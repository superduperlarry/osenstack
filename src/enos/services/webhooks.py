"""Webhook endpoint management. Delivery machinery is a later-phase deliverable —
Phase 0 emits ActivityEvents only."""

import hashlib
import secrets

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import WebhookEndpoint
from enos.models.base import utcnow
from enos.schemas.control import WebhookEndpointCreate
from enos.services import activity
from enos.services.context import Principal
from enos.services.errors import not_found


def _new_secret() -> tuple[str, str]:
    secret = f"whsec_{secrets.token_urlsafe(24)}"
    return secret, hashlib.sha256(secret.encode()).hexdigest()


async def create_endpoint(
    session: AsyncSession, principal: Principal, body: WebhookEndpointCreate
) -> tuple[WebhookEndpoint, str]:
    principal.require_owner()
    secret, secret_hash = _new_secret()
    endpoint = WebhookEndpoint(
        id=ids.new_id(ids.WEBHOOK_ENDPOINT),
        owner_id=principal.owner.id,
        url=body.url,
        event_types=body.event_types,
        label=body.label,
        status="active",
        secret_hash=secret_hash,
    )
    session.add(endpoint)
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="webhook_endpoint.created",
        credential_id=principal.credential.id,
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
    )
    return endpoint, secret


async def list_endpoints(
    session: AsyncSession, principal: Principal
) -> tuple[list[WebhookEndpoint], bool]:
    principal.require_owner()
    q = (
        select(WebhookEndpoint)
        .where(WebhookEndpoint.owner_id == principal.owner.id)
        .order_by(WebhookEndpoint.id.desc())
    )
    return list((await session.execute(q)).scalars()), False


async def get_endpoint(
    session: AsyncSession, principal: Principal, endpoint_id: str
) -> WebhookEndpoint:
    principal.require_owner()
    q = select(WebhookEndpoint).where(
        WebhookEndpoint.id == endpoint_id, WebhookEndpoint.owner_id == principal.owner.id
    )
    endpoint = (await session.execute(q)).scalar_one_or_none()
    if endpoint is None:
        raise not_found("webhook endpoint", endpoint_id)
    return endpoint


async def delete_endpoint(session: AsyncSession, principal: Principal, endpoint_id: str) -> None:
    endpoint = await get_endpoint(session, principal, endpoint_id)
    await session.execute(delete(WebhookEndpoint).where(WebhookEndpoint.id == endpoint.id))
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="webhook_endpoint.deleted",
        credential_id=principal.credential.id,
        resource_type="webhook_endpoint",
        resource_id=endpoint_id,
    )


async def rotate_secret(
    session: AsyncSession, principal: Principal, endpoint_id: str
) -> tuple[WebhookEndpoint, str]:
    endpoint = await get_endpoint(session, principal, endpoint_id)
    secret, secret_hash = _new_secret()
    endpoint.previous_secret_hash = endpoint.secret_hash  # old secret valid 24h
    endpoint.secret_hash = secret_hash
    endpoint.rotated_at = utcnow()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="webhook_endpoint.secret_rotated",
        credential_id=principal.credential.id,
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
    )
    return endpoint, secret
