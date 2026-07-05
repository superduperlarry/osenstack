"""Wires the pure policy engine into the request flow.

Single choke point: assembles contexts, calls `policy.evaluate`, and writes the
`policy.evaluation` ActivityEvent for **every** outcome. Held actions get an
Approval created via `raise_approval`. Denies raise the 403 `policy_denied` envelope.
"""

from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.models import Agent, Approval, Counterparty, Policy
from enos.models.base import utcnow
from enos.policy import ActionContext, AgentContext, Allow, Decision, Deny, Hold, evaluate
from enos.schemas.identity import PolicyCreate
from enos.services import activity, usage
from enos.services.context import Principal
from enos.services.errors import ApiError


async def load_active_policy(session: AsyncSession, agent: Agent) -> PolicyCreate | None:
    if agent.policy_version == 0:
        return None
    row = (
        await session.execute(
            select(Policy).where(
                Policy.agent_id == agent.id, Policy.version == agent.policy_version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return PolicyCreate.model_validate(row.document)


async def evaluate_action(
    session: AsyncSession,
    principal: Principal,
    agent: Agent,
    *,
    action_type: str,
    amount: Decimal | None = None,
    currency: str | None = None,
    counterparty: Counterparty | None = None,
    counterparty_is_new: bool | None = None,
    is_cross_border: bool = False,
) -> Decision:
    """Evaluate and record. Returns the decision; caller wires allow/hold/deny."""
    policy_doc = await load_active_policy(session, agent)
    daily, monthly, tx_today = await usage.spend_aggregates(session, agent.id)

    action = ActionContext(
        action_type=action_type,
        amount=amount,
        currency=currency,
        counterparty_id=counterparty.id if counterparty else None,
        counterparty_status=counterparty.status if counterparty else None,
        is_cross_border=is_cross_border,
        daily_spend=daily,
        monthly_spend=monthly,
        transactions_today=tx_today,
    )
    agent_ctx = AgentContext(
        agent_id=agent.id,
        status=agent.status,
        owner_verification_status=principal.owner.verification_status,
    )
    decision = evaluate(action, agent_ctx, policy_doc)

    outcome = {Allow: "allow", Hold: "hold", Deny: "deny"}[type(decision)]
    event_data = {
        "outcome": outcome,
        "policy_version": agent.policy_version,
        "action": {
            "action_type": action_type,
            "amount": str(amount) if amount is not None else None,
            "currency": currency,
            "counterparty_id": action.counterparty_id,
            "is_cross_border": is_cross_border,
        },
        **({"trigger": decision.trigger} if isinstance(decision, Hold) else {}),
        **({"rule": decision.rule} if isinstance(decision, Deny) else {}),
    }
    event_kwargs = dict(
        owner_id=principal.owner.id,
        type="policy.evaluation",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type=action_type,
        data=event_data,
    )
    if isinstance(decision, Deny):
        # A deny becomes a 403, which rolls the request transaction back — the
        # evaluation record must survive, so it gets its own committed session.
        from enos.db import get_sessionmaker

        async with get_sessionmaker()() as audit_session:
            await activity.record_event(audit_session, **event_kwargs)
            await audit_session.commit()
    else:
        await activity.record_event(session, **event_kwargs)
    return decision


def deny_error(decision: Deny) -> ApiError:
    return ApiError(
        403,
        "policy_denied",
        decision.message,
        {"rule": decision.rule, **decision.detail},
    )


async def raise_approval(
    session: AsyncSession,
    principal: Principal,
    agent: Agent,
    decision: Hold,
    *,
    action_type: str,
    action_id: str,
    summary: dict[str, Any],
) -> Approval:
    policy_doc = await load_active_policy(session, agent)
    expire_hours = policy_doc.approvals.auto_expire_hours if policy_doc else 72
    approval = Approval(
        id=ids.new_id(ids.APPROVAL),
        owner_id=principal.owner.id,
        agent_id=agent.id,
        action_type=action_type,
        action_id=action_id,
        trigger=decision.trigger,
        summary={**summary, **({"trigger_detail": decision.detail} if decision.detail else {})},
        status="pending",
        expires_at=utcnow() + timedelta(hours=expire_hours),
    )
    session.add(approval)
    await session.flush()
    await activity.record_event(
        session,
        owner_id=principal.owner.id,
        type="approval.requested",
        agent_id=agent.id,
        credential_id=principal.credential.id,
        resource_type="approval",
        resource_id=approval.id,
        data={"action_type": action_type, "action_id": action_id, "trigger": decision.trigger},
    )
    return approval


__all__ = ["Allow", "Deny", "Hold", "asdict", "deny_error", "evaluate_action", "load_active_policy", "raise_approval"]
