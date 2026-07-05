"""Pure unit tests for the policy engine — one per row of the semantics table."""

from decimal import Decimal

from enos.policy import ActionContext, AgentContext, Allow, Deny, Hold, evaluate
from enos.schemas.identity import PolicyApprovals, PolicyCreate, PolicyLimits


def make_policy(**overrides) -> PolicyCreate:
    base = dict(
        limits=PolicyLimits(
            per_transaction={"amount": "500.00", "currency": "USD"},
            daily={"amount": "1000.00", "currency": "USD"},
            monthly={"amount": "5000.00", "currency": "USD"},
            max_transactions_per_day=10,
        ),
        approvals=PolicyApprovals(
            require_approval_above={"amount": "200.00", "currency": "USD"},
            require_approval_for_new_counterparties=True,
            require_approval_for_cross_border=False,
        ),
    )
    base.update(overrides)
    return PolicyCreate(**base)


ACTIVE_AGENT = AgentContext(agent_id="agt_1", status="active", owner_verification_status="verified")


def payment(amount: str = "100.00", **overrides) -> ActionContext:
    base = dict(
        action_type="payment",
        amount=Decimal(amount),
        currency="USD",
        counterparty_id="cpt_1",
        counterparty_status="verified",
    )
    base.update(overrides)
    return ActionContext(**base)


# ── Deny (categorical) ────────────────────────────────────────────────────


def test_no_policy_is_deny_all():
    decision = evaluate(payment(), ACTIVE_AGENT, None)
    assert isinstance(decision, Deny) and decision.rule == "no_policy"


def test_suspended_agent_denied():
    agent = AgentContext(agent_id="agt_1", status="suspended", owner_verification_status="verified")
    decision = evaluate(payment(), agent, make_policy())
    assert isinstance(decision, Deny) and decision.rule == "agent_not_active"


def test_unverified_owner_denied():
    agent = AgentContext(agent_id="agt_1", status="active", owner_verification_status="pending")
    decision = evaluate(payment(), agent, make_policy())
    assert isinstance(decision, Deny) and decision.rule == "owner_not_verified"


def test_blocked_counterparty_denied():
    decision = evaluate(payment(counterparty_status="blocked"), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Deny) and decision.rule == "counterparty_blocked"


def test_currency_allowlist_miss_denied():
    policy = make_policy(currency_allowlist=["USD"])
    decision = evaluate(payment(currency="EUR"), ACTIVE_AGENT, policy)
    assert isinstance(decision, Deny) and decision.rule == "currency_allowlist"


def test_merchant_category_allowlist_denied():
    policy = make_policy(merchant_category_allowlist=["5812"])
    action = ActionContext(
        action_type="card_authorization", amount=Decimal("10"), currency="USD",
        merchant_category="7995",
    )
    decision = evaluate(action, ACTIVE_AGENT, policy)
    assert isinstance(decision, Deny) and decision.rule == "merchant_category_allowlist"


def test_counterparty_allowlist_miss_denied():
    policy = make_policy(counterparty_allowlist=["cpt_other"])
    decision = evaluate(payment(), ACTIVE_AGENT, policy)
    assert isinstance(decision, Deny) and decision.rule == "counterparty_allowlist"


def test_verified_counterparties_only_denied():
    policy = make_policy(verified_counterparties_only=True)
    decision = evaluate(payment(counterparty_status="unverified"), ACTIVE_AGENT, policy)
    assert isinstance(decision, Deny) and decision.rule == "verified_counterparties_only"


# ── Hold (quantitative / review — 202, never an error) ───────────────────


def test_per_transaction_limit_holds():
    decision = evaluate(payment("600.00"), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Hold) and decision.trigger == "per_transaction_limit"


def test_daily_limit_holds():
    decision = evaluate(
        payment("150.00", daily_spend=Decimal("900.00")), ACTIVE_AGENT, make_policy()
    )
    assert isinstance(decision, Hold) and decision.trigger == "daily_limit"


def test_monthly_limit_holds():
    decision = evaluate(
        payment("150.00", monthly_spend=Decimal("4900.00")), ACTIVE_AGENT, make_policy()
    )
    assert isinstance(decision, Hold) and decision.trigger == "monthly_limit"


def test_velocity_limit_holds():
    decision = evaluate(payment(transactions_today=10), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Hold) and decision.trigger == "max_transactions_per_day"


def test_require_approval_above_holds():
    decision = evaluate(payment("300.00"), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Hold) and decision.trigger == "require_approval_above"


def test_new_counterparty_holds():
    decision = evaluate(payment(counterparty_status="unverified"), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Hold) and decision.trigger == "new_counterparty"


def test_cross_border_holds_when_required():
    policy = make_policy(
        approvals=PolicyApprovals(
            require_approval_for_new_counterparties=False,
            require_approval_for_cross_border=True,
        )
    )
    decision = evaluate(payment(is_cross_border=True), ACTIVE_AGENT, policy)
    assert isinstance(decision, Hold) and decision.trigger == "cross_border"


# ── Allow ─────────────────────────────────────────────────────────────────


def test_within_policy_allows():
    decision = evaluate(payment("100.00"), ACTIVE_AGENT, make_policy())
    assert isinstance(decision, Allow)


def test_deny_wins_over_hold():
    """Categorical deny is checked before any hold rule fires."""
    policy = make_policy(currency_allowlist=["USD"])
    decision = evaluate(payment("600.00", currency="EUR"), ACTIVE_AGENT, policy)
    assert isinstance(decision, Deny) and decision.rule == "currency_allowlist"
