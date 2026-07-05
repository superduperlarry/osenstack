"""Cross-cutting ASGI middleware. Execution order: request-id → auth → idempotency.

These run outside the router, so they emit the error envelope directly.
"""

import hashlib
import json
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from enos import ids
from enos.api.envelope import envelope
from enos.config import get_settings
from enos.db import get_sessionmaker
from enos.models import IdempotencyKey
from enos.models.base import utcnow
from enos.services.credentials import resolve_token
from enos.services.errors import ApiError

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")
EXEMPT_PATHS = ("/healthz", "/openapi.json", "/docs", "/redoc")


def _request_id(scope: Scope) -> str:
    return scope.setdefault("state", {}).get("request_id", "")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = ids.new_id(ids.REQUEST)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode()))
            await send(message)

        await self.app(scope, receive, send_with_header)


class AuthMiddleware:
    """Resolves ok_/ac_ bearer tokens to owner vs agent scope; 401s everything else."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1"):
            return await self.app(scope, receive, send)

        request = Request(scope)
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            response = envelope(
                401, "unauthorized", "Missing bearer token.", request_id=_request_id(scope)
            )
            return await response(scope, receive, send)
        token = auth_header[7:].strip()

        try:
            async with get_sessionmaker()() as session:
                principal = await resolve_token(session, token)
                scope["state"]["auth"] = {
                    "credential_id": principal.credential.id,
                    "owner_id": principal.owner.id,
                    "agent_id": principal.agent.id if principal.agent else None,
                }
                await session.commit()  # persists last_used_at
        except ApiError as exc:
            response = envelope(
                exc.status, exc.code, exc.message, exc.details, request_id=_request_id(scope)
            )
            return await response(scope, receive, send)

        await self.app(scope, receive, send)


def _canonical_body_hash(method: str, path: str, body: bytes) -> str:
    try:
        canonical = json.dumps(json.loads(body or b"null"), sort_keys=True, separators=(",", ":"))
    except (ValueError, UnicodeDecodeError):
        canonical = body.hex()
    return hashlib.sha256(f"{method} {path} {canonical}".encode()).hexdigest()


class IdempotencyMiddleware:
    """Idempotency-Key enforcement on every mutating /v1 request.

    24h window keyed by (credential, key). Same key + same body replays the
    original response; same key + different body → 409 idempotency_conflict.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in MUTATING_METHODS
            or not scope["path"].startswith("/v1")
        ):
            return await self.app(scope, receive, send)

        request = Request(scope)
        request_id = _request_id(scope)
        key = request.headers.get("idempotency-key")
        if key is None or not (16 <= len(key) <= 128):
            response = envelope(
                400,
                "validation_error",
                "Idempotency-Key header is required on mutating requests (16–128 chars).",
                request_id=request_id,
            )
            return await response(scope, receive, send)

        credential_id = scope["state"]["auth"]["credential_id"]

        # Buffer the request body so we can hash it and still hand it downstream.
        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        request_hash = _canonical_body_hash(scope["method"], scope["path"], body)

        window_start = utcnow() - timedelta(hours=get_settings().idempotency_window_hours)
        async with get_sessionmaker()() as session:
            existing = (
                await session.execute(
                    select(IdempotencyKey).where(
                        IdempotencyKey.credential_id == credential_id,
                        IdempotencyKey.key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None and existing.created_at < window_start:
                await session.execute(
                    delete(IdempotencyKey).where(IdempotencyKey.id == existing.id)
                )
                await session.commit()
                existing = None

        if existing is not None:
            if existing.request_hash != request_hash:
                response = envelope(
                    409,
                    "idempotency_conflict",
                    "Idempotency-Key was already used with a different request body.",
                    request_id=request_id,
                )
                return await response(scope, receive, send)
            replay = envelope_replay(existing, request_id)
            return await replay(scope, receive, send)

        # Replay the buffered body downstream and capture the response.
        sent = False

        async def replay_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        status_holder: dict = {"status": 500, "body": b""}

        async def capture_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            elif message["type"] == "http.response.body":
                status_holder["body"] += message.get("body", b"")
            await send(message)

        await self.app(scope, replay_receive, capture_send)

        status = status_holder["status"]
        if status < 500:  # server faults are retryable, don't pin them
            try:
                response_body = json.loads(status_holder["body"]) if status_holder["body"] else None
            except ValueError:
                response_body = None
            async with get_sessionmaker()() as session:
                stmt = (
                    pg_insert(IdempotencyKey)
                    .values(
                        id=ids.new_id(ids.IDEMPOTENCY),
                        credential_id=credential_id,
                        key=key,
                        request_hash=request_hash,
                        response_status=status,
                        response_body=response_body,
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing(constraint="uq_idempotency_credential_key")
                )
                await session.execute(stmt)
                await session.commit()


def envelope_replay(record: IdempotencyKey, request_id: str):
    from starlette.responses import JSONResponse, Response

    if record.response_body is None:
        return Response(
            status_code=record.response_status, headers={"Idempotency-Replayed": "true"}
        )
    return JSONResponse(
        status_code=record.response_status,
        content=record.response_body,
        headers={"Idempotency-Replayed": "true"},
    )
