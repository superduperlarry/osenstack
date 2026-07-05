from datetime import datetime

from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, LimitParam, Session, StartingAfterParam
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import ActivityEvent, ListEnvelope
from enos.services import activity as activity_service
from enos.services import serialize

router = APIRouter(tags=["Activity"], responses=DEFAULT_RESPONSES)


@router.get("/activity", operation_id="listActivity", response_model=ListEnvelope[ActivityEvent])
async def list_activity(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    agent_id: str | None = None,
    type: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
):
    rows, has_more = await activity_service.list_events(
        session,
        principal,
        limit=limit,
        starting_after=starting_after,
        agent_id=agent_id,
        type=type,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return ListEnvelope[ActivityEvent](
        data=[serialize.activity_event(e) for e in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )


@router.get("/activity/{event_id}", operation_id="getActivityEvent", response_model=ActivityEvent)
async def get_activity_event(event_id: str, session: Session, principal: CurrentPrincipal):
    event = await activity_service.get_event(session, principal, event_id)
    return serialize.activity_event(event)
