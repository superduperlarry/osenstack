from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CardForm(str, Enum):
    virtual = "virtual"
    physical = "physical"


class CardFormCreate(str, Enum):
    virtual = "virtual"


class CardStatus(str, Enum):
    active = "active"
    frozen = "frozen"
    terminated = "terminated"


class CardNetwork(str, Enum):
    visa = "visa"


class CardCreate(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    form: CardFormCreate = CardFormCreate.virtual


class Card(BaseModel):
    id: str
    agent_id: str
    label: str | None = None
    form: CardForm
    status: CardStatus
    network: CardNetwork = CardNetwork.visa
    last4: str
    expiry_month: int | None = None
    expiry_year: int | None = None
    created_at: datetime


class VirtualAccountStatus(str, Enum):
    provisioning = "provisioning"
    active = "active"
    closed = "closed"


class VirtualAccountCreate(BaseModel):
    currency: str | None = None
    label: str | None = Field(default=None, max_length=60)


class VirtualAccount(BaseModel):
    id: str
    agent_id: str
    label: str | None = None
    account_name: str
    account_number: str | None = None
    bank_name: str | None = None
    bank_identifier: str | None = None
    currency: str | None = None
    supported_rails: list[str] | None = None
    status: VirtualAccountStatus
    created_at: datetime
