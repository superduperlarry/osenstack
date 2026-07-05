from fastapi import APIRouter

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import Quote, QuoteCreate
from enos.services import quotes as quotes_service
from enos.services import serialize

router = APIRouter(tags=["Quotes"], responses=DEFAULT_RESPONSES)


@router.post("/quotes", operation_id="createQuote", response_model=Quote, status_code=201)
async def create_quote(
    body: QuoteCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    quote = await quotes_service.create_quote(session, principal, body)
    return serialize.quote(quote)


@router.get("/quotes/{quote_id}", operation_id="getQuote", response_model=Quote)
async def get_quote(quote_id: str, session: Session, principal: CurrentPrincipal):
    quote = await quotes_service.get_quote(session, principal, quote_id)
    return serialize.quote(quote)
