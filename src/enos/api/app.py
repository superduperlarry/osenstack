"""enos-api role: the /v1 REST surface."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from enos.api.envelope import envelope
from enos.api.middleware import AuthMiddleware, IdempotencyMiddleware, RequestIdMiddleware
from enos.api.routes import (
    activity,
    agents,
    approvals,
    balances_transfers,
    cards,
    counterparties,
    credentials,
    owner,
    payments,
    policies,
    quotes,
    virtual_accounts,
    webhooks,
)
from enos.services.errors import ApiError

_STATUS_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Enstack Agent OS API",
        version="1.0.0-draft.1",
        summary="Give your AI agents real money — and real control.",
        contact={"name": "Enstack Agent OS", "email": "hello@enosone.com"},
        servers=[
            {"url": "https://sandbox.api.enosone.com/v1", "description": "Sandbox (Phase 0)"},
            {"url": "https://api.enosone.com/v1", "description": "Production (Phase 2 GA)"},
        ],
    )

    for router in (
        owner.router,
        agents.router,
        credentials.router,
        policies.router,
        balances_transfers.router,
        quotes.router,
        payments.router,
        counterparties.router,
        cards.router,
        virtual_accounts.router,
        approvals.router,
        activity.router,
        webhooks.router,
    ):
        app.include_router(router, prefix="/v1")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return envelope(exc.status, exc.code, exc.message, exc.details, _request_id(request))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return envelope(
            400,
            "validation_error",
            "Request validation failed.",
            {"errors": exc.errors()},
            _request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        return envelope(exc.status_code, code, str(exc.detail), None, _request_id(request))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        return envelope(500, "internal_error", "Internal error.", None, _request_id(request))

    # Execution order (add_middleware is LIFO): request-id → auth → idempotency.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIdMiddleware)

    _install_custom_openapi(app)
    return app


def _install_custom_openapi(app: FastAPI) -> None:
    """Post-process the generated schema to stay in parity with the spec:

    - strip the /v1 path prefix (the server URL carries it, as in the spec)
    - drop auto-generated 422 responses and their validation schemas
    - declare the bearerAuth security scheme and global security requirement
    """
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            summary=app.summary,
            contact=app.contact,
            routes=app.routes,
            servers=app.servers,
        )
        schema["paths"] = {
            (path[3:] if path.startswith("/v1") else path): ops
            for path, ops in schema["paths"].items()
        }
        for ops in schema["paths"].values():
            for op in ops.values():
                if isinstance(op, dict):
                    op.get("responses", {}).pop("422", None)
        for name in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(name, None)
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "opaque"}
        }
        schema["security"] = [{"bearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


app = create_app()
