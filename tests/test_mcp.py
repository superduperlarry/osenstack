"""MCP server: 19 tools exactly, thin wrappers over the service layer,
every invocation audited in mcp_audit."""

import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.conftest import make_agent, make_counterparty

EXPECTED_TOOLS = {
    "get_balance",
    "get_funding_instructions",
    "get_policy",
    "create_quote",
    "get_quote",
    "create_payment",
    "get_payment",
    "list_payments",
    "cancel_payment",
    "create_transfer",
    "list_transfers",
    "create_counterparty",
    "list_counterparties",
    "get_counterparty",
    "list_cards",
    "freeze_card",
    "list_approvals",
    "get_approval",
    "list_activity",
}

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest_asyncio.fixture(scope="session")
async def mcp_client():
    """Runs the MCP session manager in its own task — anyio cancel scopes must
    enter and exit in the same task, which fixture teardown can't guarantee."""
    import asyncio

    from enos.mcp.app import app, mcp

    started = asyncio.Event()
    stop = asyncio.Event()

    async def runner():
        async with mcp.session_manager.run():
            started.set()
            await stop.wait()

    task = asyncio.create_task(runner())
    await started.wait()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        stop.set()
        await task


async def _rpc(mcp_client, method: str, params: dict | None = None, token: str | None = None):
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    r = await mcp_client.post("/mcp", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _call_tool(mcp_client, name: str, arguments: dict, token: str) -> dict:
    body = await _rpc(
        mcp_client, "tools/call", {"name": name, "arguments": arguments}, token=token
    )
    assert "result" in body, body
    result = body["result"]
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


async def _audit_rows(tool: str | None = None):
    from enos.db import get_sessionmaker
    from enos.models import McpAudit

    async with get_sessionmaker()() as session:
        q = select(McpAudit)
        if tool:
            q = q.where(McpAudit.tool == tool)
        return list((await session.execute(q)).scalars())


async def test_catalog_is_exactly_19_tools(mcp_client):
    body = await _rpc(mcp_client, "tools/list")
    tools = {t["name"] for t in body["result"]["tools"]}
    assert tools == EXPECTED_TOOLS
    assert len(tools) == 19


async def test_owner_capabilities_absent(mcp_client):
    """Agents operate inside the box; only the owner reshapes it."""
    body = await _rpc(mcp_client, "tools/list")
    tools = {t["name"] for t in body["result"]["tools"]}
    for forbidden in (
        "create_agent", "suspend_agent", "create_credential", "revoke_credential",
        "replace_policy", "put_policy", "approve_approval", "reject_approval",
        "verify_counterparty", "unfreeze_card", "create_webhook_endpoint", "create_card",
    ):
        assert forbidden not in tools


async def test_get_balance_and_audit(client, owner, mcp_client):
    setup = await make_agent(client, owner, credential_kind="mcp")
    result = await _call_tool(mcp_client, "get_balance", {}, setup["token"])
    assert result["balance"]["available"]["amount"].startswith("1000.00")
    assert result["request_id"].startswith("req_")

    rows = await _audit_rows("get_balance")
    assert len(rows) == 1
    assert rows[0].credential_id == setup["credential_id"]
    assert rows[0].agent_id == setup["agent"]["id"]
    assert rows[0].owner_id == owner["id"]
    assert rows[0].result_status == "ok"


async def test_api_kind_credential_rejected(client, owner, mcp_client):
    setup = await make_agent(client, owner, credential_kind="api")
    result = await _call_tool(mcp_client, "get_balance", {}, setup["token"])
    assert result["outcome"] == "error"
    assert result["error"]["code"] == "unauthorized"


async def test_owner_key_rejected(client, owner, mcp_client):
    result = await _call_tool(mcp_client, "get_balance", {}, owner["key"])
    assert result["outcome"] == "error"
    assert result["error"]["code"] == "unauthorized"


async def test_create_payment_three_outcomes(client, owner, mcp_client):
    setup = await make_agent(client, owner, credential_kind="mcp")
    cpty = await make_counterparty(client, owner, verified=True)

    # processing
    result = await _call_tool(
        mcp_client,
        "create_payment",
        {
            "counterparty_id": cpty["id"],
            "amount": {"amount": "50.00", "currency": "USD"},
            "purpose": "mcp allow path",
        },
        setup["token"],
    )
    assert result["outcome"] == "processing"
    assert result["payment"]["status"] == "completed"

    # pending_approval — not an error; approval_id returned for polling
    result = await _call_tool(
        mcp_client,
        "create_payment",
        {"counterparty_id": cpty["id"], "amount": {"amount": "300.00", "currency": "USD"}},
        setup["token"],
    )
    assert result["outcome"] == "pending_approval"
    assert result["approval_id"].startswith("apr_")

    approvals = await _call_tool(mcp_client, "list_approvals", {}, setup["token"])
    assert any(a["id"] == result["approval_id"] for a in approvals["approvals"])

    # policy_denied — reported as an outcome, not a raised error
    quote = await _call_tool(
        mcp_client,
        "create_quote",
        {
            "destination_currency": "EUR",
            "source_amount": {"amount": "10.00", "currency": "USD"},
        },
        setup["token"],
    )
    assert quote["outcome"] == "created"
    cpty_eur = await make_counterparty(client, owner, verified=True, currency="EUR", country="DE")
    result = await _call_tool(
        mcp_client,
        "create_payment",
        {"counterparty_id": cpty_eur["id"], "quote_id": quote["quote"]["id"]},
        setup["token"],
    )
    assert result["outcome"] == "policy_denied"
    assert result["denial"]["details"]["rule"] == "currency_allowlist"

    denied_audit = [r for r in await _audit_rows("create_payment") if r.result_status == "denied"]
    assert len(denied_audit) == 1


async def test_mcp_idempotency_key_replay(client, owner, mcp_client):
    setup = await make_agent(client, owner, credential_kind="mcp")
    cpty = await make_counterparty(client, owner, verified=True)
    args = {
        "counterparty_id": cpty["id"],
        "amount": {"amount": "25.00", "currency": "USD"},
        "idempotency_key": "mcp-test-key-0001",
    }
    first = await _call_tool(mcp_client, "create_payment", args, setup["token"])
    second = await _call_tool(mcp_client, "create_payment", args, setup["token"])
    assert second["payment"]["id"] == first["payment"]["id"]  # replayed, not re-executed

    rows = await _audit_rows("create_payment")
    assert len(rows) == 2  # both invocations audited
    assert all(r.idempotency_key == "mcp-test-key-0001" for r in rows)


async def test_freeze_card_but_no_unfreeze(client, owner, mcp_client):
    setup = await make_agent(client, owner, credential_kind="mcp")
    from tests.conftest import ok_headers

    r = await client.post(
        f"/v1/agents/{setup['agent']['id']}/cards",
        json={"label": "mcp card"},
        headers=ok_headers(owner),
    )
    card_id = r.json()["id"]

    result = await _call_tool(mcp_client, "freeze_card", {"card_id": card_id}, setup["token"])
    assert result["outcome"] == "frozen"

    body = await _rpc(mcp_client, "tools/list")
    assert "unfreeze_card" not in {t["name"] for t in body["result"]["tools"]}
