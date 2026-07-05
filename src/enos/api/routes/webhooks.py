from fastapi import APIRouter, Response

from enos.api.deps import CurrentPrincipal, IdempotencyKeyHeader, Session
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import (
    ListEnvelope,
    WebhookEndpoint,
    WebhookEndpointCreate,
    WebhookEndpointWithSecret,
)
from enos.services import serialize
from enos.services import webhooks as webhooks_service

router = APIRouter(tags=["Webhooks"], responses=DEFAULT_RESPONSES)


@router.post(
    "/webhook_endpoints",
    operation_id="createWebhookEndpoint",
    response_model=WebhookEndpointWithSecret,
    status_code=201,
)
async def create_webhook_endpoint(
    body: WebhookEndpointCreate,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    endpoint, secret = await webhooks_service.create_endpoint(session, principal, body)
    return serialize.webhook_endpoint(endpoint, secret=secret)


@router.get(
    "/webhook_endpoints",
    operation_id="listWebhookEndpoints",
    response_model=ListEnvelope[WebhookEndpoint],
)
async def list_webhook_endpoints(session: Session, principal: CurrentPrincipal):
    rows, has_more = await webhooks_service.list_endpoints(session, principal)
    return ListEnvelope[WebhookEndpoint](
        data=[serialize.webhook_endpoint(e) for e in rows], has_more=has_more, next_cursor=None
    )


@router.delete(
    "/webhook_endpoints/{webhook_endpoint_id}",
    operation_id="deleteWebhookEndpoint",
    status_code=204,
    response_class=Response,
)
async def delete_webhook_endpoint(
    webhook_endpoint_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    await webhooks_service.delete_endpoint(session, principal, webhook_endpoint_id)


@router.post(
    "/webhook_endpoints/{webhook_endpoint_id}/rotate_secret",
    operation_id="rotateWebhookSecret",
    response_model=WebhookEndpointWithSecret,
)
async def rotate_webhook_secret(
    webhook_endpoint_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    endpoint, secret = await webhooks_service.rotate_secret(session, principal, webhook_endpoint_id)
    return serialize.webhook_endpoint(endpoint, secret=secret)
