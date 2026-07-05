from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Quote
from enos.models.base import utcnow
from enos.providers import registry
from enos.schemas.money_movement import QuoteCreate
from enos.services import agents as agents_service
from enos.services.context import Principal
from enos.services.errors import ApiError, not_found, validation


async def create_quote(session: AsyncSession, principal: Principal, body: QuoteCreate) -> Quote:
    principal.require_scope("quotes:create")
    agent = await agents_service.get_agent(session, principal, body.agent_id)

    if (body.source_amount is None) == (body.destination_amount is None):
        raise validation("Provide source_amount OR destination_amount, not both.")

    source_currency = principal.owner.default_currency
    if body.source_amount is not None and body.source_amount.currency != source_currency:
        raise validation(
            f"source_amount must be in the owner default currency ({source_currency}); "
            "agent balances hold a single currency in Phase 0."
        )
    if (
        body.destination_amount is not None
        and body.destination_amount.currency != body.destination_currency
    ):
        raise validation("destination_amount currency must match destination_currency.")

    router = registry.get_routing_provider()
    try:
        route = router.quote(
            source_currency=source_currency,
            destination_currency=body.destination_currency,
            source_amount=Decimal(body.source_amount.amount) if body.source_amount else None,
            destination_amount=(
                Decimal(body.destination_amount.amount) if body.destination_amount else None
            ),
            destination_country=body.destination_country,
        )
    except LookupError as exc:
        raise ApiError(400, "unsupported_route", str(exc)) from None

    quote = Quote(
        id=ids.new_id(ids.QUOTE),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        source_amount=route.source_amount,
        source_currency=route.source_currency,
        destination_amount=route.destination_amount,
        destination_currency=route.destination_currency,
        rate=route.rate,
        fees=route.fees,
        estimated_arrival=route.estimated_arrival,
        expires_at=utcnow() + timedelta(minutes=route.ttl_minutes),
    )
    session.add(quote)
    await session.flush()
    return quote


async def get_quote(session: AsyncSession, principal: Principal, quote_id: str) -> Quote:
    principal.require_scope("quotes:create")
    q = select(Quote).where(Quote.id == quote_id, Quote.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Quote.agent_id == principal.agent.id)
    quote = (await session.execute(q)).scalar_one_or_none()
    if quote is None:
        raise not_found("quote", quote_id)
    return quote
