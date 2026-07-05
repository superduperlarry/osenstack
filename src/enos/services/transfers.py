"""Internal balance moves. Policy-evaluated when initiated by an agent credential."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Transfer
from enos.schemas.money_movement import TransferCreate
from enos.services import activity, ledger, policy_gate
from enos.services import agents as agents_service
from enos.services.context import Principal
from enos.services.errors import not_found, validation
from enos.services.policy_gate import Deny, Hold


async def _validate_holder(session: AsyncSession, principal: Principal, ref) -> None:
    if ref.holder_type.value == "owner":
        if ref.holder_id != principal.owner.id:
            raise validation("Holder is not part of this account.")
    else:
        await agents_service.get_agent(session, principal, ref.holder_id)  # tenant check


async def create_transfer(
    session: AsyncSession, principal: Principal, body: TransferCreate
) -> Transfer:
    principal.require_scope("transfers:create")
    amount = Decimal(body.amount.amount)
    if amount <= 0:
        raise validation("Transfer amount must be positive.")
    if body.amount.currency != principal.owner.default_currency:
        raise validation(
            f"Transfers are in the owner default currency ({principal.owner.default_currency})."
        )
    if (body.source.holder_type, body.source.holder_id) == (
        body.destination.holder_type,
        body.destination.holder_id,
    ):
        raise validation("Source and destination must differ.")

    # An agent credential may only move funds out of its own balance.
    if principal.agent is not None and (
        body.source.holder_type.value != "agent" or body.source.holder_id != principal.agent.id
    ):
        raise validation("Agent credentials may only transfer from their own balance.")

    await _validate_holder(session, principal, body.source)
    await _validate_holder(session, principal, body.destination)

    src_balance = await ledger.get_or_create_balance(
        session,
        owner=principal.owner,
        holder_type=body.source.holder_type.value,
        holder_id=body.source.holder_id,
    )
    ledger.ensure_available(src_balance, amount)

    transfer = Transfer(
        id=ids.new_id(ids.TRANSFER),
        owner_id=principal.owner.id,
        agent_id=principal.agent.id if principal.agent else None,
        credential_id=principal.credential.id,
        source_holder_type=body.source.holder_type.value,
        source_holder_id=body.source.holder_id,
        destination_holder_type=body.destination.holder_type.value,
        destination_holder_id=body.destination.holder_id,
        amount=amount,
        currency=body.amount.currency,
        status="completed",
        note=body.note,
    )

    if principal.agent is not None:
        agent = await agents_service.get_agent(session, principal, principal.agent.id)
        decision = await policy_gate.evaluate_action(
            session,
            principal,
            agent,
            action_type="transfer",
            amount=amount,
            currency=body.amount.currency,
        )
        if isinstance(decision, Deny):
            raise policy_gate.deny_error(decision)
        if isinstance(decision, Hold):
            transfer.status = "pending_approval"
            session.add(transfer)
            await session.flush()
            await ledger.reserve(session, src_balance, amount)
            approval = await policy_gate.raise_approval(
                session,
                principal,
                agent,
                decision,
                action_type="transfer",
                action_id=transfer.id,
                summary={
                    "amount": {"amount": str(amount), "currency": body.amount.currency},
                    "destination": {
                        "holder_type": body.destination.holder_type.value,
                        "holder_id": body.destination.holder_id,
                    },
                    "note": body.note,
                },
            )
            transfer.approval_id = approval.id
            return transfer

    session.add(transfer)
    await session.flush()
    await execute_transfer(session, principal, transfer, from_reservation=False)
    return transfer


async def execute_transfer(
    session: AsyncSession, principal: Principal, transfer: Transfer, *, from_reservation: bool
) -> None:
    await ledger.internal_transfer(
        session,
        owner=principal.owner,
        source_type=transfer.source_holder_type,
        source_id=transfer.source_holder_id,
        destination_type=transfer.destination_holder_type,
        destination_id=transfer.destination_holder_id,
        amount=transfer.amount,
        resource_id=transfer.id,
        from_reservation=from_reservation,
    )
    transfer.status = "completed"
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="transfer.completed",
        agent_id=transfer.agent_id,
        credential_id=transfer.credential_id,
        resource_type="transfer",
        resource_id=transfer.id,
        data={"amount": str(transfer.amount), "currency": transfer.currency},
    )


async def get_transfer(session: AsyncSession, principal: Principal, transfer_id: str) -> Transfer:
    principal.require_scope("transfers:read")
    q = select(Transfer).where(Transfer.id == transfer_id, Transfer.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Transfer.agent_id == principal.agent.id)
    transfer = (await session.execute(q)).scalar_one_or_none()
    if transfer is None:
        raise not_found("transfer", transfer_id)
    return transfer


async def list_transfers(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int = 20,
    starting_after: str | None = None,
    agent_id: str | None = None,
) -> tuple[list[Transfer], bool]:
    principal.require_scope("transfers:read")
    q = select(Transfer).where(Transfer.owner_id == principal.owner.id)
    if principal.agent is not None:
        q = q.where(Transfer.agent_id == principal.agent.id)
    elif agent_id:
        q = q.where(Transfer.agent_id == agent_id)
    if starting_after:
        q = q.where(Transfer.id < starting_after)
    q = q.order_by(Transfer.id.desc()).limit(limit + 1)
    rows = list((await session.execute(q)).scalars())
    return rows[:limit], len(rows) > limit
