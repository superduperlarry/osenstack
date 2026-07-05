from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enos.models.base import Base, utcnow


class Approval(Base):
    """Human-in-the-loop queue. A held action is a 202 + one of these, never an error."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_owner", "owner_id"), Index("ix_approvals_agent", "agent_id"))

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    action_type: Mapped[str]  # payment | transfer | counterparty
    action_id: Mapped[str]
    trigger: Mapped[str]  # policy rule that raised it
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(default="pending")  # pending | approved | rejected | expired
    decided_by: Mapped[str | None]
    decided_at: Mapped[datetime | None]
    note: Mapped[str | None]
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ActivityEvent(Base):
    """Unified append-only feed. Every event carries agent + credential attribution."""

    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_owner_occurred", "owner_id", "occurred_at"),
        Index("ix_activity_agent", "agent_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    type: Mapped[str]  # dot notation: payment.completed, policy.evaluation, …
    agent_id: Mapped[str | None]
    credential_id: Mapped[str | None]
    resource_type: Mapped[str | None]
    resource_id: Mapped[str | None]
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)


class WebhookEndpoint(Base):
    """Endpoint management only — delivery machinery is out of Phase 0 scope."""

    __tablename__ = "webhook_endpoints"
    __table_args__ = (Index("ix_webhook_endpoints_owner", "owner_id"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    url: Mapped[str]
    event_types: Mapped[list] = mapped_column(JSONB)
    label: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="active")  # active | disabled
    secret_hash: Mapped[str]
    previous_secret_hash: Mapped[str | None]  # valid 24h after rotation
    rotated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("credential_id", "key", name="uq_idempotency_credential_key"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))
    key: Mapped[str]
    request_hash: Mapped[str]  # SHA-256 over method + path + canonical body
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class McpAudit(Base):
    """Append-only audit of every MCP tool invocation. Non-negotiable."""

    __tablename__ = "mcp_audit"
    __table_args__ = (Index("ix_mcp_audit_owner", "owner_id"), Index("ix_mcp_audit_agent", "agent_id"))

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str]
    agent_id: Mapped[str]
    credential_id: Mapped[str]
    tool: Mapped[str]
    args_hash: Mapped[str]  # SHA-256 of canonical arguments JSON
    idempotency_key: Mapped[str | None]
    result_status: Mapped[str]  # ok | error | denied
    request_id: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
