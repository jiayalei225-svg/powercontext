"""对外错误契约。

HTTP 层把 :class:`ApiError` 翻译成 ``{"error": <code>, "detail": <detail>}``。
错误码是稳定契约，客户端依赖它做分支处理。
"""

from __future__ import annotations


class ApiError(Exception):
    """可返回给客户端的业务错误。"""

    def __init__(self, code: str, detail: str, status: int = 400) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status

    def to_payload(self) -> dict[str, str]:
        return {"error": self.code, "detail": self.detail}


class InvalidPageSize(ApiError):
    def __init__(self, limit: int, detail: str | None = None) -> None:
        super().__init__(
            "invalid_page_size",
            detail or f"page_size 必须在 1..{limit} 之间",
        )
