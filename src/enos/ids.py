"""Prefixed ULID identifiers, matching the spec's id examples (agt_01J…)."""

from ulid import ULID

OWNER = "own"
AGENT = "agt"
CREDENTIAL = "crd"
POLICY = "pol"
LEDGER_ACCOUNT = "lac"
LEDGER_ENTRY = "led"
JOURNAL = "jrn"
BALANCE = "bal"
PAYMENT = "pay"
TRANSFER = "trf"
QUOTE = "qot"
COUNTERPARTY = "cpt"
CARD = "crd_v"
VIRTUAL_ACCOUNT = "va"
APPROVAL = "apr"
ACTIVITY_EVENT = "evt"
WEBHOOK_ENDPOINT = "whe"
IDEMPOTENCY = "idk"
MCP_AUDIT = "mca"
REQUEST = "req"


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"
