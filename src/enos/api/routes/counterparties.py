from fastapi import APIRouter

from enos.api.deps import (
    CurrentPrincipal,
    IdempotencyKeyHeader,
    LimitParam,
    Session,
    StartingAfterParam,
)
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Counterparty, CounterpartyCreate, CounterpartyStatus, ListEnvelope
from enos.services import counterparties as counterparties_service
from enos.services import serialize

router = APIRouter(tags=["Counterparties"], responses=DEFAULT_RESPONSES)


@router.post(
    "/counterparties",
    operation_id="createCounterparty",
    response_model=Counterparty,
    status_code=201,
)
async def create_counterparty(
    body: CounterpartyCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    counterparty = await counterparties_service.create_counterparty(session, principal, body)
    return serialize.counterparty(counterparty)


@router.get(
    "/counterparties",
    operation_id="listCounterparties",
    response_model=ListEnvelope[Counterparty],
)
async def list_counterparties(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    status: CounterpartyStatus | None = None,
):
    rows, has_more = await counterparties_service.list_counterparties(
        session,
        principal,
        limit=limit,
        starting_after=starting_after,
        status=status.value if status else None,
    )
    return ListEnvelope[Counterparty](
        data=[serialize.counterparty(c) for c in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )


@router.get(
    "/counterparties/{counterparty_id}",
    operation_id="getCounterparty",
    response_model=Counterparty,
)
async def get_counterparty(counterparty_id: str, session: Session, principal: CurrentPrincipal):
    counterparty = await counterparties_service.get_counterparty(session, principal, counterparty_id)
    return serialize.counterparty(counterparty)


@router.post(
    "/counterparties/{counterparty_id}/verify",
    operation_id="verifyCounterparty",
    response_model=Counterparty,
)
async def verify_counterparty(
    counterparty_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    counterparty = await counterparties_service.verify_counterparty(
        session, principal, counterparty_id
    )
    return serialize.counterparty(counterparty)
