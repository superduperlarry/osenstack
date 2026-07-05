from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enos.models.base import Base, utcnow


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(primary_key=True)
    type: Mapped[str]  # individual | business
    legal_name: Mapped[str]
    display_name: Mapped[str | None]
    verification_status: Mapped[str] = mapped_column(default="pending")  # pending | verified | action_required
    country: Mapped[str]
    default_currency: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"), index=True)
    display_name: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="active")  # active | suspended | deactivated
    policy_version: Mapped[int] = mapped_column(Integer, default=0)  # 0 = default deny-all
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Credential(Base):
    """Scoped bearer credential. agent_id NULL = owner key (ok_…); else agent credential (ac_…)."""

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True)
    kind: Mapped[str]  # api | mcp (agent credentials) | owner (owner keys, never a Credential resource)
    label: Mapped[str | None]
    token_hash: Mapped[str] = mapped_column(unique=True)  # SHA-256 of the bearer secret
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(default="active")  # active | revoked
    last_used_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Policy(Base):
    """Versioned, immutable policy rows. Replaced whole via PUT; never patched."""

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_policies_agent_version"),
        Index("ix_policies_owner", "owner_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSONB)  # {limits, counterparty_allowlist, …, approvals} per spec
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
