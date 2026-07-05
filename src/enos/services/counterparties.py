from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Counterparty
from enos.schemas.money_movement import CounterpartyCreate
from enos.services import activity, policy_gate
from enos.services import agents as agents_service
from enos.services.context import Principal
from enos.services.errors import not_found
from enos.services.policy_gate import Deny, Hold


async def create_counterparty(
    session: AsyncSession, principal: Principal, body: CounterpartyCreate
) -> Counterparty:
    principal.require_scope("counterparties:create")
    actor_type = "owner" if principal.is_owner else "agent"
    actor_id = principal.owner.id if principal.is_owner else principal.agent.id

    counterparty = Counterparty(
        id=ids.new_id(ids.COUNTERPARTY),
        owner_id=principal.owner.id,
        display_name=body.display_name,
        destination=body.destination.model_dump(mode="json", exclude_none=True),
        status="unverified",
        created_by_actor_type=actor_type,
        created_by_actor_id=actor_id,
        metadata_=body.metadata or {},
    )
    session.add(counterparty)
    await session.flush()

    # Agent-created counterparties are policy-evaluated: creation may itself
    # raise an Approval (spec keeps the response 201 either way — the approval
    # gates *payments* to it, not its existence).
    if principal.agent is not None:
        agent = await agents_service.get_agent(session, principal, principal.agent.id)
        decision = await policy_gate.evaluate_action(
            session,
            principal,
            agent,
            action_type="counterparty",
            counterparty=counterparty,
        )
        if isinstance(decision, Deny):
            raise policy_gate.deny_error(decision)
        if isinstance(decision, Hold):
            await policy_gate.raise_approval(
                session,
                principal,
                agent,
                decision,
                action_type="counterparty",
                action_id=counterparty.id,
                summary={
                    "display_name": counterparty.display_name,
                    "destination_type": body.destination.type.value,
                },
            )

    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="counterparty.created",
        agent_id=principal.agent.id if principal.agent else None,
        credential_id=principal.credential.id,
        resource_type="counterparty",
        resource_id=counterparty.id,
        data={"display_name": counterparty.display_name},
    )
    return counterparty


async def get_counterparty(
    session: AsyncSession, principal: Principal, counterparty_id: str
) -> Counterparty:
    principal.require_scope("counterparties:read")
    q = select(Counterparty).where(
        Counterparty.id == counterparty_id, Counterparty.owner_id == principal.owner.id
    )
    counterparty = (await session.execute(q)).scalar_one_or_none()
    if counterparty is None:
        raise not_found("counterparty", counterparty_id)
    return counterparty


async def list_counterparties(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    status: str | None = None,
) -> tuple[list[Counterparty], bool]:
    principal.require_scope("counterparties:read")
    q = select(Counterparty).where(Counterparty.owner_id == principal.owner.id)
    if status:
        q = q.where(Counterparty.status == status)
    if starting_after:
        q = q.where(Counterparty.id < starting_after)
    q = q.order_by(Counterparty.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


async def verify_counterparty(
    session: AsyncSession, principal: Principal, counterparty_id: str
) -> Counterparty:
    principal.require_owner()
    counterparty = await get_counterparty(session, principal, counterparty_id)
    counterparty.status = "verified"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="counterparty.verified",
        credential_id=principal.credential.id,
        resource_type="counterparty",
        resource_id=counterparty.id,
    )
    return counterparty
