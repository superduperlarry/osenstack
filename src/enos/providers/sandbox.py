"""Sandbox stub adapters — the only Phase 0 provider implementations.

Deterministic where it matters for tests; no external calls."""

import hashlib
from decimal import ROUND_HALF_UP, Decimal

from enos.providers import registry
from enos.providers.base import (
    DispatchResult,
    IssuedCard,
    ProvisionedAccount,
    RouteQuote,
)

_CENT = Decimal("0.01")

# Static all-in FX table for the sandbox: destination units per source unit.
_RATES: dict[tuple[str, str], Decimal] = {
    ("USD", "PHP"): Decimal("56.10"),
    ("USD", "HKD"): Decimal("7.80"),
    ("USD", "EUR"): Decimal("0.92"),
    ("USD", "SGD"): Decimal("1.35"),
    ("HKD", "PHP"): Decimal("7.20"),
    ("HKD", "USD"): Decimal("0.128"),
    ("SGD", "USD"): Decimal("0.74"),
    ("EUR", "USD"): Decimal("1.09"),
    ("PHP", "USD"): Decimal("0.0178"),
}


def _digits_from(seed: str, n: int) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return str(int(h, 16))[-n:].zfill(n)


class SandboxCardIssuer:
    def issue(self, *, agent_id: str, label: str | None, form: str) -> IssuedCard:
        return IssuedCard(
            provider_ref=f"sbx_card_{_digits_from(agent_id + (label or ''), 12)}",
            network="visa",
            last4=_digits_from(agent_id + (label or "card"), 4),
            expiry_month=12,
            expiry_year=2030,
        )

    def freeze(self, provider_ref: str) -> None:  # sandbox: nothing to call out to
        return None

    def unfreeze(self, provider_ref: str) -> None:
        return None


class SandboxBankingPartner:
    def provision_virtual_account(
        self, *, owner_legal_name: str, agent_display_name: str, agent_id: str, currency: str
    ) -> ProvisionedAccount:
        return ProvisionedAccount(
            provider_ref=f"sbx_va_{_digits_from(agent_id + currency, 12)}",
            # Naming scheme pending banking-partner agreement (open gate 3).
            account_name=f"{owner_legal_name} — {agent_display_name}",
            account_number=_digits_from(agent_id + currency, 10),
            bank_name="Enstack Sandbox Bank",
            bank_identifier="ENSBSGSX",
            currency=currency,
            supported_rails=["bank_transfer_local", "fps"],
            status="active",
        )


class SandboxRoutingProvider:
    def _rate(self, source: str, destination: str) -> Decimal:
        if source == destination:
            return Decimal("1")
        rate = _RATES.get((source, destination))
        if rate is None:
            raise LookupError(f"Sandbox routing has no rate for {source}->{destination}")
        return rate

    def quote(
        self,
        *,
        source_currency: str,
        destination_currency: str,
        source_amount: Decimal | None,
        destination_amount: Decimal | None,
        destination_country: str | None,
    ) -> RouteQuote:
        rate = self._rate(source_currency, destination_currency)
        if source_amount is not None:
            src = source_amount
            dst = (src * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            assert destination_amount is not None
            dst = destination_amount
            src = (dst / rate).quantize(_CENT, rounding=ROUND_HALF_UP)
        fee = max((src * Decimal("0.0025")).quantize(_CENT, rounding=ROUND_HALF_UP), _CENT)
        same = source_currency == destination_currency
        return RouteQuote(
            source_amount=src,
            source_currency=source_currency,
            destination_amount=dst,
            destination_currency=destination_currency,
            rate=rate,
            fees=[{"type": "routing_fee", "amount": {"amount": str(fee), "currency": source_currency}}],
            estimated_arrival="instant" if same else "within 2 hours",
            ttl_minutes=30,
        )

    def dispatch(
        self, *, payment_id: str, destination_currency: str, is_cross_border: bool
    ) -> DispatchResult:
        rail = "bank_transfer" if is_cross_border else "fps"
        return DispatchResult(rail=rail, status="completed", detail="sandbox instant settlement")


registry.register(registry.KIND_CARD_ISSUER, "sandbox", SandboxCardIssuer())
registry.register(registry.KIND_BANKING_PARTNER, "sandbox", SandboxBankingPartner())
registry.register(registry.KIND_ROUTING_PROVIDER, "sandbox", SandboxRoutingProvider())
