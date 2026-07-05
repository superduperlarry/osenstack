from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import ActivityEvent
from enos.services.context import Principal
from enos.services.errors import not_found


async def record_event(
    session: AsyncSession,
    *,
    owner_id: str,
    type: str,
    agent_id: str | None = None,
    credential_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        id=ids.new_id(ids.ACTIVITY_EVENT),
        owner_id=owner_id,
        type=type,
        agent_id=agent_id,
        credential_id=credential_id,
        resource_type=resource_type,
        resource_id=resource_id,
        data=data or {},
    )
    session.add(event)
    return event


async def list_events(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    agent_id: str | None = None,
    type: str | None = None,
    occurred_after=None,
    occurred_before=None,
) -> tuple[list[ActivityEvent], bool]:
    q = select(ActivityEvent).where(ActivityEvent.owner_id == principal.owner.id)
    if principal.agent is not None:  # agents see only their own events
        q = q.where(ActivityEvent.agent_id == principal.agent.id)
    elif agent_id:
        q = q.where(ActivityEvent.agent_id == agent_id)
    if type:
        if type.endswith(".*") or type.endswith("*"):
            q = q.where(ActivityEvent.type.like(type.rstrip("*") + "%"))
        else:
            q = q.where(ActivityEvent.type == type)
    if occurred_after:
        q = q.where(ActivityEvent.occurred_at > occurred_after)
    if occurred_before:
        q = q.where(ActivityEvent.occurred_at < occurred_before)
    if starting_after:
        q = q.where(ActivityEvent.id < starting_after)
    q = q.order_by(ActivityEvent.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


async def get_event(session: AsyncSession, principal: Principal, event_id: str) -> ActivityEvent:
    q = select(ActivityEvent).where(
        ActivityEvent.id == event_id, ActivityEvent.owner_id == principal.owner.id
    )
    if principal.agent is not None:
        q = q.where(ActivityEvent.agent_id == principal.agent.id)
    event = (await session.execute(q)).scalar_one_or_none()
    if event is None:
        raise not_found("activity event", event_id)
    return event
