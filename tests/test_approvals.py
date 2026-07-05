"""Human-in-the-loop: approve executes, reject cancels + releases, expiry works."""

from tests.conftest import ac_headers, make_agent, make_counterparty, ok_headers


async def _held_payment(client, owner, setup, cpty, amount="300.00"):
    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": amount, "currency": "USD"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 202, r.text
    return r.json()


async def _balance(client, setup):
    r = await client.get(
        f"/v1/agents/{setup['agent']['id']}/balance",
        headers={"Authorization": f"Bearer {setup['token']}"},
    )
    return r.json()


async def test_approve_executes_payment(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    r = await client.post(
        f"/v1/approvals/{payment['approval_id']}/approve",
        json={"note": "looks right"},
        headers=ok_headers(owner),
    )
    assert r.status_code == 200, r.text
    approval = r.json()
    assert approval["status"] == "approved"
    assert approval["note"] == "looks right"

    r = await client.get(
        f"/v1/payments/{payment['id']}", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    assert r.json()["status"] == "completed"
    statuses = [t["status"] for t in r.json()["timeline"]]
    assert statuses == ["pending_approval", "processing", "completed"]

    balance = await _balance(client, setup)
    assert balance["pending_out"]["amount"].startswith("0")
    assert balance["available"]["amount"].startswith("700.00")


async def test_reject_cancels_and_releases(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    r = await client.post(
        f"/v1/approvals/{payment['approval_id']}/reject",
        json={"note": "not this vendor"},
        headers=ok_headers(owner),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    r = await client.get(
        f"/v1/payments/{payment['id']}", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    assert r.json()["status"] == "cancelled"
    assert r.json()["failure_reason"] == "owner_rejected"

    balance = await _balance(client, setup)
    assert balance["available"]["amount"].startswith("1000.00")  # fully restored
    assert balance["pending_out"]["amount"].startswith("0")


async def test_agent_cannot_decide_approvals(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    r = await client.post(
        f"/v1/approvals/{payment['approval_id']}/approve",
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 403  # owner scope only — the asymmetry is the product


async def test_double_decision_conflicts(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    r = await client.post(
        f"/v1/approvals/{payment['approval_id']}/approve", headers=ok_headers(owner)
    )
    assert r.status_code == 200
    r = await client.post(
        f"/v1/approvals/{payment['approval_id']}/reject", headers=ok_headers(owner)
    )
    assert r.status_code == 409
    assert r.json()["code"] == "approval_not_pending"


async def test_cancel_held_payment_releases_funds(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    r = await client.post(
        f"/v1/payments/{payment['id']}/cancel", headers=ac_headers(setup["token"])
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    balance = await _balance(client, setup)
    assert balance["available"]["amount"].startswith("1000.00")


async def test_expiry_task_expires_and_releases(client, owner):
    setup = await make_agent(client, owner)
    cpty = await make_counterparty(client, owner, verified=True)
    payment = await _held_payment(client, owner, setup, cpty)

    from sqlalchemy import text

    from enos.db import get_sessionmaker
    from enos.services.approvals import expire_stale

    async with get_sessionmaker()() as session:
        # Backdate the expiry (approvals are decidable state, not append-only).
        await session.execute(
            text("UPDATE approvals SET expires_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": payment["approval_id"]},
        )
        await session.commit()

    async with get_sessionmaker()() as session:
        count = await expire_stale(session)
        await session.commit()
    assert count == 1

    r = await client.get(
        f"/v1/approvals/{payment['approval_id']}", headers=ok_headers(owner, idem=False)
    )
    assert r.json()["status"] == "expired"
    r = await client.get(
        f"/v1/payments/{payment['id']}", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    assert r.json()["status"] == "cancelled"
    balance = await _balance(client, setup)
    assert balance["available"]["amount"].startswith("1000.00")


async def test_approving_counterparty_verifies_it(client, owner):
    setup = await make_agent(client, owner)
    r = await client.post(
        "/v1/counterparties",
        json={
            "display_name": "Held Vendor",
            "destination": {"type": "bank_account", "account_number": "121212343434"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 201
    cpty_id = r.json()["id"]

    approvals = await client.get(
        "/v1/approvals",
        params={"status": "pending", "agent_id": setup["agent"]["id"]},
        headers=ok_headers(owner, idem=False),
    )
    approval = next(a for a in approvals.json()["data"] if a["action_id"] == cpty_id)

    r = await client.post(f"/v1/approvals/{approval['id']}/approve", headers=ok_headers(owner))
    assert r.status_code == 200

    r = await client.get(
        f"/v1/counterparties/{cpty_id}", headers={"Authorization": f"Bearer {setup['token']}"}
    )
    assert r.json()["status"] == "verified"
