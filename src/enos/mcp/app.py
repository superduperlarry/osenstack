"""enos-mcp role: the single agent contract. 19 tools, all thin audited
wrappers over the internal service layer — one policy engine, two doors.

Owner-scope capabilities (agent lifecycle, credential issuance, policy writes,
approval decisions, counterparty verification, card unfreeze, webhooks) are
deliberately absent: agents operate inside the box; only the owner reshapes it.
"""

import contextlib
import json
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from enos.mcp.runtime import run_tool
from enos.schemas import (
    CounterpartyCreate,
    Money,
    PaymentCreate,
    QuoteCreate,
    TransferCreate,
)
from enos.schemas.common import BalanceRef, HolderType
from enos.schemas.money_movement import CounterpartyDestination
from enos.services import activity as activity_service
from enos.services import approvals as approvals_service
from enos.services import cards as cards_service
from enos.services import counterparties as counterparties_service
from enos.services import owners as owners_service
from enos.services import payments as payments_service
from enos.services import policies as policies_service
from enos.services import quotes as quotes_service
from enos.services import serialize
from enos.services import transfers as transfers_service
from enos.services import virtual_accounts as va_service

mcp = FastMCP(
    "enos-mcp",
    instructions=(
        "Enstack Agent OS — give your AI agents real money, and real control. "
        "Authenticate with your agent credential (ac_…) as a bearer token. "
        "Every action is evaluated against your owner-defined Policy: results are "
        "`processing` (done), `pending_approval` (held for your owner — not an error; "
        "poll list_approvals), or `policy_denied`. Use get_policy and get_balance to "
        "plan within your limits instead of discovering them by failing."
    ),
    stateless_http=True,
    json_response=True,
    # Hosted network server behind containers/load balancers: the Host header
    # is deployment-dependent and auth is bearer-token based, so the SDK's
    # DNS-rebinding (Host allowlist) protection is disabled.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _dump(schema_obj) -> dict[str, Any]:
    return json.loads(schema_obj.model_dump_json())


# ── Read tools ────────────────────────────────────────────────────────────


@mcp.tool()
async def get_balance(ctx: Context) -> dict:
    """Get this agent's current balance (available, pending_out, per-currency breakdown)."""

    async def body(session, principal):
        balance = await owners_service.get_agent_balance(session, principal, principal.agent.id)
        return {"balance": _dump(serialize.balance(balance))}

    return await run_tool(ctx, "get_balance", {}, body)


@mcp.tool()
async def get_funding_instructions(ctx: Context) -> dict:
    """How to top up this agent's balance: virtual account details per funding rail."""

    async def body(session, principal):
        instructions = await va_service.funding_instructions(session, principal, principal.agent.id)
        return {"funding_instructions": _dump(instructions)}

    return await run_tool(ctx, "get_funding_instructions", {}, body)


@mcp.tool()
async def get_policy(ctx: Context) -> dict:
    """Read this agent's active policy (limits, allowlists, approval rules) to plan within it."""

    async def body(session, principal):
        policy = await policies_service.get_active_policy(session, principal, principal.agent)
        return {"policy": _dump(policy)}

    return await run_tool(ctx, "get_policy", {}, body)


# ── Quotes ────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_quote(
    ctx: Context,
    destination_currency: str,
    source_amount: Money | None = None,
    destination_amount: Money | None = None,
    destination_country: str | None = None,
    counterparty_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Price a cross-currency payment. The quote is firm until expires_at; pass its id to create_payment."""
    args = {
        "destination_currency": destination_currency,
        "source_amount": source_amount.model_dump() if source_amount else None,
        "destination_amount": destination_amount.model_dump() if destination_amount else None,
        "destination_country": destination_country,
        "counterparty_id": counterparty_id,
    }

    async def body(session, principal):
        quote = await quotes_service.create_quote(
            session,
            principal,
            QuoteCreate(
                agent_id=principal.agent.id,
                source_amount=source_amount,
                destination_amount=destination_amount,
                destination_currency=destination_currency,
                destination_country=destination_country,
                counterparty_id=counterparty_id,
            ),
        )
        return {"outcome": "created", "quote": _dump(serialize.quote(quote))}

    return await run_tool(
        ctx, "create_quote", args, body, mutating=True, idempotency_key=idempotency_key
    )


@mcp.tool()
async def get_quote(ctx: Context, quote_id: str) -> dict:
    """Retrieve a quote by id."""

    async def body(session, principal):
        quote = await quotes_service.get_quote(session, principal, quote_id)
        return {"quote": _dump(serialize.quote(quote))}

    return await run_tool(ctx, "get_quote", {"quote_id": quote_id}, body)


# ── Payments ──────────────────────────────────────────────────────────────


@mcp.tool()
async def create_payment(
    ctx: Context,
    counterparty_id: str,
    quote_id: str | None = None,
    amount: Money | None = None,
    reference: str | None = None,
    purpose: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Send funds to a counterparty. Same-currency: pass amount. Cross-currency: pass quote_id.
    Three outcomes: `processing`, `pending_approval` (your owner was notified — not an error),
    or `policy_denied`. Reason about next steps from the outcome field."""
    args = {
        "counterparty_id": counterparty_id,
        "quote_id": quote_id,
        "amount": amount.model_dump() if amount else None,
        "reference": reference,
        "purpose": purpose,
    }

    async def body(session, principal):
        payment = await payments_service.create_payment(
            session,
            principal,
            PaymentCreate(
                agent_id=principal.agent.id,
                counterparty_id=counterparty_id,
                quote_id=quote_id,
                amount=amount,
                reference=reference,
                purpose=purpose,
            ),
        )
        outcome = "pending_approval" if payment.status == "pending_approval" else "processing"
        return {
            "outcome": outcome,
            **({"approval_id": payment.approval_id} if payment.approval_id else {}),
            "payment": _dump(serialize.payment(payment)),
        }

    return await run_tool(
        ctx, "create_payment", args, body, mutating=True, idempotency_key=idempotency_key
    )


@mcp.tool()
async def get_payment(ctx: Context, payment_id: str) -> dict:
    """Retrieve a payment, including its status timeline."""

    async def body(session, principal):
        payment = await payments_service.get_payment(session, principal, payment_id)
        return {"payment": _dump(serialize.payment(payment))}

    return await run_tool(ctx, "get_payment", {"payment_id": payment_id}, body)


@mcp.tool()
async def list_payments(
    ctx: Context,
    limit: int = 20,
    starting_after: str | None = None,
    status: str | None = None,
) -> dict:
    """List this agent's payments, newest first."""
    args = {"limit": limit, "starting_after": starting_after, "status": status}

    async def body(session, principal):
        rows, has_more = await payments_service.list_payments(
            session, principal, limit=limit, starting_after=starting_after, status=status
        )
        return {
            "payments": [_dump(serialize.payment(p)) for p in rows],
            "has_more": has_more,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    return await run_tool(ctx, "list_payments", args, body)


@mcp.tool()
async def cancel_payment(ctx: Context, payment_id: str, idempotency_key: str | None = None) -> dict:
    """Cancel a payment. Pre-dispatch only — pending_approval payments can always be cancelled."""

    async def body(session, principal):
        payment = await payments_service.cancel_payment(session, principal, payment_id)
        return {"outcome": "cancelled", "payment": _dump(serialize.payment(payment))}

    return await run_tool(
        ctx,
        "cancel_payment",
        {"payment_id": payment_id},
        body,
        mutating=True,
        idempotency_key=idempotency_key,
    )


# ── Transfers ─────────────────────────────────────────────────────────────


@mcp.tool()
async def create_transfer(
    ctx: Context,
    destination_holder_type: str,
    destination_holder_id: str,
    amount: Money,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Move funds from this agent's balance to the owner treasury or a sibling agent.
    Instant and fee-free; policy-evaluated."""
    args = {
        "destination_holder_type": destination_holder_type,
        "destination_holder_id": destination_holder_id,
        "amount": amount.model_dump(),
        "note": note,
    }

    async def body(session, principal):
        transfer = await transfers_service.create_transfer(
            session,
            principal,
            TransferCreate(
                source=BalanceRef(holder_type=HolderType.agent, holder_id=principal.agent.id),
                destination=BalanceRef(
                    holder_type=HolderType(destination_holder_type),
                    holder_id=destination_holder_id,
                ),
                amount=amount,
                note=note,
            ),
        )
        outcome = "pending_approval" if transfer.status == "pending_approval" else "completed"
        return {
            "outcome": outcome,
            **({"approval_id": transfer.approval_id} if transfer.approval_id else {}),
            "transfer": _dump(serialize.transfer(transfer)),
        }

    return await run_tool(
        ctx, "create_transfer", args, body, mutating=True, idempotency_key=idempotency_key
    )


@mcp.tool()
async def list_transfers(ctx: Context, limit: int = 20, starting_after: str | None = None) -> dict:
    """List this agent's internal transfers."""
    args = {"limit": limit, "starting_after": starting_after}

    async def body(session, principal):
        rows, has_more = await transfers_service.list_transfers(
            session, principal, limit=limit, starting_after=starting_after
        )
        return {
            "transfers": [_dump(serialize.transfer(t)) for t in rows],
            "has_more": has_more,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    return await run_tool(ctx, "list_transfers", args, body)


# ── Counterparties ────────────────────────────────────────────────────────


@mcp.tool()
async def create_counterparty(
    ctx: Context,
    display_name: str,
    destination: CounterpartyDestination,
    idempotency_key: str | None = None,
) -> dict:
    """Save a payee. Starts `unverified`; under require_approval_for_new_counterparties
    this may itself raise an Approval for your owner."""
    args = {"display_name": display_name, "destination": destination.model_dump(exclude_none=True)}

    async def body(session, principal):
        counterparty = await counterparties_service.create_counterparty(
            session,
            principal,
            CounterpartyCreate(display_name=display_name, destination=destination),
        )
        return {"outcome": "created", "counterparty": _dump(serialize.counterparty(counterparty))}

    return await run_tool(
        ctx, "create_counterparty", args, body, mutating=True, idempotency_key=idempotency_key
    )


@mcp.tool()
async def list_counterparties(
    ctx: Context, limit: int = 20, starting_after: str | None = None, status: str | None = None
) -> dict:
    """List saved counterparties (destination details are masked)."""
    args = {"limit": limit, "starting_after": starting_after, "status": status}

    async def body(session, principal):
        rows, has_more = await counterparties_service.list_counterparties(
            session, principal, limit=limit, starting_after=starting_after, status=status
        )
        return {
            "counterparties": [_dump(serialize.counterparty(c)) for c in rows],
            "has_more": has_more,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    return await run_tool(ctx, "list_counterparties", args, body)


@mcp.tool()
async def get_counterparty(ctx: Context, counterparty_id: str) -> dict:
    """Retrieve a counterparty by id."""

    async def body(session, principal):
        counterparty = await counterparties_service.get_counterparty(
            session, principal, counterparty_id
        )
        return {"counterparty": _dump(serialize.counterparty(counterparty))}

    return await run_tool(ctx, "get_counterparty", {"counterparty_id": counterparty_id}, body)


# ── Cards ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_cards(ctx: Context) -> dict:
    """List this agent's cards (masked — PAN/CVV never traverse MCP)."""

    async def body(session, principal):
        rows, _ = await cards_service.list_cards(session, principal, principal.agent.id)
        return {"cards": [_dump(serialize.card(c)) for c in rows]}

    return await run_tool(ctx, "list_cards", {}, body)


@mcp.tool()
async def freeze_card(ctx: Context, card_id: str, idempotency_key: str | None = None) -> dict:
    """Freeze this agent's own card. Unfreezing is owner-only — deliberately not a tool here."""

    async def body(session, principal):
        card = await cards_service.freeze_card(session, principal, card_id)
        return {"outcome": "frozen", "card": _dump(serialize.card(card))}

    return await run_tool(
        ctx, "freeze_card", {"card_id": card_id}, body, mutating=True, idempotency_key=idempotency_key
    )


# ── Approvals & activity ──────────────────────────────────────────────────


@mcp.tool()
async def list_approvals(
    ctx: Context, limit: int = 20, starting_after: str | None = None, status: str | None = None
) -> dict:
    """List approvals raised by this agent's own actions — check whether your
    payment is still waiting on the owner."""
    args = {"limit": limit, "starting_after": starting_after, "status": status}

    async def body(session, principal):
        rows, has_more = await approvals_service.list_approvals(
            session, principal, limit=limit, starting_after=starting_after, status=status
        )
        return {
            "approvals": [_dump(serialize.approval(a)) for a in rows],
            "has_more": has_more,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    return await run_tool(ctx, "list_approvals", args, body)


@mcp.tool()
async def get_approval(ctx: Context, approval_id: str) -> dict:
    """Retrieve an approval by id."""

    async def body(session, principal):
        approval = await approvals_service.get_approval(session, principal, approval_id)
        return {"approval": _dump(serialize.approval(approval))}

    return await run_tool(ctx, "get_approval", {"approval_id": approval_id}, body)


@mcp.tool()
async def list_activity(
    ctx: Context,
    limit: int = 20,
    starting_after: str | None = None,
    type: str | None = None,
) -> dict:
    """This agent's own activity feed, newest first (payments, policy evaluations, approvals…)."""
    args = {"limit": limit, "starting_after": starting_after, "type": type}

    async def body(session, principal):
        rows, has_more = await activity_service.list_events(
            session, principal, limit=limit, starting_after=starting_after, type=type
        )
        return {
            "events": [_dump(serialize.activity_event(e)) for e in rows],
            "has_more": has_more,
            "next_cursor": rows[-1].id if has_more and rows else None,
        }

    return await run_tool(ctx, "list_activity", args, body)


# ── Resources & prompts ───────────────────────────────────────────────────


@mcp.resource("policy://current")
async def policy_resource() -> str:
    """The agent's active Policy document (mirrors get_policy)."""
    ctx = mcp.get_context()
    result = await run_tool(ctx, "resource:policy://current", {}, _policy_body)
    return json.dumps(result)


async def _policy_body(session, principal):
    policy = await policies_service.get_active_policy(session, principal, principal.agent)
    return {"policy": _dump(policy)}


@mcp.resource("balance://current")
async def balance_resource() -> str:
    """Current balance snapshot (mirrors get_balance)."""
    ctx = mcp.get_context()
    result = await run_tool(ctx, "resource:balance://current", {}, _balance_body)
    return json.dumps(result)


async def _balance_body(session, principal):
    balance = await owners_service.get_agent_balance(session, principal, principal.agent.id)
    return {"balance": _dump(serialize.balance(balance))}


@mcp.prompt()
def plan_payment(counterparty: str, amount: str, currency: str) -> str:
    """Guided happy path for making a payment inside policy."""
    return (
        f"You want to pay {amount} {currency} to {counterparty}. Follow this plan:\n"
        "1. Call get_policy — check the per-transaction limit, allowlists, and approval thresholds.\n"
        "2. Call get_balance — confirm available funds cover the amount.\n"
        "3. If the destination currency differs from your balance currency, call create_quote "
        "and use the returned quote_id.\n"
        "4. Call create_payment (amount for same-currency, quote_id for cross-currency).\n"
        "5. If the outcome is `pending_approval`, your owner has been notified — poll "
        "get_approval with the approval_id; do not retry the payment.\n"
        "6. If the outcome is `policy_denied`, read the denial rule and stay within policy — "
        "you cannot widen your own limits."
    )


def create_app() -> FastAPI:
    streamable = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Enstack Agent OS MCP", lifespan=lifespan)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    app.mount("/", streamable)
    return app


app = create_app()
