"""Approval decisions — the owner side of human-in-the-loop."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos.models import Approval, Counterparty, Payment, Transfer
from enos.models.base import utcnow
from enos.services import activity, ledger
from enos.services import payments as payments_service
from enos.services import transfers as transfers_service
from enos.services.context import Principal
from enos.services.errors import ApiError, not_found


async def get_approval(session: AsyncSession, principal: Principal, approval_id: str) -> Approval:
    principal.require_scope("approvals:read")
    q = select(Approval).where(Approval.id == approval_id, Approval.owner_id == principal.owner.id)
    if principal.agent is not None:  # agents see only approvals raised by their own actions
        q = q.where(Approval.agent_id == principal.agent.id)
    approval = (await session.execute(q)).scalar_one_or_none()
    if approval is None:
        raise not_found("approval", approval_id)
    return approval


async def list_approvals(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    status: str | None = None,
    agent_id: str | None = None,
) -> tuple[list[Approval], bool]:
    principal.require_scope("approvals:read")
    q = select(Approval).where(Approval.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Approval.agent_id == principal.agent.id)
    elif agent_id:
        q = q.where(Approval.agent_id == agent_id)
    if status:
        q = q.where(Approval.status == status)
    if starting_after:
        q = q.where(Approval.id < starting_after)
    q = q.order_by(Approval.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit


def _require_pending(approval: Approval) -> None:
    if approval.status != "pending":
        raise ApiError(409, "approval_not_pending", f"Approval is already {approval.status}.")
    if approval.expires_at < utcnow():
        raise ApiError(409, "approval_expired", "Approval has expired.")


async def _release_held_funds(session: AsyncSession, principal: Principal, approval: Approval):
    if approval.action_type == "payment":
        payment = (
            await session.execute(select(Payment).where(Payment.id == approval.action_id))
        ).scalar_one()
        balance = await ledger.get_or_create_balance(
            session, owner=principal.owner, holder_type="agent", holder_id=payment.agent_id
        )
        await ledger.release_reservation(session, balance, payment.source_amount)
        return payment
    if approval.action_type == "transfer":
        transfer = (
            await session.execute(select(Transfer).where(Transfer.id == approval.action_id))
        ).scalar_one()
        balance = await ledger.get_or_create_balance(
            session,
            owner=principal.owner,
            holder_type=transfer.source_holder_type,
            holder_id=transfer.source_holder_id,
        )
        await ledger.release_reservation(session, balance, transfer.amount)
        return transfer
    return None


async def approve(
    session: AsyncSession, principal: Principal, approval_id: str, note: str | None
) -> Approval:
    principal.require_owner()
    approval = await get_approval(session, principal, approval_id)
    _require_pending(approval)

    if approval.action_type == "payment":
        payment = (
            await session.execute(select(Payment).where(Payment.id == approval.action_id))
        ).scalar_one()
        before = payment.destination_amount
        await payments_service.execute_approved(session, principal, payment)
        if payment.destination_amount != before:  # repriced after quote expiry
            approval.summary = {
                **(approval.summary or {}),
                "repriced": {
                    "original_destination_amount": str(before),
                    "executed_destination_amount": str(payment.destination_amount),
                },
            }
    elif approval.action_type == "transfer":
        transfer = (
            await session.execute(select(Transfer).where(Transfer.id == approval.action_id))
        ).scalar_one()
        await transfers_service.execute_transfer(session, principal, transfer, from_reservation=True)
    elif approval.action_type == "counterparty":
        counterparty = (
            await session.execute(
                select(Counterparty).where(Counterparty.id == approval.action_id)
            )
        ).scalar_one()
        counterparty.status = "verified"  # owner-confirmed

    approval.status = "approved"
    approval.decided_by = principal.owner.id
    approval.decided_at = utcnow()
    approval.note = note
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="approval.decided",
        agent_id=approval.agent_id,
        credential_id=principal.credential.id,
        resource_type="approval",
        resource_id=approval.id,
        data={"decision": "approved", "action_type": approval.action_type},
    )
    return approval


async def reject(
    session: AsyncSession, principal: Principal, approval_id: str, note: str | None
) -> Approval:
    principal.require_owner()
    approval = await get_approval(session, principal, approval_id)
    _require_pending(approval)

    action = await _release_held_funds(session, principal, approval)
    if approval.action_type == "payment":
        action.status = "cancelled"
        action.failure_reason = "owner_rejected"
        payments_service._timeline_add(action, "cancelled", "owner rejected")
        await activity.record_event(
            session,
            owner_id=principal.owner.id,
            type="payment.cancelled",
            agent_id=action.agent_id,
            resource_type="payment",
            resource_id=action.id,
            data={"reason": "owner_rejected"},
        )
    elif approval.action_type == "transfer":
        action.status = "cancelled"
    elif approval.action_type == "counterparty":
        counterparty = (
            await session.execute(
                select(Counterparty).where(Counterparty.id == approval.action_id)
            )
        ).scalar_one()
        counterparty.status = "blocked"

    approval.status = "rejected"
    approval.decided_by = principal.owner.id
    approval.decided_at = utcnow()
    approval.note = note
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="approval.decided",
        agent_id=approval.agent_id,
        credential_id=principal.credential.id,
        resource_type="approval",
        resource_id=approval.id,
        data={"decision": "rejected", "action_type": approval.action_type},
    )
    return approval


async def expire_stale(session: AsyncSession) -> int:
    """Worker task: expire pending approvals past their expiry; release holds."""
    from enos.models import Owner
    from enos.services.context import Principal as P

    q = select(Approval).where(Approval.status == "pending", Approval.expires_at < utcnow())
    stale = list((await session.execute(q)).scalars())
    for approval in stale:
        owner = (
            await session.execute(select(Owner).where(Owner.id == approval.owner_id))
        ).scalar_one()
        pseudo = P(owner=owner, credential=None)  # type: ignore[arg-type]
        action = await _release_held_funds(session, pseudo, approval)
        if approval.action_type == "payment" and action is not None:
            action.status = "cancelled"
            action.failure_reason = "approval_expired"
        elif approval.action_type == "transfer" and action is not None:
            action.status = "cancelled"
        approval.status = "expired"
        approval.decided_at = utcnow()
        await activity.record_event(
            session,
            owner_id=approval.owner_id,
            type="approval.decided",
            agent_id=approval.agent_id,
            resource_type="approval",
            resource_id=approval.id,
            data={"decision": "expired", "action_type": approval.action_type},
        )
    return len(stale)
