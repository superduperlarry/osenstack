# Test suite

Runs against a **real Postgres** — numeric money, the append-only triggers,
and idempotency semantics are meaningless on SQLite.

Database resolution (see `conftest.py`):

1. If `ENOS_DATABASE_URL` is set (CI service container, or the docker-compose
   Postgres: `postgresql+asyncpg://enos:enos@localhost:5432/enos`), tests use it.
   **The schema is dropped and rebuilt** by the real Alembic migration each
   session — never point this at a database you care about.
2. Otherwise an embedded PostgreSQL 16 boots automatically via `pgserver`
   (a dev dependency) under `.local-postgres/`. No Docker needed.

```
uv run pytest            # everything
uv run pytest tests/test_policy_engine.py   # pure engine tests, no HTTP
```

Coverage map: idempotency replay/conflict (`test_idempotency.py`), policy
allow/hold/deny at engine and API level (`test_policy_engine.py`,
`test_payments_policy.py`), double-entry invariants and append-only triggers
(`test_ledger.py`), approval approve/reject/expire (`test_approvals.py`),
auth + tenant isolation (`test_auth_tenancy.py`), the 19-tool MCP surface and
mcp_audit (`test_mcp.py`), and the spec round-trip (`test_spec_roundtrip.py`).
