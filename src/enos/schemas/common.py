"""Schemas mirroring docs/agent_os_openapi.yaml components — the spec is the contract.

Field names, required-ness, enums, and patterns must match the spec exactly;
scripts/spec_diff.py fails CI on drift.
"""

from enum import Enum
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, Field

MONEY_PATTERN = r"^-?\d+(\.\d+)?$"

DecimalStr = Annotated[str, Field(pattern=MONEY_PATTERN, description="Decimal string. Never a float.")]


class Money(BaseModel):
    amount: DecimalStr
    currency: str = Field(description="ISO 4217 code.")


class Error(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str


class HolderType(str, Enum):
    owner = "owner"
    agent = "agent"


class BalanceRef(BaseModel):
    holder_type: HolderType
    holder_id: str


T = TypeVar("T")


class ListEnvelope(BaseModel, Generic[T]):
    data: list[T]
    has_more: bool
    next_cursor: str | None = None
