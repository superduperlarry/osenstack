"""Inputs and outcomes for the policy engine. Pure data — no I/O, no ORM."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ActionContext:
    """A proposed action, with usage aggregates pre-assembled by the caller.

    All amounts are Decimal, expressed in the owner's default currency.
    """

    action_type: str  # payment | transfer | counterparty | card_authorization
    amount: Decimal | None = None
    currency: str | None = None  # destination currency of the action
    counterparty_id: str | None = None
    counterparty_status: str | None = None  # unverified | verified | blocked
    is_cross_border: bool = False
    merchant_category: str | None = None  # MCC, card authorizations only
    daily_spend: Decimal = Decimal("0")
    monthly_spend: Decimal = Decimal("0")
    transactions_today: int = 0


@dataclass(frozen=True)
class AgentContext:
    agent_id: str
    status: str  # active | suspended | deactivated
    owner_verification_status: str  # pending | verified | action_required


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Hold:
    """The action must be held pending owner approval — a 202, never an error."""

    trigger: str  # policy rule that raised the approval, e.g. require_approval_above
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Deny:
    """Hard policy block — 403 policy_denied."""

    rule: str
    message: str
    detail: dict = field(default_factory=dict)


Decision = Allow | Hold | Deny
