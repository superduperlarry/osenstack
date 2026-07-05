"""Ledger invariants: journals balance, balances derive from entries,
append-only tables reject mutation at the database level."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import ac_headers, make_agent, make_counterparty


async def _session():
    from enos.db import get_sessionmaker

    return get_sessionmaker()()


async def _run_money_traffic(client, owner):
    """Fund, transfer, pay (allow), and hold — a representative mix."""
    setup = await make_agent(client, owner)  # includes a 1000 USD funding transfer
    cpty = await make_counterparty(client, owner, verified=True)
    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "150.00", "currency": "USD"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 201
    r = await client.post(
        "/v1/payments",
        json={
            "agent_id": setup["agent"]["id"],
            "counterparty_id": cpty["id"],
            "amount": {"amount": "250.00", "currency": "USD"},
        },
        headers=ac_headers(setup["token"]),
    )
    assert r.status_code == 202  # held: reservation, no journal
    return setup


async def test_every_journal_sums_to_zero(client, owner):
    await _run_money_traffic(client, owner)
    async with await _session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT journal_id, currency,
                           SUM(CASE WHEN direction = 'credit' THEN amount ELSE -amount END) AS net
                    FROM ledger_entries GROUP BY journal_id, currency
                    """
                )
            )
        ).all()
        assert rows, "expected journals to exist"
        for journal_id, currency, net in rows:
            assert net == Decimal("0"), f"journal {journal_id} unbalanced in {currency}: {net}"


async def test_balances_derive_from_entries(client, owner):
    """available == (credits - debits per holder account) - pending_out, always."""
    await _run_money_traffic(client, owner)
    async with await _session() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT b.holder_type, b.holder_id, b.available, b.pending_out,
                           COALESCE(SUM(CASE WHEN le.direction = 'credit' THEN le.amount
                                             ELSE -le.amount END), 0) AS derived
                    FROM balances b
                    LEFT JOIN ledger_accounts la
                      ON la.holder_type = b.holder_type AND la.holder_id = b.holder_id
                    LEFT JOIN ledger_entries le ON le.account_id = la.id
                    GROUP BY b.holder_type, b.holder_id, b.available, b.pending_out
                    """
                )
            )
        ).all()
        assert rows
        for holder_type, holder_id, available, pending_out, derived in rows:
            assert available == derived - pending_out, (
                f"{holder_type}/{holder_id}: available={available} "
                f"derived={derived} pending_out={pending_out}"
            )


async def test_no_floats_in_ledger_amounts(client, owner):
    from enos.ledger.posting import EntrySpec, post_journal

    async with await _session() as session:
        with pytest.raises(TypeError):
            await post_journal(
                session,
                [
                    EntrySpec("acc_a", "debit", 10.0, "USD"),  # type: ignore[arg-type]
                    EntrySpec("acc_b", "credit", Decimal("10"), "USD"),
                ],
            )


async def test_unbalanced_journal_rejected():
    from enos.ledger.posting import EntrySpec, LedgerImbalance, post_journal

    async with await _session() as session:
        with pytest.raises(LedgerImbalance):
            await post_journal(
                session,
                [
                    EntrySpec("acc_a", "debit", Decimal("10"), "USD"),
                    EntrySpec("acc_b", "credit", Decimal("9"), "USD"),
                ],
            )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_entries SET amount = amount + 1",
        "DELETE FROM ledger_entries",
        "UPDATE activity_events SET type = 'tampered'",
        "DELETE FROM activity_events",
        "UPDATE policies SET version = 999",
        "DELETE FROM policies",
    ],
)
async def test_append_only_tables_reject_mutation(client, owner, statement):
    await _run_money_traffic(client, owner)
    async with await _session() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text(statement))
        await session.rollback()


async def test_mcp_audit_append_only(client, owner):
    from enos import ids
    from enos.models import McpAudit

    async with await _session() as session:
        session.add(
            McpAudit(
                id=ids.new_id(ids.MCP_AUDIT),
                owner_id=owner["id"],
                agent_id="agt_x",
                credential_id="crd_x",
                tool="get_balance",
                args_hash="0" * 64,
                result_status="ok",
                request_id="req_x",
            )
        )
        await session.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("DELETE FROM mcp_audit"))
        await session.rollback()
