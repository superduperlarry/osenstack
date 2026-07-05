from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos.models import Balance
from enos.services import agents as agents_service
from enos.services import ledger
from enos.services.context import Principal


async def get_owner_profile(session: AsyncSession, principal: Principal):
    principal.require_owner()
    return principal.owner


async def list_balances(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
) -> tuple[list[Balance], bool]:
    """Owner scope sees all balances (treasury + every agent); agents only their own."""
    principal.require_scope("balance:read")
    if principal.agent is not None:
        balance = await ledger.get_or_create_balance(
            session, owner=principal.owner, holder_type="agent", holder_id=principal.agent.id
        )
        return [balance], False
    await ledger.get_or_create_balance(  # ensure the treasury row exists
        session, owner=principal.owner, holder_type="owner", holder_id=principal.owner.id
    )
    q = select(Balance).where(Balance.owner_id == principal.owner.id)
    if starting_after:
        q = q.where(Balance.id < starting_after)
    q = q.order_by(Balance.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


async def get_agent_balance(session: AsyncSession, principal: Principal, agent_id: str) -> Balance:
    principal.require_scope("balance:read")
    agent = await agents_service.get_agent(session, principal, agent_id)
    return await ledger.get_or_create_balance(
        session, owner=principal.owner, holder_type="agent", holder_id=agent.id
    )
