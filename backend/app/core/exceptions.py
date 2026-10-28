"""Unified error envelope and exception hierarchy.

Every API response uses the envelope::

    {"code": 0, "message": "ok", "data": <payload>, "trace_id": "..."}

Error codes (see architecture §7.3):
  * 0      success
  * 400xx  client errors (40001 param / 40101 unauth / 40301 forbidden / 40401 not found)
  * 500xx  server errors (50001 llm timeout / 50002 embed fail / 50003 empty retrieve / 50004 citation fail)
"""
from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.utils.tracer import get_trace_id

# Version-safe 422 constant (Starlette renamed it in 1.x with a deprecation warning).
try:
    from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT as HTTP_422
except ImportError:  # pragma: no cover - older Starlette
    from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY as HTTP_422


class AppError(Exception):
    """Base application error carrying a business error code + http status."""

    code: int = 50000
    message: str = "server error"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str | None = None, data: object = None) -> None:
        self.message = message or self.message
        self.data = data
        super().__init__(self.message)


class BadRequestError(AppError):
    code = 40001
    message = "参数错误"
    http_status = status.HTTP_400_BAD_REQUEST


class UnauthorizedError(AppError):
    code = 40101
    message = "未认证或登录已失效"
    http_status = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(AppError):
    code = 40301
    message = "权限不足，无权访问该内容"
    http_status = status.HTTP_403_FORBIDDEN


class NotFoundError(AppError):
    code = 40401
    message = "资源不存在"
    http_status = status.HTTP_404_NOT_FOUND


class LLMTimeoutError(AppError):
    code = 50001
    message = "大模型调用超时"
    http_status = status.HTTP_502_BAD_GATEWAY


class EmbeddingError(AppError):
    code = 50002
    message = "向量化失败"
    http_status = status.HTTP_502_BAD_GATEWAY


class EmptyRetrieveError(AppError):
    code = 50003
    message = "未检索到相关条款"
    http_status = HTTP_422


class CitationCheckError(AppError):
    code = 50004
    message = "引用校验未通过"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR


def _envelope(code: int, message: str, data: object = None) -> dict:
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": get_trace_id(),
    }


def make_response(code: int, message: str, data: object = None, http_status: int = 200) -> JSONResponse:
    """Build a JSONResponse using the unified envelope."""
    return JSONResponse(status_code=http_status, content=_envelope(code, message, data))


def ok(data: object = None, message: str = "ok") -> JSONResponse:
    """Success envelope (code 0)."""
    return make_response(0, message, data, status.HTTP_200_OK)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return make_response(exc.code, exc.message, exc.data, exc.http_status)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic model validators put exception instances in ctx.error; raw
    # errors are not JSON serialisable and also echo submitted secrets.
    errors = [{"loc": item["loc"], "type": item["type"], "message": item["msg"]} for item in exc.errors()]
    message = errors[0]["message"].removeprefix("Value error, ") if errors else "参数校验失败"
    return make_response(40001, message, errors, HTTP_422)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return make_response(50000, "服务器内部错误", None, status.HTTP_500_INTERNAL_SERVER_ERROR)
