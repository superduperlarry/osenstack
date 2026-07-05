from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from enos.schemas.common import Money


class OwnerType(str, Enum):
    individual = "individual"
    business = "business"


class VerificationStatus(str, Enum):
    pending = "pending"
    verified = "verified"
    action_required = "action_required"


class Owner(BaseModel):
    id: str
    type: OwnerType
    legal_name: str
    display_name: str | None = None
    verification_status: VerificationStatus
    country: str | None = None
    default_currency: str | None = None
    created_at: datetime


class AgentStatus(str, Enum):
    active = "active"
    suspended = "suspended"
    deactivated = "deactivated"


class Agent(BaseModel):
    id: str
    owner_id: str
    display_name: str
    description: str | None = None
    status: AgentStatus
    policy_version: int
    metadata: dict[str, str] | None = None
    created_at: datetime


class AgentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    metadata: dict[str, str] | None = None


class AgentUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    metadata: dict[str, str] | None = None


class CredentialKind(str, Enum):
    api = "api"
    mcp = "mcp"


class CredentialScope(str, Enum):
    balance_read = "balance:read"
    quotes_create = "quotes:create"
    payments_create = "payments:create"
    payments_read = "payments:read"
    transfers_create = "transfers:create"
    transfers_read = "transfers:read"
    counterparties_create = "counterparties:create"
    counterparties_read = "counterparties:read"
    cards_read = "cards:read"
    cards_freeze = "cards:freeze"
    approvals_read = "approvals:read"
    activity_read = "activity:read"
    policy_read = "policy:read"


class CredentialStatus(str, Enum):
    active = "active"
    revoked = "revoked"


class Credential(BaseModel):
    id: str
    agent_id: str
    kind: CredentialKind
    label: str | None = None
    scopes: list[CredentialScope]
    status: CredentialStatus
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class CredentialCreate(BaseModel):
    kind: CredentialKind
    label: str | None = Field(default=None, max_length=120)
    scopes: list[CredentialScope] = Field(min_length=1)
    expires_at: datetime | None = None


class CredentialWithSecret(Credential):
    secret: str


class PolicyLimits(BaseModel):
    per_transaction: Money | None = None
    daily: Money | None = None
    monthly: Money | None = None
    max_transactions_per_day: int | None = None


class PolicyApprovals(BaseModel):
    require_approval_above: Money | None = None
    require_approval_for_new_counterparties: bool = True
    require_approval_for_cross_border: bool = False
    auto_expire_hours: int = 72


class Policy(BaseModel):
    agent_id: str
    version: int
    limits: PolicyLimits
    counterparty_allowlist: list[str] | None = None
    verified_counterparties_only: bool = False
    merchant_category_allowlist: list[str] | None = None
    currency_allowlist: list[str] | None = None
    approvals: PolicyApprovals
    created_at: datetime


class PolicyCreate(BaseModel):
    limits: PolicyLimits
    counterparty_allowlist: list[str] | None = None
    verified_counterparties_only: bool = False
    merchant_category_allowlist: list[str] | None = None
    currency_allowlist: list[str] | None = None
    approvals: PolicyApprovals
