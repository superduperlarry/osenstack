from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ApprovalActionType(str, Enum):
    payment = "payment"
    transfer = "transfer"
    counterparty = "counterparty"


class Approval(BaseModel):
    id: str
    agent_id: str
    action_type: ApprovalActionType
    action_id: str
    trigger: str | None = None
    summary: dict[str, Any] | None = None
    status: ApprovalStatus
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    expires_at: datetime | None = None
    created_at: datetime


class ApprovalDecision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ActivityResource(BaseModel):
    type: str | None = None
    id: str | None = None


class ActivityEvent(BaseModel):
    id: str
    type: str
    agent_id: str | None  # required-but-nullable, per spec
    credential_id: str | None = None
    resource: ActivityResource | None = None
    data: dict[str, Any] | None = None
    occurred_at: datetime


class WebhookEndpointStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class WebhookEndpointCreate(BaseModel):
    url: str
    event_types: list[str] = Field(min_length=1)
    label: str | None = Field(default=None, max_length=120)


class WebhookEndpoint(BaseModel):
    id: str
    url: str
    event_types: list[str]
    label: str | None = None
    status: WebhookEndpointStatus
    created_at: datetime


class WebhookEndpointWithSecret(WebhookEndpoint):
    secret: str
