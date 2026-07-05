from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enos.models.base import Base, utcnow


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (Index("ix_cards_owner", "owner_id"), Index("ix_cards_agent", "agent_id"))

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    provider_ref: Mapped[str]  # issuer adapter's reference; never exposed
    label: Mapped[str | None]
    form: Mapped[str] = mapped_column(default="virtual")  # virtual | physical (Phase 2)
    status: Mapped[str] = mapped_column(default="active")  # active | frozen | terminated
    network: Mapped[str] = mapped_column(default="visa")
    last4: Mapped[str]  # PAN/CVV never stored; the issuer adapter holds them
    expiry_month: Mapped[int] = mapped_column(Integer)
    expiry_year: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class VirtualAccount(Base):
    __tablename__ = "virtual_accounts"
    __table_args__ = (
        Index("ix_virtual_accounts_owner", "owner_id"),
        Index("ix_virtual_accounts_agent", "agent_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("owners.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    provider_ref: Mapped[str]  # banking adapter's reference; never exposed
    label: Mapped[str | None]
    account_name: Mapped[str]  # "{owner_legal_name} — {agent_display_name}" pending gate 3
    account_number: Mapped[str | None]
    bank_name: Mapped[str | None]
    bank_identifier: Mapped[str | None]
    currency: Mapped[str]
    supported_rails: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(default="provisioning")  # provisioning | active | closed
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
