from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def error_payload(status_code: int, message: str) -> dict[str, int | str]:
    return {"statusCode": status_code, "message": message}


def validation_error_message(errors: list[dict[str, Any]]) -> str:
    first = errors[0] if errors else None
    if not first:
        return "请求内容不合法"
    if first.get("type") == "extra_forbidden":
        location = first.get("loc")
        field = location[-1] if isinstance(location, tuple) and location else None
        if isinstance(field, str):
            return f"不允许提交字段：{field}"
    return str(first.get("msg", "请求内容不合法"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_payload(exc.status_code, exc.message), status_code=exc.status_code)

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return JSONResponse(error_payload(exc.status_code, message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(error_payload(400, validation_error_message(exc.errors())), status_code=400)
