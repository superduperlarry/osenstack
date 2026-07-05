from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Card
from enos.providers import registry
from enos.schemas.products import CardCreate
from enos.services import activity
from enos.services import agents as agents_service
from enos.services.context import Principal
from enos.services.errors import ApiError, not_found


async def create_card(
    session: AsyncSession, principal: Principal, agent_id: str, body: CardCreate
) -> Card:
    principal.require_owner()  # no cards:create scope exists — issuance is owner-only
    agent = await agents_service.get_agent(session, principal, agent_id)
    issuer = registry.get_card_issuer()
    issued = issuer.issue(agent_id=agent.id, label=body.label, form=body.form.value)
    card = Card(
        id=ids.new_id(ids.CARD),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        provider_ref=issued.provider_ref,
        label=body.label,
        form=body.form.value,
        status="active",
        network=issued.network,
        last4=issued.last4,
        expiry_month=issued.expiry_month,
        expiry_year=issued.expiry_year,
    )
    session.add(card)
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="card.created",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="card",
        resource_id=card.id,
        data={"last4": card.last4},
    )
    return card


async def list_cards(
    session: AsyncSession, principal: Principal, agent_id: str
) -> tuple[list[Card], bool]:
    principal.require_scope("cards:read")
    await agents_service.get_agent(session, principal, agent_id)  # tenant + own-agent check
    q = (
        select(Card)
        .where(Card.owner_id == principal.owner.id, Card.agent_id == agent_id)
        .order_by(Card.id.desc())
    )
    return list((await session.execute(q)).scalars()), False


async def get_card(session: AsyncSession, principal: Principal, card_id: str) -> Card:
    principal.require_scope("cards:read")
    q = select(Card).where(Card.id == card_id, Card.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Card.agent_id == principal.agent.id)
    card = (await session.execute(q)).scalar_one_or_none()
    if card is None:
        raise not_found("card", card_id)
    return card


async def freeze_card(session: AsyncSession, principal: Principal, card_id: str) -> Card:
    """Owner, or the card's own agent — an agent may freeze, never unfreeze, its card."""
    principal.require_scope("cards:freeze")
    card = await get_card_for_freeze(session, principal, card_id)
    if card.status == "terminated":
        raise ApiError(409, "card_terminated", "Card is terminated.")
    registry.get_card_issuer().freeze(card.provider_ref)
    card.status = "frozen"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="card.frozen",
        agent_id=card.agent_id,
        credential_id=principal.credential.id,
        resource_type="card",
        resource_id=card.id,
    )
    return card


async def get_card_for_freeze(session: AsyncSession, principal: Principal, card_id: str) -> Card:
    q = select(Card).where(Card.id == card_id, Card.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Card.agent_id == principal.agent.id)
    card = (await session.execute(q)).scalar_one_or_none()
    if card is None:
        raise not_found("card", card_id)
    return card


async def unfreeze_card(session: AsyncSession, principal: Principal, card_id: str) -> Card:
    principal.require_owner()  # deliberately owner-only
    card = await get_card_for_freeze(session, principal, card_id)
    if card.status != "frozen":
        raise ApiError(409, "card_not_frozen", f"Card is {card.status}.")
    registry.get_card_issuer().unfreeze(card.provider_ref)
    card.status = "active"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="card.unfrozen",
        agent_id=card.agent_id,
        credential_id=principal.credential.id,
        resource_type="card",
        resource_id=card.id,
    )
    return card
