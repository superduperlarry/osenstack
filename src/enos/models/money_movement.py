from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enos.models.base import Base, MoneyAmount, utcnow


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (Index("ix_quotes_owner", "owner_id"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    source_amount: Mapped[MoneyAmount]
    source_currency: Mapped[str]
    destination_amount: Mapped[MoneyAmount]
    destination_currency: Mapped[str]
    rate: Mapped[Decimal]  # destination units per source unit, all-in
    fees: Mapped[list] = mapped_column(JSONB, default=list)  # [{type, amount: {amount, currency}}]
    estimated_arrival: Mapped[str | None]
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_owner", "owner_id"),
        Index("ix_payments_agent", "agent_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))  # attribution, never optional
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"))
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"))
    source_amount: Mapped[MoneyAmount]
    source_currency: Mapped[str]
    destination_amount: Mapped[Decimal | None]
    destination_currency: Mapped[str | None]
    status: Mapped[str]  # pending_approval | processing | completed | failed | cancelled | returned
    approval_id: Mapped[str | None]
    failure_reason: Mapped[str | None]
    rail: Mapped[str | None]
    reference: Mapped[str | None]
    purpose: Mapped[str | None]
    timeline: Mapped[list] = mapped_column(JSONB, default=list)  # [{status, at, detail}]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None]


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (Index("ix_transfers_owner", "owner_id"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"))  # initiating agent, if any
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))
    source_holder_type: Mapped[str]
    source_holder_id: Mapped[str]
    destination_holder_type: Mapped[str]
    destination_holder_id: Mapped[str]
    amount: Mapped[MoneyAmount]
    currency: Mapped[str]
    status: Mapped[str]  # completed | pending_approval | cancelled
    approval_id: Mapped[str | None]
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Counterparty(Base):
    __tablename__ = "counterparties"
    __table_args__ = (Index("ix_counterparties_owner", "owner_id"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    display_name: Mapped[str]
    destination: Mapped[dict] = mapped_column(JSONB)  # full details; reads expose masked summary only
    status: Mapped[str] = mapped_column(default="unverified")  # unverified | verified | blocked
    created_by_actor_type: Mapped[str]  # owner | agent
    created_by_actor_id: Mapped[str]
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
