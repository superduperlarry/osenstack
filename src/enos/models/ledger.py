from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enos.models.base import Base, MoneyAmount, utcnow


class LedgerAccount(Base):
    """One account per (owner, holder, currency), plus per-currency system accounts (owner_id NULL)."""

    __tablename__ = "ledger_accounts"
    __table_args__ = (
        UniqueConstraint("holder_type", "holder_id", "currency", name="uq_ledger_accounts_holder"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("owners.id"), index=True)
    holder_type: Mapped[str]  # owner | agent | system
    holder_id: Mapped[str]  # owner/agent id, or system account name (settlement, funding)
    currency: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LedgerEntry(Base):
    """Append-only double entry. Every journal_id sums to zero per currency."""

    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_entries_journal", "journal_id"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    journal_id: Mapped[str]
    account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id"), index=True)
    direction: Mapped[str]  # debit | credit
    amount: Mapped[MoneyAmount]  # always positive; direction carries the sign
    currency: Mapped[str]
    resource_type: Mapped[str | None]  # payment | transfer | funding | …
    resource_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Balance(Base):
    """Materialized balance per holder, updated in the same transaction as postings.

    Always derivable from ledger_entries; a test asserts agreement.
    """

    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("holder_type", "holder_id", name="uq_balances_holder"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"), index=True)
    holder_type: Mapped[str]  # owner | agent
    holder_id: Mapped[str]
    currency: Mapped[str]  # owner default currency for the headline amounts
    available: Mapped[MoneyAmount]
    pending_out: Mapped[MoneyAmount]
    breakdown: Mapped[list] = mapped_column(JSONB, default=list)  # [{amount, currency}]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
