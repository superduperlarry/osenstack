"""Ledger accounts, materialized balances, and funds movement primitives.

Invariant kept everywhere: `balance.available == derived_ledger_balance - pending_out`
(a test recomputes balances from entries and asserts agreement).
Reservations (policy holds) move value between available and pending_out
without a journal — money hasn't moved; a hold is not a posting.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.ledger.posting import EntrySpec, post_journal
from enos.models import Balance, LedgerAccount, Owner
from enos.services.errors import ApiError

SYSTEM_SETTLEMENT = "settlement"
SYSTEM_FUNDING = "funding"


async def get_or_create_account(
    session: AsyncSession,
    *,
    owner_id: str | None,
    holder_type: str,
    holder_id: str,
    currency: str,
) -> LedgerAccount:
    q = select(LedgerAccount).where(
        LedgerAccount.holder_type == holder_type,
        LedgerAccount.holder_id == holder_id,
        LedgerAccount.currency == currency,
    )
    account = (await session.execute(q)).scalar_one_or_none()
    if account is None:
        account = LedgerAccount(
            id=ids.new_id(ids.LEDGER_ACCOUNT),
            owner_id=owner_id,
            holder_type=holder_type,
            holder_id=holder_id,
            currency=currency,
        )
        session.add(account)
        await session.flush()
    return account


async def system_account(session: AsyncSession, name: str, currency: str) -> LedgerAccount:
    return await get_or_create_account(
        session, owner_id=None, holder_type="system", holder_id=name, currency=currency
    )


async def get_or_create_balance(
    session: AsyncSession, *, owner: Owner, holder_type: str, holder_id: str
) -> Balance:
    q = select(Balance).where(Balance.holder_type == holder_type, Balance.holder_id == holder_id)
    balance = (await session.execute(q)).scalar_one_or_none()
    if balance is None:
        balance = Balance(
            id=ids.new_id(ids.BALANCE),
            owner_id=owner.id,
            holder_type=holder_type,
            holder_id=holder_id,
            currency=owner.default_currency,
            available=Decimal("0"),
            pending_out=Decimal("0"),
            breakdown=[],
        )
        session.add(balance)
        await session.flush()
    return balance


def _sync_breakdown(balance: Balance) -> None:
    balance.breakdown = [{"amount": str(balance.available), "currency": balance.currency}]


async def fund(
    session: AsyncSession,
    *,
    owner: Owner,
    holder_type: str,
    holder_id: str,
    amount: Decimal,
    resource_type: str = "funding",
    resource_id: str | None = None,
) -> str:
    """Credit a holder from the funding system account (sandbox top-ups, inbound credits)."""
    currency = owner.default_currency
    holder_acct = await get_or_create_account(
        session, owner_id=owner.id, holder_type=holder_type, holder_id=holder_id, currency=currency
    )
    funding_acct = await system_account(session, SYSTEM_FUNDING, currency)
    journal_id = await post_journal(
        session,
        [
            EntrySpec(funding_acct.id, "debit", amount, currency),
            EntrySpec(holder_acct.id, "credit", amount, currency),
        ],
        resource_type=resource_type,
        resource_id=resource_id,
    )
    balance = await get_or_create_balance(
        session, owner=owner, holder_type=holder_type, holder_id=holder_id
    )
    balance.available = balance.available + amount
    _sync_breakdown(balance)
    return journal_id


def ensure_available(balance: Balance, amount: Decimal) -> None:
    if balance.available < amount:
        raise ApiError(
            409,
            "insufficient_funds",
            "Balance is insufficient for this action.",
            {"available": str(balance.available), "requested": str(amount)},
        )


async def reserve(session: AsyncSession, balance: Balance, amount: Decimal) -> None:
    """Hold funds pending approval: available → pending_out. No journal."""
    ensure_available(balance, amount)
    balance.available = balance.available - amount
    balance.pending_out = balance.pending_out + amount
    _sync_breakdown(balance)


async def release_reservation(session: AsyncSession, balance: Balance, amount: Decimal) -> None:
    """Reverse a hold (rejected / cancelled / expired)."""
    balance.pending_out = balance.pending_out - amount
    balance.available = balance.available + amount
    _sync_breakdown(balance)


async def pay_out(
    session: AsyncSession,
    *,
    owner: Owner,
    holder_type: str,
    holder_id: str,
    amount: Decimal,
    resource_type: str,
    resource_id: str,
    from_reservation: bool = False,
) -> str:
    """Post the outbound journal: debit holder, credit settlement.

    `from_reservation=True` consumes a prior hold (pending_out) instead of available.
    """
    currency = owner.default_currency
    holder_acct = await get_or_create_account(
        session, owner_id=owner.id, holder_type=holder_type, holder_id=holder_id, currency=currency
    )
    settlement_acct = await system_account(session, SYSTEM_SETTLEMENT, currency)
    balance = await get_or_create_balance(
        session, owner=owner, holder_type=holder_type, holder_id=holder_id
    )
    if from_reservation:
        balance.pending_out = balance.pending_out - amount
    else:
        ensure_available(balance, amount)
        balance.available = balance.available - amount
    _sync_breakdown(balance)
    return await post_journal(
        session,
        [
            EntrySpec(holder_acct.id, "debit", amount, currency),
            EntrySpec(settlement_acct.id, "credit", amount, currency),
        ],
        resource_type=resource_type,
        resource_id=resource_id,
    )


async def internal_transfer(
    session: AsyncSession,
    *,
    owner: Owner,
    source_type: str,
    source_id: str,
    destination_type: str,
    destination_id: str,
    amount: Decimal,
    resource_id: str,
    from_reservation: bool = False,
) -> str:
    """Instant internal move: debit source holder, credit destination holder."""
    currency = owner.default_currency
    src_acct = await get_or_create_account(
        session, owner_id=owner.id, holder_type=source_type, holder_id=source_id, currency=currency
    )
    dst_acct = await get_or_create_account(
        session,
        owner_id=owner.id,
        holder_type=destination_type,
        holder_id=destination_id,
        currency=currency,
    )
    src_balance = await get_or_create_balance(
        session, owner=owner, holder_type=source_type, holder_id=source_id
    )
    dst_balance = await get_or_create_balance(
        session, owner=owner, holder_type=destination_type, holder_id=destination_id
    )
    if from_reservation:
        src_balance.pending_out = src_balance.pending_out - amount
    else:
        ensure_available(src_balance, amount)
        src_balance.available = src_balance.available - amount
    dst_balance.available = dst_balance.available + amount
    _sync_breakdown(src_balance)
    _sync_breakdown(dst_balance)
    return await post_journal(
        session,
        [
            EntrySpec(src_acct.id, "debit", amount, currency),
            EntrySpec(dst_acct.id, "credit", amount, currency),
        ],
        resource_type="transfer",
        resource_id=resource_id,
    )
