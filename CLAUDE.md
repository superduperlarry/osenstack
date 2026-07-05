# Enstack Agent OS — Phase 0 Sandbox

FastAPI `/v1` service, MCP server, and Postgres ledger for the Enstack Agent OS
sandbox. One codebase, one image, three roles: `api` | `mcp` | `worker`.

## The contract

- [docs/agent_os_openapi.yaml](docs/agent_os_openapi.yaml) — **the spec is the contract.**
  The FastAPI-generated schema must stay in semantic parity with it;
  `scripts/spec_diff.py` (run in CI and as a pytest test) fails the build on drift.
- [docs/AGENT_OS_MCP_TOOL_CATALOG.md](docs/AGENT_OS_MCP_TOOL_CATALOG.md) — the 19 agent-scoped
  MCP tools. Rule zero: the MCP surface never exposes a capability REST doesn't
  have, and never bypasses Policy.
- [docs/HANDOFF_Enstack_Agent_OS_Session.md](docs/HANDOFF_Enstack_Agent_OS_Session.md) — session
  context and open decision gates.

## Binding constraints (violations are rejected changes)

1. **Decimal-only money.** `decimal.Decimal` in Python, `NUMERIC` in Postgres,
   decimal strings on the wire. A `float` anywhere in money math fails CI.
2. **Append-only ledger and audit.** `ledger_entries`, `activity_events`, and
   `mcp_audit` reject UPDATE/DELETE at the database level (triggers). Ledger is
   double-entry: every journal sums to zero per currency.
3. **Registry-driven providers.** All card/banking/routing integrations go
   through `enos.providers.registry`. A hardcoded provider conditional
   (`if issuer == "banki":`) anywhere outside `src/enos/providers/` is a
   rejected change; CI greps for it.
4. **Tenant isolation on every query.** Every tenant-owned table carries
   `owner_id`; every service-layer query filters by the authenticated owner
   (and by agent for `ac_` credentials). No cross-owner reads, ever.
5. **Policies are versioned and immutable.** PUT replaces whole; each PUT is a
   new row. Version 0 = default deny-all.
6. **Approvals are 202s, not errors.** A policy hold returns the held object
   with `pending_approval` status and a created Approval.
7. **Attribution is structural.** `credential_id` on every Payment; `agent_id`
   + `credential_id` on every ActivityEvent and mcp_audit row.
8. **Customer-safe vocabulary** in anything externally visible: "Balance",
   "Enstack Routing", rail names. Never "stablecoin/USDC/onchain/OSN".

## Out of scope for Phase 0

Real provider integrations (sandbox stub adapters only), crypto module,
Terraform, frontends, webhook **delivery** (we emit ActivityEvents and manage
endpoints; delivery machinery comes later).

## Dev commands

```
uv sync                                # install deps
docker compose up -d                   # postgres, redis, rabbitmq, api, mcp, worker
uv run alembic upgrade head            # migrate (compose api does this on start)
uv run python scripts/seed_sandbox.py  # bootstrap sandbox owner + ok_test_ key
uv run pytest                          # test suite (needs Postgres; see tests/README)
uv run python scripts/spec_diff.py     # spec round-trip check
```

## Layout

`src/enos/` — `models/` (SQLAlchemy), `schemas/` (Pydantic v2, mirror the spec
exactly), `services/` (shared internal layer — both API routes and MCP tools
call this, never each other), `policy/engine.py` (pure `evaluate()`),
`ledger/posting.py` (double-entry), `providers/` (registry + sandbox stubs),
`api/`, `mcp/`, `worker/` (the three roles).
