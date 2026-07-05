"""Provider abstraction. Adapters implement these Protocols; nothing outside
`enos.providers` may reference a concrete provider by name — resolution goes
through the registry, configured in settings. A hardcoded provider conditional
is a rejected change (CI greps for it)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class IssuedCard:
    provider_ref: str
    network: str
    last4: str
    expiry_month: int
    expiry_year: int


@dataclass(frozen=True)
class ProvisionedAccount:
    provider_ref: str
    account_name: str
    account_number: str
    bank_name: str
    bank_identifier: str
    currency: str
    supported_rails: list[str]
    status: str  # provisioning | active


@dataclass(frozen=True)
class RouteQuote:
    source_amount: Decimal
    source_currency: str
    destination_amount: Decimal
    destination_currency: str
    rate: Decimal  # destination units per source unit, all-in
    fees: list[dict]  # [{type, amount: {amount, currency}}] — decimal strings
    estimated_arrival: str
    ttl_minutes: int


@dataclass(frozen=True)
class DispatchResult:
    rail: str
    status: str  # completed | processing | failed
    detail: str | None = None


class CardIssuer(Protocol):
    def issue(self, *, agent_id: str, label: str | None, form: str) -> IssuedCard: ...
    def freeze(self, provider_ref: str) -> None: ...
    def unfreeze(self, provider_ref: str) -> None: ...


class BankingPartner(Protocol):
    def provision_virtual_account(
        self, *, owner_legal_name: str, agent_display_name: str, agent_id: str, currency: str
    ) -> ProvisionedAccount: ...


class RoutingProvider(Protocol):
    def quote(
        self,
        *,
        source_currency: str,
        destination_currency: str,
        source_amount: Decimal | None,
        destination_amount: Decimal | None,
        destination_country: str | None,
    ) -> RouteQuote: ...

    def dispatch(
        self, *, payment_id: str, destination_currency: str, is_cross_border: bool
    ) -> DispatchResult: ...
