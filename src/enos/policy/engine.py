"""The policy engine — the authorization core of Agent OS.

`evaluate` is a pure function: callers assemble the contexts, the engine
decides. Semantics (deny checks run first; within a group, first hit wins):

- **Deny** (categorical — things the owner said "never"): no policy attached
  (version 0 deny-all), agent not active, owner not verified, blocked
  counterparty, currency/merchant-category/counterparty allowlist misses,
  `verified_counterparties_only` violations.
- **Hold** (quantitative / review rules — one-off approvable by the owner):
  per-transaction/daily/monthly limits, velocity, `require_approval_above`,
  new counterparties, cross-border.

Every evaluation must be recorded as a `policy.evaluation` ActivityEvent —
that is the caller's job (see services.policy_gate), since the engine does no I/O.
"""

from decimal import Decimal

from enos.policy.types import ActionContext, AgentContext, Allow, Decision, Deny, Hold
from enos.schemas.identity import PolicyCreate

MONETARY_ACTIONS = ("payment", "transfer", "card_authorization")


def evaluate(action: ActionContext, agent: AgentContext, policy: PolicyCreate | None) -> Decision:
    # ── Deny: categorical rules ──────────────────────────────────────────
    if policy is None:
        return Deny(rule="no_policy", message="Agent has no policy attached (default deny-all).")

    if agent.status != "active":
        return Deny(rule="agent_not_active", message=f"Agent is {agent.status}.")

    if agent.owner_verification_status != "verified":
        return Deny(rule="owner_not_verified", message="Owner verification is not complete.")

    if action.counterparty_status == "blocked":
        return Deny(rule="counterparty_blocked", message="Counterparty is blocked.")

    if (
        policy.currency_allowlist is not None
        and action.currency is not None
        and action.currency not in policy.currency_allowlist
    ):
        return Deny(
            rule="currency_allowlist",
            message=f"Currency {action.currency} is not on the policy allowlist.",
            detail={"currency": action.currency, "allowed": policy.currency_allowlist},
        )

    if (
        policy.merchant_category_allowlist is not None
        and action.merchant_category is not None
        and action.merchant_category not in policy.merchant_category_allowlist
    ):
        return Deny(
            rule="merchant_category_allowlist",
            message=f"Merchant category {action.merchant_category} is not permitted.",
        )

    if action.action_type in ("payment",) and action.counterparty_id is not None:
        if (
            policy.counterparty_allowlist is not None
            and action.counterparty_id not in policy.counterparty_allowlist
        ):
            return Deny(
                rule="counterparty_allowlist",
                message="Counterparty is not on the policy allowlist.",
                detail={"counterparty_id": action.counterparty_id},
            )
        if policy.verified_counterparties_only and action.counterparty_status != "verified":
            return Deny(
                rule="verified_counterparties_only",
                message="Policy permits owner-verified counterparties only.",
            )

    # ── Hold: quantitative limits and review rules ───────────────────────
    if action.action_type in MONETARY_ACTIONS and action.amount is not None:
        limits = policy.limits
        if limits.per_transaction is not None and action.amount > Decimal(limits.per_transaction.amount):
            return Hold(trigger="per_transaction_limit", detail={"limit": limits.per_transaction.amount})
        if limits.daily is not None and action.daily_spend + action.amount > Decimal(limits.daily.amount):
            return Hold(trigger="daily_limit", detail={"limit": limits.daily.amount})
        if limits.monthly is not None and action.monthly_spend + action.amount > Decimal(limits.monthly.amount):
            return Hold(trigger="monthly_limit", detail={"limit": limits.monthly.amount})
        if (
            limits.max_transactions_per_day is not None
            and action.transactions_today + 1 > limits.max_transactions_per_day
        ):
            return Hold(
                trigger="max_transactions_per_day",
                detail={"limit": limits.max_transactions_per_day},
            )

        approvals = policy.approvals
        if approvals.require_approval_above is not None and action.amount > Decimal(
            approvals.require_approval_above.amount
        ):
            return Hold(
                trigger="require_approval_above",
                detail={"threshold": approvals.require_approval_above.amount},
            )

    if (
        action.action_type in ("payment", "counterparty")
        and policy.approvals.require_approval_for_new_counterparties
        and action.counterparty_status == "unverified"
    ):
        return Hold(trigger="new_counterparty")

    if (
        action.action_type in ("payment",)
        and policy.approvals.require_approval_for_cross_border
        and action.is_cross_border
    ):
        return Hold(trigger="cross_border")

    return Allow()
