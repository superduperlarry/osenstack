from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Agent
from enos.schemas.identity import AgentCreate, AgentUpdate
from enos.services import activity, ledger
from enos.services.context import Principal
from enos.services.errors import not_found


async def get_agent(session: AsyncSession, principal: Principal, agent_id: str) -> Agent:
    """Owner-scoped fetch with tenant isolation; agents may fetch only themselves."""
    q = select(Agent).where(Agent.id == agent_id, Agent.owner_id == principal.owner.id)
    if principal.agent is not None and principal.agent.id != agent_id:
        raise not_found("agent", agent_id)  # 404, not 403 — don't leak other agents' existence
    agent = (await session.execute(q)).scalar_one_or_none()
    if agent is None:
        raise not_found("agent", agent_id)
    return agent


async def create_agent(session: AsyncSession, principal: Principal, body: AgentCreate) -> Agent:
    principal.require_owner()
    agent = Agent(
        id=ids.new_id(ids.AGENT),
        owner_id=principal.owner.id,
        display_name=body.display_name,
        description=body.description,
        status="active",
        policy_version=0,  # default deny-all until a Policy is attached
        metadata_=body.metadata or {},
    )
    session.add(agent)
    await session.flush()
    await ledger.get_or_create_balance(
        session, owner=principal.owner, holder_type="agent", holder_id=agent.id
    )
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="agent.created",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="agent",
        resource_id=agent.id,
        data={"display_name": agent.display_name},
    )
    return agent


async def list_agents(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    status: str | None = None,
) -> tuple[list[Agent], bool]:
    principal.require_owner()
    q = select(Agent).where(Agent.owner_id == principal.owner.id)
    if status:
        q = q.where(Agent.status == status)
    if starting_after:
        q = q.where(Agent.id < starting_after)
    q = q.order_by(Agent.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


async def update_agent(
    session: AsyncSession, principal: Principal, agent_id: str, body: AgentUpdate
) -> Agent:
    principal.require_owner()
    agent = await get_agent(session, principal, agent_id)
    if body.display_name is not None:
        agent.display_name = body.display_name
    if body.description is not None:
        agent.description = body.description
    if body.metadata is not None:
        agent.metadata_ = body.metadata
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="agent.updated",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="agent",
        resource_id=agent.id,
    )
    return agent


async def set_agent_status(
    session: AsyncSession, principal: Principal, agent_id: str, status: str
) -> Agent:
    principal.require_owner()
    agent = await get_agent(session, principal, agent_id)
    agent.status = status
    event = "agent.suspended" if status == "suspended" else "agent.reactivated"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type=event,
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="agent",
        resource_id=agent.id,
    )
    return agent
