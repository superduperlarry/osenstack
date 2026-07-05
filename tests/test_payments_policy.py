"""API-level policy paths: allow → 201, hold → 202 + Approval, deny → 403.
Every evaluation writes a policy.evaluation ActivityEvent."""

from tests.conftest import ac_headers, make_agent, make_counterparty, ok_headers


async def _policy_events(client, token: str) -> list[dict]:
    r = await client.get(
        "/v1/activity",
        params={"type": "policy.evaluation"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    return r.json()["data"]


async def test_allow_path_201_and_completed(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "100.00", "currency": "USD"},
            "purpose": "unit test allow path",
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 201, r.text
    payment = r.json()
    assert payment["status"] == "completed"  # sandbox rail settles instantly
    assert payment["credential_id"] == setup["credential_id"]  # attribution is structural
    assert payment["rail"] == "fps"

    balance = await client.get(
        f"/v1/agents/{setup['agent']['id']}/balance",
        headers={"Authorization": f"Bearer {setup['token']}"},
    )
    assert balance.json()["available"]["amount"].startswith("900.00")

    events = await _policy_events(client, setup["token"])
    assert any(e["data"]["outcome"] == "allow" for e in events)


async def test_hold_path_202_approval_and_reservation(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "300.00", "currency": "USD"},  # > require_approval_above 200
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 202, r.text  # held, never an error
    payment = r.json()
    assert payment["status"] == "pending_approval"
    assert payment["approval_id"] is not None

    approval = await client.get(
        f"/v1/approvals/{payment['approval_id']}",
        headers={"Authorization": f"Bearer {setup['token']}"},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "pending"
    assert approval.json()["trigger"] == "require_approval_above"

    balance = await client.get(
        f"/v1/agents/{setup['agent']['id']}/balance",
        headers={"Authorization": f"Bearer {setup['token']}"},
    )
    body = balance.json()
    assert body["pending_out"]["amount"].startswith("300.00")
    assert body["available"]["amount"].startswith("700.00")

    events = await _policy_events(client, setup["token"])
    assert any(e["data"]["outcome"] == "hold" for e in events)


async def test_deny_path_403_envelope_and_event(client, owner):
    setup = await make_agent(client, owner)
    # Cross-currency to EUR requires a quote; EUR is not on the currency allowlist.
    cpty = await make_counterparty(client, owner, verified=True, currency="EUR", country="DE")

    quote = await client.post(
        "/v1/quotes",
        json={
            "agent_id": setup["agent"]["id"],
            "source_amount": {"amount": "50.00", "currency": "USD"},
            "destination_currency": "EUR",
        },
        headers=ac_headers(setup["token"]),
    )
    assert quote.status_code == 201, quote.text

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "quote_id": quote.json()["id"],
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["code"] == "policy_denied"
    assert body["details"]["rule"] == "currency_allowlist"
    assert body["request_id"].startswith("req_")

    # The denial's evaluation record survives the rolled-back request.
    events = await _policy_events(client, setup["token"])
    assert any(e["data"]["outcome"] == "deny" for e in events)


async def test_deny_all_default_policy(client, owner):
    setup = await make_agent(client, owner, policy=None)  # version 0 = deny-all
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "1.00", "currency": "USD"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 403
    assert r.json()["details"]["rule"] == "no_policy"


async def test_owner_initiated_payment_skips_policy(client, owner):
    """The owner is the approver — owner-key payments aren't policy-gated."""
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "400.00", "currency": "USD"},  # above the hold threshold
        },
        headers=ok_headers(owner),
    )
    assert r.status_code == 201


async def test_insufficient_funds_is_409_before_policy(client, owner):
    setup = await make_agent(client, owner, fund="10.00")
    cpty = await make_counterparty(client, owner, verified=True)

    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "50.00", "currency": "USD"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "insufficient_funds"


async def test_agent_created_counterparty_raises_approval(client, owner):
    setup = await make_agent(client, owner)
    r = await client.post(
        "/v1/counterparties",
        json={
            "display_name": "New Vendor",
            "destination": {"type": "bank_account", "account_number": "777788889999"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 201  # response stays 201 per spec; the approval gates payments
    assert r.json()["status"] == "unverified"

    approvals = await client.get(
        "/v1/approvals", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    pending = [a for a in approvals.json()["data"] if a["action_type"] == "counterparty"]
    assert len(pending) == 1
    assert pending[0]["trigger"] == "new_counterparty"
