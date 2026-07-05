from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Card, CardCreate, ListEnvelope
from enos.services import cards as cards_service
from enos.services import serialize

router = APIRouter(tags=["Cards"], responses=DEFAULT_RESPONSES)


@router.post(
    "/agents/{agent_id}/cards", operation_id="createCard", response_model=Card, status_code=201
)
async def create_card(
    agent_id: str,
    body: CardCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    card = await cards_service.create_card(session, principal, agent_id, body)
    return serialize.card(card)


@router.get("/agents/{agent_id}/cards", operation_id="listCards", response_model=ListEnvelope[Card])
async def list_cards(agent_id: str, session: Session, principal: CurrentPrincipal):
    rows, has_more = await cards_service.list_cards(session, principal, agent_id)
    return ListEnvelope[Card](
        data=[serialize.card(c) for c in rows], has_more=has_more, next_cursor=None
    )


@router.get("/cards/{card_id}", operation_id="getCard", response_model=Card)
async def get_card(card_id: str, session: Session, principal: CurrentPrincipal):
    card = await cards_service.get_card(session, principal, card_id)
    return serialize.card(card)


@router.post("/cards/{card_id}/freeze", operation_id="freezeCard", response_model=Card)
async def freeze_card(
    card_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    card = await cards_service.freeze_card(session, principal, card_id)
    return serialize.card(card)


@router.post("/cards/{card_id}/unfreeze", operation_id="unfreezeCard", response_model=Card)
async def unfreeze_card(
    card_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    card = await cards_service.unfreeze_card(session, principal, card_id)
    return serialize.card(card)
