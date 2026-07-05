from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Agent, Policy
from enos.schemas.identity import Policy as PolicySchema
from enos.schemas.identity import PolicyApprovals, PolicyCreate, PolicyLimits
from enos.services import activity, serialize
from enos.services.context import Principal


async def get_active_policy(
    session: AsyncSession, principal: Principal, agent: Agent
) -> PolicySchema:
    principal.require_scope("policy:read")
    if agent.policy_version > 0:
        row = (
            await session.execute(
                select(Policy).where(
                    Policy.agent_id == agent.id, Policy.version == agent.policy_version
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return serialize.policy(row)
    # Version 0: the implicit default policy. Deny-all in the engine regardless
    # of what the display document suggests.
    return PolicySchema(
        agent_id=agent.id,
        version=0,
        limits=PolicyLimits(),
        counterparty_allowlist=[],
        approvals=PolicyApprovals(),
        created_at=agent.created_at,
    )


async def replace_policy(
    session: AsyncSession, principal: Principal, agent: Agent, body: PolicyCreate
) -> PolicySchema:
    principal.require_owner()
    new_version = agent.policy_version + 1
    row = Policy(
        id=ids.new_id(ids.POLICY),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        version=new_version,
        document=body.model_dump(mode="json"),
    )
    session.add(row)
    agent.policy_version = new_version
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="policy.updated",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="policy",
        resource_id=row.id,
        data={"version": new_version},
    )
    return serialize.policy(row)
