"""The one error shape: { code, message, details, request_id }."""

from typing import Any

from starlette.responses import JSONResponse


def envelope(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str = "",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "details": details, "request_id": request_id},
        headers=headers,
    )
