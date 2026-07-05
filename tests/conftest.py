"""Test harness: embedded Postgres (pgserver) + the real Alembic migration.

No mocked persistence anywhere — numeric money, append-only triggers, and
idempotency races only mean something on a real Postgres.
"""

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parent.parent

# Use the provided database (CI service container / compose Postgres) when set;
# otherwise boot an embedded pgserver instance — no Docker required locally.
if "ENOS_DATABASE_URL" not in os.environ:
    import pgserver

    _srv = pgserver.get_server(REPO / ".local-postgres")
    os.environ["ENOS_DATABASE_URL"] = _srv.get_uri().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
os.environ["ENOS_ENVIRONMENT"] = "test"

DB_URI = os.environ["ENOS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")

from enos.config import get_settings  # noqa: E402

get_settings.cache_clear()

TABLES = (
    "mcp_audit",
    "idempotency_keys",
    "activity_events",
    "approvals",
    "ledger_entries",
    "balances",
    "ledger_accounts",
    "payments",
    "transfers",
    "quotes",
    "cards",
    "virtual_accounts",
    "counterparties",
    "webhook_endpoints",
    "policies",
    "credentials",
    "agents",
    "owners",
)


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Fresh schema per test session, built by the real migration."""
    import asyncio

    import asyncpg

    async def reset() -> None:
        conn = await asyncpg.connect(DB_URI)
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()

    asyncio.run(reset())

    from alembic import command
    from alembic.config import Config

    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        command.upgrade(Config(str(REPO / "alembic.ini")), "head")
    finally:
        os.chdir(cwd)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    yield
    from sqlalchemy import text

    from enos.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE TABLE {', '.join(TABLES)} CASCADE"))
        await session.commit()


@pytest_asyncio.fixture
async def client():
    from enos.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def owner():
    """A verified sandbox owner with a funded treasury and an ok_ key."""
    from enos import ids
    from enos.db import get_sessionmaker
    from enos.models import Owner
    from enos.services import ledger
    from enos.services.credentials import issue_owner_key

    async with get_sessionmaker()() as session:
        record = Owner(
            id=ids.new_id(ids.OWNER),
            type="business",
            legal_name="Test Trading Pte. Ltd.",
            display_name="Test Trading",
            verification_status="verified",
            country="SG",
            default_currency="USD",
        )
        session.add(record)
        await session.flush()
        _, secret = await issue_owner_key(session, record)
        await ledger.fund(
            session,
            owner=record,
            holder_type="owner",
            holder_id=record.id,
            amount=Decimal("10000.00"),
        )
        await session.commit()
        return {"id": record.id, "key": secret, "currency": "USD", "country": "SG"}


def ok_headers(owner: dict, idem: bool = True) -> dict:
    headers = {"Authorization": f"Bearer {owner['key']}"}
    if idem:
        headers["Idempotency-Key"] = str(uuid4())
    return headers


def ac_headers(token: str, idem: bool = True) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if idem:
        headers["Idempotency-Key"] = str(uuid4())
    return headers


ALL_SCOPES = [
    "balance:read",
    "quotes:create",
    "payments:create",
    "payments:read",
    "transfers:create",
    "transfers:read",
    "counterparties:create",
    "counterparties:read",
    "cards:read",
    "cards:freeze",
    "approvals:read",
    "activity:read",
    "policy:read",
]

DEFAULT_POLICY = {
    "limits": {
        "per_transaction": {"amount": "500.00", "currency": "USD"},
        "daily": {"amount": "1000.00", "currency": "USD"},
        "monthly": {"amount": "5000.00", "currency": "USD"},
        "max_transactions_per_day": 20,
    },
    "currency_allowlist": ["USD", "PHP"],
    "approvals": {
        "require_approval_above": {"amount": "200.00", "currency": "USD"},
        "require_approval_for_new_counterparties": True,
        "require_approval_for_cross_border": False,
        "auto_expire_hours": 72,
    },
}


async def make_agent(
    client: AsyncClient,
    owner: dict,
    *,
    policy: dict | None = DEFAULT_POLICY,
    fund: str | None = "1000.00",
    credential_kind: str = "api",
    scopes: list[str] = ALL_SCOPES,
) -> dict:
    """Full agent setup through the API: create → policy → credential → fund."""
    r = await client.post(
        "/v1/agents", json={"display_name": "Test Agent"}, headers=ok_headers(owner)
    )
    assert r.status_code == 201, r.text
    agent = r.json()

    if policy is not None:
        r = await client.put(
            f"/v1/agents/{agent['id']}/policy", json=policy, headers=ok_headers(owner)
        )
        assert r.status_code == 200, r.text

    r = await client.post(
        f"/v1/agents/{agent['id']}/credentials",
        json={"kind": credential_kind, "scopes": scopes, "label": "test credential"},
        headers=ok_headers(owner),
    )
    assert r.status_code == 201, r.text
    credential = r.json()

    if fund is not None:
        r = await client.post(
            "/v1/transfers",
            json={
                "source": {"holder_type": "owner", "holder_id": owner["id"]},
                "destination": {"holder_type": "agent", "holder_id": agent["id"]},
                "amount": {"amount": fund, "currency": "USD"},
            },
            headers=ok_headers(owner),
        )
        assert r.status_code == 201, r.text

    return {"agent": agent, "token": credential["secret"], "credential_id": credential["id"]}


async def make_counterparty(
    client: AsyncClient,
    owner: dict,
    *,
    verified: bool = True,
    currency: str = "USD",
    country: str = "SG",
) -> dict:
    r = await client.post(
        "/v1/counterparties",
        json={
            "display_name": "Acme Supplies",
            "destination": {
                "type": "bank_account",
                "currency": currency,
                "country": country,
                "account_name": "Acme Supplies Ltd",
                "account_number": "000123454821",
                "bank_identifier": "ACMESGSX",
            },
        },
        headers=ok_headers(owner),
    )
    assert r.status_code == 201, r.text
    counterparty = r.json()
    if verified:
        r = await client.post(
            f"/v1/counterparties/{counterparty['id']}/verify", headers=ok_headers(owner)
        )
        assert r.status_code == 200, r.text
        counterparty = r.json()
    return counterparty
