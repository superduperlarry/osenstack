# osenstack

**Enstack Agent OS — payments backend.** Give your AI agents real money — and
real control.

This is the Phase 0 sandbox backend: a verified **Owner** provisions
**Agents** (AI sub-principals) that hold a Balance, spend, and receive — all
inside an Owner-defined **Policy** (limits, allowlists, human-in-the-loop
approvals, full audit). ENOS applications such as **ENOS One**
([`Enosone`](https://github.com/superduperlarry/Enosone)) are built on top of
this backend.

## What's here

One codebase, one image, three roles:

| Role | What it serves |
| --- | --- |
| `api` | The `/v1` REST surface — [docs/agent_os_openapi.yaml](docs/agent_os_openapi.yaml) is the contract; CI fails on drift. |
| `mcp` | The agent-facing MCP server — 19 audited tools ([catalog](docs/AGENT_OS_MCP_TOOL_CATALOG.md)), one policy engine, two doors. |
| `worker` | Celery jobs (approval expiry). |

Core guarantees (enforced structurally, tested, and checked in CI — see
[CLAUDE.md](CLAUDE.md) for the full list):

- **Decimal-only money** — `NUMERIC` in Postgres, decimal strings on the wire.
- **Append-only double-entry ledger and audit** — UPDATE/DELETE rejected by
  database triggers; every journal sums to zero.
- **Approvals are 202s, not errors** — over-policy actions are held for the
  owner, never failed.
- **Registry-driven providers** — card/banking/routing integrations are
  swappable adapters; Phase 0 ships sandbox stubs only.
- **Tenant isolation and structural attribution** on every query and event.

## Quickstart

```
uv sync                                # install deps (Python 3.12)
docker compose up -d                   # postgres, redis, rabbitmq, api, mcp, worker
uv run python scripts/seed_sandbox.py  # sandbox owner + ok_test_ key (printed once)
uv run pytest                          # test suite — no Docker needed (embedded Postgres)
uv run python scripts/spec_diff.py     # spec round-trip check
```

API on `:8000`, MCP (streamable HTTP) on `:8001/mcp`. Authenticate with
`Authorization: Bearer <ok_… | ac_…>`; every mutating request needs an
`Idempotency-Key` header.

## Layout

`src/enos/` — `models/` (SQLAlchemy) · `schemas/` (Pydantic, mirror the spec)
· `services/` (shared internal layer; REST and MCP both call it) ·
`policy/engine.py` (pure `evaluate()` → allow | hold | deny) ·
`ledger/posting.py` (double-entry) · `providers/` (registry + sandbox stubs) ·
`api/` · `mcp/` · `worker/`.

Status: **Phase 0 sandbox** — sandbox provider adapters only; real
integrations, webhook delivery, and frontends land in later phases.
