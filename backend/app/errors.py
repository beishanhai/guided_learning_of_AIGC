"""统一错误模型（§5.3：错误返回 code、message、request_id）。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    """无权限资源统一返回 404，避免泄露资源存在性（§5.3 / F12）。"""

    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "version_conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media"


class SemanticError(AppError):
    status_code = 422
    code = "unprocessable_entity"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class BudgetExceeded(AppError):
    status_code = 402
    code = "budget_exceeded"


class ProviderError(AppError):
    status_code = 502
    code = "upstream_provider_error"

    def __init__(self, message: str, *, retryable: bool = False, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retryable = retryable
