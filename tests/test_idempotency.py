"""Idempotency-Key: required on mutation, replay on same body, 409 on drift."""

from uuid import uuid4

from tests.conftest import make_agent, ok_headers


async def test_missing_key_rejected(client, owner):
    r = await client.post(
        "/v1/agents", json={"display_name": "A"}, headers=ok_headers(owner, idem=False)
    )
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["request_id"].startswith("req_")


async def test_short_key_rejected(client, owner):
    headers = ok_headers(owner, idem=False) | {"Idempotency-Key": "too-short"}
    r = await client.post("/v1/agents", json={"display_name": "A"}, headers=headers)
    assert r.status_code == 400


async def test_same_key_same_body_replays(client, owner):
    headers = ok_headers(owner)
    body = {"display_name": "Replayed Agent"}

    first = await client.post("/v1/agents", json=body, headers=headers)
    assert first.status_code == 201

    second = await client.post("/v1/agents", json=body, headers=headers)
    assert second.status_code == 201
    assert second.headers.get("idempotency-replayed") == "true"
    assert second.json()["id"] == first.json()["id"]  # no second agent created

    r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {owner['key']}"})
    names = [a["display_name"] for a in r.json()["data"]]
    assert names.count("Replayed Agent") == 1


async def test_same_key_different_body_conflicts(client, owner):
    headers = ok_headers(owner)
    first = await client.post("/v1/agents", json={"display_name": "One"}, headers=headers)
    assert first.status_code == 201

    conflict = await client.post("/v1/agents", json={"display_name": "Two"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


async def test_keys_are_scoped_per_credential(client, owner):
    """Same key under a different credential is independent (keyed by credential+key)."""
    setup = await make_agent(client, owner)
    shared_key = str(uuid4())

    r1 = await client.post(
        "/v1/counterparties",
        json={"display_name": "Cpty A", "destination": {"type": "bank_account", "account_number": "111122223333"}},
        headers=ok_headers(owner, idem=False) | {"Idempotency-Key": shared_key},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/v1/counterparties",
        json={"display_name": "Cpty B", "destination": {"type": "bank_account", "account_number": "444455556666"}},
        headers={"Authorization": f"Bearer {setup['token']}", "Idempotency-Key": shared_key},
    )
    # Different credential, same key, different body — NOT a conflict.
    assert r2.status_code == 201
    assert r2.json()["id"] != r1.json()["id"]


async def test_error_responses_replay_too(client, owner):
    """A 4xx outcome is pinned to the key as well."""
    setup = await make_agent(client, owner, fund=None)  # zero balance
    cpty = await client.post(
        "/v1/counterparties",
        json={"display_name": "Poor Target", "destination": {"type": "bank_account", "account_number": "999900001111"}},
        headers=ok_headers(owner),
    )
    headers = ok_headers(owner)
    body = {
        "agent_id": setup["agent"]["id"],
        "counterparty_id": cpty.json()["id"],
        "amount": {"amount": "50.00", "currency": "USD"},
    }
    first = await client.post("/v1/payments", json=body, headers=headers)
    assert first.status_code == 409
    assert first.json()["code"] == "insufficient_funds"

    replay = await client.post("/v1/payments", json=body, headers=headers)
    assert replay.status_code == 409
    assert replay.headers.get("idempotency-replayed") == "true"
