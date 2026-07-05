from datetime import datetime

from fastapi import APIRouter, Response

from enos.api.deps import (
    CurrentPrincipal,
    IdempotencyKeyHeader,
    LimitParam,
    Session,
    StartingAfterParam,
)
from enos.api.routes import DEFAULT_RESPONSES
from enos.schemas import ListEnvelope, Payment, PaymentCreate, PaymentStatus
from enos.services import payments as payments_service
from enos.services import serialize

router = APIRouter(tags=["Payments"], responses=DEFAULT_RESPONSES)


@router.post(
    "/payments",
    operation_id="createPayment",
    response_model=Payment,
    status_code=201,
    responses={202: {"model": Payment, "description": "Payment created but held pending owner approval."}},
)
async def create_payment(
    body: PaymentCreate,
    response: Response,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    payment = await payments_service.create_payment(session, principal, body)
    if payment.status == "pending_approval":
        response.status_code = 202
    return serialize.payment(payment)


@router.get("/payments", operation_id="listPayments", response_model=ListEnvelope[Payment])
async def list_payments(
    session: Session,
    principal: CurrentPrincipal,
    limit: LimitParam = 20,
    starting_after: StartingAfterParam = None,
    agent_id: str | None = None,
    status: PaymentStatus | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
):
    rows, has_more = await payments_service.list_payments(
        session,
        principal,
        limit=limit,
        starting_after=starting_after,
        agent_id=agent_id,
        status=status.value if status else None,
        created_after=created_after,
        created_before=created_before,
    )
    return ListEnvelope[Payment](
        data=[serialize.payment(p) for p in rows],
        has_more=has_more,
        next_cursor=rows[-1].id if has_more and rows else None,
    )


@router.get("/payments/{payment_id}", operation_id="getPayment", response_model=Payment)
async def get_payment(payment_id: str, session: Session, principal: CurrentPrincipal):
    payment = await payments_service.get_payment(session, principal, payment_id)
    return serialize.payment(payment)


@router.post("/payments/{payment_id}/cancel", operation_id="cancelPayment", response_model=Payment)
async def cancel_payment(
    payment_id: str,
    session: Session,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKeyHeader,
):
    payment = await payments_service.cancel_payment(session, principal, payment_id)
    return serialize.payment(payment)
