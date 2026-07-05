from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from enos.schemas.common import BalanceRef, HolderType, Money


class Balance(BaseModel):
    holder_type: HolderType
    holder_id: str
    available: Money
    pending_out: Money | None = None
    currency_breakdown: list[Money]
    updated_at: datetime


class FundingMethod(BaseModel):
    rail: str
    account_name: str
    account_number: str | None = None
    bank_name: str | None = None
    bank_identifier: str | None = None
    currency: str | None = None
    reference: str


class FundingInstructions(BaseModel):
    agent_id: str
    methods: list[FundingMethod]


class TransferStatus(str, Enum):
    completed = "completed"
    pending_approval = "pending_approval"
    cancelled = "cancelled"


class Transfer(BaseModel):
    id: str
    source: BalanceRef
    destination: BalanceRef
    amount: Money
    status: TransferStatus
    approval_id: str | None = None
    note: str | None = None
    created_at: datetime


class TransferCreate(BaseModel):
    source: BalanceRef
    destination: BalanceRef
    amount: Money
    note: str | None = Field(default=None, max_length=280)


class QuoteCreate(BaseModel):
    agent_id: str
    source_amount: Money | None = None
    destination_amount: Money | None = None
    destination_currency: str
    destination_country: str | None = None
    counterparty_id: str | None = None


class QuoteFee(BaseModel):
    type: str
    amount: Money


class Quote(BaseModel):
    id: str
    agent_id: str
    source_amount: Money
    destination_amount: Money
    rate: str
    fees: list[QuoteFee]
    estimated_arrival: str | None = None
    expires_at: datetime
    created_at: datetime


class PaymentStatus(str, Enum):
    pending_approval = "pending_approval"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    returned = "returned"


class PaymentCreate(BaseModel):
    agent_id: str
    counterparty_id: str
    quote_id: str | None = None
    amount: Money | None = None
    reference: str | None = Field(default=None, max_length=140)
    purpose: str | None = Field(default=None, max_length=280)


class TimelineEntry(BaseModel):
    status: str
    at: datetime
    detail: str | None = None


class Payment(BaseModel):
    id: str
    agent_id: str
    credential_id: str | None = None
    counterparty_id: str
    quote_id: str | None = None
    source_amount: Money
    destination_amount: Money | None = None
    status: PaymentStatus
    approval_id: str | None = None
    failure_reason: str | None = None
    rail: str | None = None
    reference: str | None = None
    purpose: str | None = None
    timeline: list[TimelineEntry] | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CounterpartyStatus(str, Enum):
    unverified = "unverified"
    verified = "verified"
    blocked = "blocked"


class DestinationType(str, Enum):
    bank_account = "bank_account"
    ewallet = "ewallet"
    card_payout = "card_payout"


class CounterpartyDestination(BaseModel):
    type: DestinationType
    currency: str | None = None
    country: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    bank_identifier: str | None = None
    ewallet_provider: str | None = None
    ewallet_id: str | None = None


class CounterpartyCreate(BaseModel):
    display_name: str = Field(max_length=120)
    destination: CounterpartyDestination
    metadata: dict[str, str] | None = None


class DestinationSummary(BaseModel):
    type: str | None = None
    currency: str | None = None
    country: str | None = None
    masked_identifier: str | None = None


class ActorType(str, Enum):
    owner = "owner"
    agent = "agent"


class CreatedBy(BaseModel):
    actor_type: ActorType | None = None
    actor_id: str | None = None


class Counterparty(BaseModel):
    id: str
    display_name: str
    destination_summary: DestinationSummary
    status: CounterpartyStatus
    created_by: CreatedBy | None = None
    created_at: datetime
