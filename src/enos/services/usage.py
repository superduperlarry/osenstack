"""Usage aggregates feeding policy limit evaluation.

Counts everything that consumes or reserves the agent's funds today/this month:
payments and agent-initiated transfers in pending_approval / processing /
completed / returned states. Cancelled and failed actions do not count.
"""

from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from enos.models import Payment, Transfer
from enos.models.base import utcnow

_COUNTED_PAYMENT_STATUSES = ("pending_approval", "processing", "completed", "returned")
_COUNTED_TRANSFER_STATUSES = ("pending_approval", "completed")


def _day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def spend_aggregates(session: AsyncSession, agent_id: str) -> tuple[Decimal, Decimal, int]:
    """Returns (daily_spend, monthly_spend, transactions_today) in the owner currency."""
    now = utcnow()
    day, month = _day_start(now), _month_start(now)

    async def _window(since: datetime) -> tuple[Decimal, int]:
        pay_q = select(
            func.coalesce(func.sum(Payment.source_amount), 0), func.count(Payment.id)
        ).where(
            Payment.agent_id == agent_id,
            Payment.status.in_(_COUNTED_PAYMENT_STATUSES),
            Payment.created_at >= since,
        )
        pay_total, pay_count = (await session.execute(pay_q)).one()
        trf_q = select(
            func.coalesce(func.sum(Transfer.amount), 0), func.count(Transfer.id)
        ).where(
            Transfer.agent_id == agent_id,
            Transfer.status.in_(_COUNTED_TRANSFER_STATUSES),
            Transfer.created_at >= since,
        )
        trf_total, trf_count = (await session.execute(trf_q)).one()
        return Decimal(pay_total) + Decimal(trf_total), int(pay_count) + int(trf_count)

    daily, tx_today = await _window(day)
    monthly, _ = await _window(month)
    return daily, monthly, tx_today
