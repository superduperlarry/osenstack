"""Payment lifecycle. Policy evaluation happens here.

Outcomes (spec): within policy → 201 processing; held → 202 pending_approval
with an Approval created; hard-denied → 403 policy_denied. Owner-initiated
payments skip policy (the owner is the approver) but not funds checks.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Counterparty, Payment, Quote
from enos.models.base import utcnow
from enos.providers import registry
from enos.schemas.money_movement import PaymentCreate
from enos.services import activity, ledger, policy_gate
from enos.services import agents as agents_service
from enos.services import counterparties as counterparties_service
from enos.services.context import Principal
from enos.services.errors import ApiError, not_found, validation
from enos.services.policy_gate import Deny, Hold


def _timeline_add(payment: Payment, status: str, detail: str | None = None) -> None:
    payment.timeline = [
        *(payment.timeline or []),
        {"status": status, "at": utcnow().isoformat(), "detail": detail},
    ]


def _is_cross_border(owner_country: str, owner_currency: str, cpty: Counterparty) -> bool:
    dest = cpty.destination or {}
    if dest.get("country"):
        return dest["country"] != owner_country
    if dest.get("currency"):
        return dest["currency"] != owner_currency
    return False


async def _resolve_amounts(
    session: AsyncSession, principal: Principal, body: PaymentCreate, cpty: Counterparty
) -> tuple[Decimal, str, Decimal | None, str | None, Quote | None]:
    """Rule on record: no amount-plus-quote ambiguity. Cross-currency requires a
    quote; same-currency takes an amount. Validated here."""
    owner_ccy = principal.owner.default_currency
    dest_ccy = (cpty.destination or {}).get("currency") or owner_ccy

    if body.quote_id is not None and body.amount is not None:
        raise validation("Provide quote_id OR amount, not both.")

    if body.quote_id is not None:
        q = select(Quote).where(
            Quote.id == body.quote_id,
            Quote.owner_id == principal.owner.id,
            Quote.agent_id == body.agent_id,
        )
        quote = (await session.execute(q)).scalar_one_or_none()
        if quote is None:
            raise not_found("quote", body.quote_id)
        if quote.expires_at < utcnow():
            raise ApiError(409, "quote_expired", "The quote has expired; create a new one.")
        return quote.source_amount, quote.source_currency, quote.destination_amount, quote.destination_currency, quote

    if body.amount is None:
        raise validation("amount is required when no quote_id is given.")
    if body.amount.currency != owner_ccy:
        raise validation(f"amount must be in the owner default currency ({owner_ccy}).")
    if dest_ccy != owner_ccy:
        raise validation(
            "Cross-currency payments require a quote_id. "
            f"Counterparty settles in {dest_ccy}; the balance holds {owner_ccy}."
        )
    amount = Decimal(body.amount.amount)
    return amount, owner_ccy, amount, owner_ccy, None


async def create_payment(
    session: AsyncSession, principal: Principal, body: PaymentCreate
) -> Payment:
    principal.require_scope("payments:create")
    agent = await agents_service.get_agent(session, principal, body.agent_id)
    cpty = await counterparties_service.get_counterparty(session, principal, body.counterparty_id)

    src_amount, src_ccy, dst_amount, dst_ccy, quote = await _resolve_amounts(
        session, principal, body, cpty
    )
    if src_amount <= 0:
        raise validation("Payment amount must be positive.")

    balance = await ledger.get_or_create_balance(
        session, owner=principal.owner, holder_type="agent", holder_id=agent.id
    )
    ledger.ensure_available(balance, src_amount)  # 409 insufficient_funds before policy

    cross_border = _is_cross_border(principal.owner.country, src_ccy, cpty)

    payment = Payment(
        id=ids.new_id(ids.PAYMENT),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        credential_id=principal.credential.id,
        counterparty_id=cpty.id,
        quote_id=quote.id if quote else None,
        source_amount=src_amount,
        source_currency=src_ccy,
        destination_amount=dst_amount,
        destination_currency=dst_ccy,
        status="processing",
        reference=body.reference,
        purpose=body.purpose,
        timeline=[],
    )

    if principal.agent is not None:
        decision = await policy_gate.evaluate_action(
            session,
            principal,
            agent,
            action_type="payment",
            amount=src_amount,
            currency=dst_ccy,
            counterparty=cpty,
            is_cross_border=cross_border,
        )
        if isinstance(decision, Deny):
            raise policy_gate.deny_error(decision)
        if isinstance(decision, Hold):
            payment.status = "pending_approval"
            session.add(payment)
            await session.flush()
            _timeline_add(payment, "pending_approval", f"held by policy rule {decision.trigger}")
            await ledger.reserve(session, balance, src_amount)
            approval = await policy_gate.raise_approval(
                session,
                principal,
                agent,
                decision,
                action_type="payment",
                action_id=payment.id,
                summary={
                    "counterparty": cpty.display_name,
                    "source_amount": {"amount": str(src_amount), "currency": src_ccy},
                    "destination_amount": (
                        {"amount": str(dst_amount), "currency": dst_ccy} if dst_amount else None
                    ),
                    "purpose": body.purpose,
                },
            )
            payment.approval_id = approval.id
            return payment

    session.add(payment)
    await session.flush()
    await _execute(session, principal, payment, from_reservation=False)
    return payment


async def _execute(
    session: AsyncSession, principal: Principal, payment: Payment, *, from_reservation: bool
) -> None:
    """Post the ledger journal and dispatch over the routing provider."""
    _timeline_add(payment, "processing")
    await ledger.pay_out(
        session,
        owner=principal.owner,
        holder_type="agent",
        holder_id=payment.agent_id,
        amount=payment.source_amount,
        resource_type="payment",
        resource_id=payment.id,
        from_reservation=from_reservation,
    )
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="payment.processing",
        agent_id=payment.agent_id,
        credential_id=payment.credential_id,
        resource_type="payment",
        resource_id=payment.id,
        data={"amount": str(payment.source_amount), "currency": payment.source_currency},
    )
    router = registry.get_routing_provider()
    result = router.dispatch(
        payment_id=payment.id,
        destination_currency=payment.destination_currency or payment.source_currency,
        is_cross_border=payment.destination_currency != payment.source_currency,
    )
    payment.rail = result.rail
    if result.status == "completed":
        payment.status = "completed"
        payment.completed_at = utcnow()
        _timeline_add(payment, "completed", result.detail)
        await activity.record_event(
            session,
            owner_id=principal.owner.id,
            type="payment.completed",
            agent_id=payment.agent_id,
            credential_id=payment.credential_id,
            resource_type="payment",
            resource_id=payment.id,
            data={"rail": result.rail},
        )


async def execute_approved(session: AsyncSession, principal: Principal, payment: Payment) -> None:
    """Release an approved hold. Reprices if the quote expired (both amounts
    end up recorded on the approval by the caller)."""
    if payment.quote_id is not None:
        quote = (
            await session.execute(select(Quote).where(Quote.id == payment.quote_id))
        ).scalar_one()
        if quote.expires_at < utcnow():
            router = registry.get_routing_provider()
            route = router.quote(
                source_currency=payment.source_currency,
                destination_currency=payment.destination_currency,
                source_amount=payment.source_amount,
                destination_amount=None,
                destination_country=None,
            )
            payment.destination_amount = route.destination_amount
            _timeline_add(payment, "repriced", f"quote expired; repriced at {route.rate}")
    await _execute(session, principal, payment, from_reservation=True)


async def get_payment(session: AsyncSession, principal: Principal, payment_id: str) -> Payment:
    principal.require_scope("payments:read")
    q = select(Payment).where(Payment.id == payment_id, Payment.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Payment.agent_id == principal.agent.id)
    payment = (await session.execute(q)).scalar_one_or_none()
    if payment is None:
        raise not_found("payment", payment_id)
    return payment


async def list_payments(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    agent_id: str | None = None,
    status: str | None = None,
    created_after=None,
    created_before=None,
) -> tuple[list[Payment], bool]:
    principal.require_scope("payments:read")
    q = select(Payment).where(Payment.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Payment.agent_id == principal.agent.id)
    elif agent_id:
        q = q.where(Payment.agent_id == agent_id)
    if status:
        q = q.where(Payment.status == status)
    if created_after:
        q = q.where(Payment.created_at > created_after)
    if created_before:
        q = q.where(Payment.created_at < created_before)
    if starting_after:
        q = q.where(Payment.id < starting_after)
    q = q.order_by(Payment.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


async def cancel_payment(session: AsyncSession, principal: Principal, payment_id: str) -> Payment:
    principal.require_scope("payments:create")
    payment = await get_payment(session, principal, payment_id)
    if payment.status != "pending_approval":
        # Sandbox dispatch settles instantly, so `processing` is already dispatched.
        raise ApiError(
            409, "cancellation_not_allowed", f"Payment is {payment.status}; only pre-dispatch payments can be cancelled."
        )
    balance = await ledger.get_or_create_balance(
        session, owner=principal.owner, holder_type="agent", holder_id=payment.agent_id
    )
    await ledger.release_reservation(session, balance, payment.source_amount)
    payment.status = "cancelled"
    payment.failure_reason = "cancelled_by_caller"
    _timeline_add(payment, "cancelled", "cancelled before dispatch")

    if payment.approval_id:
        from enos.models import Approval

        approval = (
            await session.execute(select(Approval).where(Approval.id == payment.approval_id))
        ).scalar_one_or_none()
        if approval is not None and approval.status == "pending":
            approval.status = "expired"
            approval.note = "underlying payment cancelled by caller"
            approval.decided_at = utcnow()

    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="payment.cancelled",
        agent_id=payment.agent_id,
        credential_id=principal.credential.id,
        resource_type="payment",
        resource_id=payment.id,
    )
    return payment
