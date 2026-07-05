"""MCP tool runtime: auth, audit, idempotency.

Rule zero: the MCP surface never exposes a capability the REST surface doesn't
have, and never bypasses Policy — every tool body is a thin call into the same
`enos.services` layer the REST routes use.

Every invocation writes an mcp_audit row (credential, agent, owner, tool,
arguments hash, result status, request_id) — including failures. Non-negotiable.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import Context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enos import ids
from enos.db import get_sessionmaker
from enos.models import IdempotencyKey, McpAudit
from enos.services.context import Principal
from enos.services.credentials import resolve_token
from enos.services.errors import ApiError, unauthorized


def _args_hash(tool: str, args: dict[str, Any]) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"mcp:{tool} {canonical}".encode()).hexdigest()


async def _resolve_principal(ctx: Context, session: AsyncSession) -> Principal:
    request = ctx.request_context.request
    auth_header = (request.headers.get("authorization") or "") if request else ""
    if not auth_header.lower().startswith("bearer "):
        raise unauthorized("Missing bearer token.")
    principal = await resolve_token(session, auth_header[7:].strip())
    if principal.agent is None:
        raise unauthorized("MCP requires an agent credential (ac_…), not an owner key.")
    if principal.credential.kind != "mcp":
        raise unauthorized("This credential is not of kind `mcp`.")
    return principal


async def _write_audit(
    *,
    attribution: dict[str, str] | None,
    tool: str,
    args_hash: str,
    idempotency_key: str | None,
    result_status: str,
    request_id: str,
) -> None:
    if attribution is None:  # unauthenticated call — nothing to attribute
        return
    async with get_sessionmaker()() as session:  # own session: survives rollbacks
        session.add(
            McpAudit(
                id=ids.new_id(ids.MCP_AUDIT),
                owner_id=attribution["owner_id"],
                agent_id=attribution["agent_id"],
                credential_id=attribution["credential_id"],
                tool=tool,
                args_hash=args_hash,
                idempotency_key=idempotency_key,
                result_status=result_status,
                request_id=request_id,
            )
        )
        await session.commit()


async def run_tool(
    ctx: Context,
    tool: str,
    args: dict[str, Any],
    fn: Callable[[AsyncSession, Principal], Awaitable[dict[str, Any]]],
    *,
    mutating: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Execute a tool body with auth → idempotency → audit around it."""
    request_id = ids.new_id(ids.REQUEST)
    args_hash = _args_hash(tool, args)
    key = idempotency_key or (f"mcp_{uuid4()}" if mutating else None)
    attribution: dict[str, str] | None = None
    result_status = "error"
    try:
        async with get_sessionmaker()() as session:
            try:
                principal = await _resolve_principal(ctx, session)
                # Plain-string attribution, captured before any rollback can
                # expire the ORM objects the principal holds.
                attribution = {
                    "owner_id": principal.owner.id,
                    "agent_id": principal.agent.id,
                    "credential_id": principal.credential.id,
                }
                await session.commit()  # persist last_used_at
            except ApiError as exc:
                result_status = "unauthenticated"
                return _error_payload(exc, request_id)

            if mutating and idempotency_key is not None:
                replay = await _idempotency_check(
                    session, principal.credential.id, idempotency_key, args_hash
                )
                if replay is not None:
                    result_status = "replayed" if "outcome" in replay else "conflict"
                    return {**replay, "request_id": request_id}

            try:
                result = await fn(session, principal)
                await session.commit()
                result_status = "ok"
            except ApiError as exc:
                await session.rollback()
                if exc.code == "policy_denied":
                    # A held/denied action is signal, not an error, to an agent loop.
                    result_status = "denied"
                    result = {
                        "outcome": "policy_denied",
                        "denial": {"code": exc.code, "message": exc.message, "details": exc.details},
                    }
                else:
                    result_status = "error"
                    return _error_payload(exc, request_id)

            if mutating:
                await _idempotency_store(
                    session, attribution["credential_id"], key, args_hash, result
                )
            return {**result, "request_id": request_id}
    finally:
        await _write_audit(
            attribution=attribution,
            tool=tool,
            args_hash=args_hash,
            idempotency_key=key,
            result_status=result_status,
            request_id=request_id,
        )


def _error_payload(exc: ApiError, request_id: str) -> dict[str, Any]:
    return {
        "outcome": "error",
        "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        "request_id": request_id,
    }


async def _idempotency_check(
    session: AsyncSession, credential_id: str, key: str, args_hash: str
) -> dict[str, Any] | None:
    existing = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.credential_id == credential_id, IdempotencyKey.key == key
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.request_hash != args_hash:
        return {
            "error": {
                "code": "idempotency_conflict",
                "message": "idempotency_key was already used with different arguments.",
            }
        }
    return existing.response_body or {}


async def _idempotency_store(
    session: AsyncSession, credential_id: str, key: str, args_hash: str, result: dict[str, Any]
) -> None:
    session.add(
        IdempotencyKey(
            id=ids.new_id(ids.IDEMPOTENCY),
            credential_id=credential_id,
            key=key,
            request_hash=args_hash,
            response_status=200,
            response_body=json.loads(json.dumps(result, default=str)),
        )
    )
    await session.commit()
