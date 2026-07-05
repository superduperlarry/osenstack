"""Double-entry journal posting. Append-only; Decimal only.

Sign convention: holder accounts are liability-like — a **credit** increases
the holder's balance, a **debit** decreases it. Money enters via the `funding`
system account and leaves via the `settlement` system account.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import LedgerEntry


class LedgerImbalance(Exception):
    """A journal that does not sum to zero per currency. Never posted."""


@dataclass(frozen=True)
class EntrySpec:
    account_id: str
    direction: str  # debit | credit
    amount: Decimal  # always positive
    currency: str


async def post_journal(
    session: AsyncSession,
    entries: list[EntrySpec],
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> str:
    """Insert a balanced journal; returns the journal id. Raises LedgerImbalance otherwise."""
    if len(entries) < 2:
        raise LedgerImbalance("A journal needs at least two entries.")

    totals: dict[str, Decimal] = {}
    for spec in entries:
        if not isinstance(spec.amount, Decimal):  # floats are a rejected change
            raise TypeError(f"Ledger amounts must be Decimal, got {type(spec.amount).__name__}")
        if spec.amount <= 0:
            raise LedgerImbalance("Entry amounts must be positive; direction carries the sign.")
        if spec.direction not in ("debit", "credit"):
            raise LedgerImbalance(f"Unknown direction {spec.direction!r}")
        signed = spec.amount if spec.direction == "credit" else -spec.amount
        totals[spec.currency] = totals.get(spec.currency, Decimal("0")) + signed

    unbalanced = {ccy: total for ccy, total in totals.items() if total != 0}
    if unbalanced:
        raise LedgerImbalance(f"Journal does not balance: {unbalanced}")

    journal_id = ids.new_id(ids.JOURNAL)
    for spec in entries:
        session.add(
            LedgerEntry(
                id=ids.new_id(ids.LEDGER_ENTRY),
                journal_id=journal_id,
                account_id=spec.account_id,
                direction=spec.direction,
                amount=spec.amount,
                currency=spec.currency,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
    return journal_id
