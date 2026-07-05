"""Bearer auth resolution and tenant/owner isolation on every query."""

from tests.conftest import ac_headers, make_agent, make_counterparty, ok_headers


async def test_missing_token_401(client):
    r = await client.get("/v1/owner")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


async def test_garbage_token_401(client):
    r = await client.get("/v1/owner", headers={"Authorization": "Bearer nonsense_token_here"})
    assert r.status_code == 401


async def test_owner_key_resolves_owner_scope(client, owner):
    r = await client.get("/v1/owner", headers={"Authorization": f"Bearer {owner['key']}"})
    assert r.status_code == 200
    assert r.json()["id"] == owner["id"]


async def test_agent_credential_cannot_use_owner_endpoints(client, owner):
    setup = await make_agent(client, owner)
    headers = {"Authorization": f"Bearer {setup['token']}"}

    assert (await client.get("/v1/owner", headers=headers)).status_code == 403
    r = await client.post(
        "/v1/agents", json={"display_name": "Nope"}, headers=ac_headers(setup["token"])
    )
    assert r.status_code == 403
    r = await client.put(
        f"/v1/agents/{setup['agent']['id']}/policy",
        json={"limits": {}, "approvals": {}},
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 403  # an agent can never widen its own box


async def test_agent_sees_only_its_own_resources(client, owner):
    agent_a = await make_agent(client, owner)
    agent_b = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": agent_a["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "10.00", "currency": "USD"},
        },
        headers=ac_headers(agent_a["token"]),
    )
    assert r.status_code == 201
    payment_id = r.json()["id"]

    # Agent B cannot see agent A's payment — 404, not 403 (no existence leak).
    r = await client.get(
        f"/v1/payments/{payment_id}", headers={"Authorization": f"Bearer {agent_b['token']}"}
    )
    assert r.status_code == 404

    r = await client.get("/v1/payments", headers={"Authorization": f"Bearer {agent_b['token']}"})
    assert r.json()["data"] == []

    # Agent B cannot read agent A's balance or act as it.
    r = await client.get(
        f"/v1/agents/{agent_a['agent']['id']}/balance",
        headers={"Authorization": f"Bearer {agent_b['token']}"},
    )
    assert r.status_code == 404
    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": agent_a["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "10.00", "currency": "USD"},
        },
        headers=ac_headers(agent_b["token"]),
    )
    assert r.status_code == 404  # an agent cannot name another agent


async def test_cross_owner_isolation(client, owner):
    from decimal import Decimal

    from enos import ids
    from enos.db import get_sessionmaker
    from enos.models import Owner
    from enos.services import ledger
    from enos.services.credentials import issue_owner_key

    async with get_sessionmaker()() as session:
        other = Owner(
            id=ids.new_id(ids.OWNER),
            type="business",
            legal_name="Rival Corp",
            verification_status="verified",
            country="HK",
            default_currency="USD",
        )
        session.add(other)
        await session.flush()
        _, other_key = await issue_owner_key(session, other)
        await ledger.fund(
            session, owner=other, holder_type="owner", holder_id=other.id, amount=Decimal("5")
        )
        await session.commit()

    setup = await make_agent(client, owner)

    other_headers = {"Authorization": f"Bearer {other_key}"}
    r = await client.get(f"/v1/agents/{setup['agent']['id']}", headers=other_headers)
    assert r.status_code == 404  # owner B cannot see owner A's agent

    r = await client.get("/v1/agents", headers=other_headers)
    assert r.json()["data"] == []

    r = await client.get("/v1/balances", headers=other_headers)
    holders = {b["holder_id"] for b in r.json()["data"]}
    assert setup["agent"]["id"] not in holders
    assert owner["id"] not in holders


async def test_suspended_agent_credentials_stop_authenticating(client, owner):
    setup = await make_agent(client, owner)
    headers = {"Authorization": f"Bearer {setup['token']}"}
    assert (await client.get("/v1/payments", headers=headers)).status_code == 200

    r = await client.post(
        f"/v1/agents/{setup['agent']['id']}/suspend", headers=ok_headers(owner)
    )
    assert r.status_code == 200

    assert (await client.get("/v1/payments", headers=headers)).status_code == 401

    r = await client.post(
        f"/v1/agents/{setup['agent']['id']}/reactivate", headers=ok_headers(owner)
    )
    assert r.status_code == 200
    assert (await client.get("/v1/payments", headers=headers)).status_code == 200


async def test_revoked_credential_401(client, owner):
    setup = await make_agent(client, owner)
    r = await client.post(
        f"/v1/credentials/{setup['credential_id']}/revoke", headers=ok_headers(owner)
    )
    assert r.status_code == 200
    r = await client.get(
        "/v1/payments", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    assert r.status_code == 401


async def test_scope_enforcement(client, owner):
    setup = await make_agent(client, owner, scopes=["balance:read"])
    r = await client.post(
        "/v1/payments",
        json={"agent_id": setup["agent"]["id"], "counterparty_id": "cpt_x", "amount": {"amount": "1", "currency": "USD"}},
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "insufficient_scope"


async def test_card_freeze_unfreeze_asymmetry(client, owner):
    setup = await make_agent(client, owner)
    r = await client.post(
        f"/v1/agents/{setup['agent']['id']}/cards",
        json={"label": "ops card"},
        headers=ok_headers(owner),
    )
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]

    # The agent may freeze its own card…
    r = await client.post(f"/v1/cards/{card_id}/freeze", headers=ac_headers(setup["token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "frozen"

    # …but never unfreeze it.
    r = await client.post(f"/v1/cards/{card_id}/unfreeze", headers=ac_headers(setup["token"]))
    assert r.status_code == 403

    r = await client.post(f"/v1/cards/{card_id}/unfreeze", headers=ok_headers(owner))
    assert r.status_code == 200
    assert r.json()["status"] == "active"
