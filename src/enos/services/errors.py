"""Service-layer error type mapped to the standard envelope by both surfaces."""

from typing import Any


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def not_found(resource: str, resource_id: str) -> ApiError:
    return ApiError(404, "not_found", f"{resource} {resource_id} not found.")


def unauthorized(message: str = "Invalid or missing credential.") -> ApiError:
    return ApiError(401, "unauthorized", message)


def forbidden_scope(scope: str) -> ApiError:
    return ApiError(403, "insufficient_scope", f"Credential lacks required scope {scope}.")


def owner_scope_required() -> ApiError:
    return ApiError(403, "owner_scope_required", "This operation requires an owner key.")


def validation(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(400, "validation_error", message, details)
