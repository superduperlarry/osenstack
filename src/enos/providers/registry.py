"""Name → adapter resolution. The only place provider selection happens."""

from typing import Any

from enos.config import get_settings

_REGISTRY: dict[tuple[str, str], Any] = {}

KIND_CARD_ISSUER = "card_issuer"
KIND_BANKING_PARTNER = "banking_partner"
KIND_ROUTING_PROVIDER = "routing_provider"


def register(kind: str, name: str, adapter: Any) -> None:
    _REGISTRY[(kind, name)] = adapter


def resolve(kind: str) -> Any:
    settings = get_settings()
    name = getattr(settings, kind)
    try:
        return _REGISTRY[(kind, name)]
    except KeyError:
        raise LookupError(
            f"No {kind} adapter registered under {name!r}. "
            f"Registered: {[n for k, n in _REGISTRY if k == kind]}"
        ) from None


def get_card_issuer():
    return resolve(KIND_CARD_ISSUER)


def get_banking_partner():
    return resolve(KIND_BANKING_PARTNER)


def get_routing_provider():
    return resolve(KIND_ROUTING_PROVIDER)


def _register_builtin() -> None:
    # Import-time registration of bundled adapters. Additional adapters
    # register themselves the same way from their own package.
    from enos.providers import sandbox  # noqa: F401


_register_builtin()
