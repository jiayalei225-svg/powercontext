"""任务状态层（PowerContext）。

任务进展与验证结果不落在本地文件，而是写入 PowerContext 的 **Atomic Memory**：

- 先建立（或复用）一个工程项目专属 Scope；
- 每次保存写入一条 ``kind="state"`` 的 Memory，正文是带 ``seq`` 的 JSON 快照；
- 读取时取该任务 ``seq`` 最大的一条。

因此"重启上下文模块"之后，新进程重新查询 PowerContext 就能拿到上次的进展，
不依赖任何进程内变量。Scope ID 缓存在 ``.data/state/scope.json``，不重复建 Scope。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_PREFIX = "SDDCTX-TASK-STATE v1 "
DEFAULT_SCOPE_TITLE = "sddctx-engineering-context"


class StateUnavailable(RuntimeError):
    """PowerContext Server 不可达或返回错误。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:  # 已有事件循环在跑（被别的框架调用）
        raise StateUnavailable(
            "检测到正在运行的事件循环，无法在同步入口里调用 PowerContext；"
            "请通过 CLI 使用状态功能"
        ) from exc


class PowerContextState:
    """任务状态的读写门面。"""

    backend_name = "powercontext"

    def __init__(
        self,
        base_url: str,
        data_dir: str | Path,
        *,
        scope_title: str = DEFAULT_SCOPE_TITLE,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.scope_title = scope_title
        self.timeout = timeout
        self._scope_file = self.data_dir / "scope.json"
        self._scope_id: str | None = None

    # ------------------------------------------------------------------ 客户端

    def _client(self):
        try:
            from powercontext.client import PowerContextClient
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确指引
            raise StateUnavailable(
                "未安装 powercontext，请执行 pip install 'powercontext[cli,server]==1.4.1'"
            ) from exc
        return PowerContextClient(
            self.base_url, timeout=self.timeout, allow_insecure_http=True
        )

    def health(self) -> dict[str, Any]:
        async def probe():
            client = self._client()
            try:
                return await client.get_liveness()
            finally:
                await client.aclose()

        try:
            result = _run(probe())
            return {"ok": True, "detail": result.model_dump(mode="json") if hasattr(result, "model_dump") else str(result)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ Scope

    def ensure_scope(self) -> str:
        if self._scope_id:
            return self._scope_id
        if self._scope_file.exists():
            cached = json.loads(self._scope_file.read_text(encoding="utf-8"))
            if cached.get("base_url") == self.base_url and cached.get("scope_id"):
                self._scope_id = str(cached["scope_id"])
                return self._scope_id
        scope_id = self._create_scope()
        self._scope_file.write_text(
            json.dumps({"base_url": self.base_url, "scope_id": scope_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._scope_id = scope_id
        return scope_id

    def _create_scope(self) -> str:
        async def create():
            from powercontext.http._generated.models import CreateScopeRequest

            client = self._client()
            try:
                scope = await client.create_scope(
                    CreateScopeRequest(
                        title=self.scope_title,
                        summary="SDD 上下文模块：工程资料索引与任务进展（sddctx）",
                        idempotency_key="sddctx-scope-v1",
                    )
                )
                return scope.scope_id
            finally:
                await client.aclose()

        try:
            return _run(create())
        except Exception as exc:  # noqa: BLE001
            raise StateUnavailable(
                f"无法在 {self.base_url} 创建 PowerContext Scope：{type(exc).__name__}: {exc}。"
                "请先启动 Server：python scripts/run_powercontext.py"
            ) from exc

    # ------------------------------------------------------------------ 读写

    def save(self, task_id: str, record: dict[str, Any], *, reason: str = "sddctx save") -> dict[str, Any]:
        scope_id = self.ensure_scope()
        previous = self.load(task_id) or {}
        seq = int(previous.get("seq", 0)) + 1
        snapshot = {
            **record,
            "task_id": task_id,
            "seq": seq,
            "updated_at": _now(),
            "previous_seq": previous.get("seq"),
        }
        text = STATE_PREFIX + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

        async def write():
            from powercontext.http._generated.models import RememberMemoryRequest

            client = self._client()
            try:
                response = await client.remember_memory(
                    RememberMemoryRequest(scope_id=scope_id, kind="state", text=text, reason=reason)
                )
                return response
            finally:
                await client.aclose()

        try:
            response = _run(write())
        except Exception as exc:  # noqa: BLE001
            raise StateUnavailable(
                f"写入 PowerContext 失败：{type(exc).__name__}: {exc}"
            ) from exc

        artifact_id = None
        if getattr(response, "records", None):
            artifact = getattr(response.records[0], "artifact", None)
            artifact_id = getattr(artifact, "artifact_id", None)

        snapshot["artifact_id"] = artifact_id
        snapshot["scope_id"] = scope_id
        return snapshot

    def load(self, task_id: str) -> dict[str, Any] | None:
        scope_id = self.ensure_scope()

        async def read():
            from powercontext.http._generated.models import ListMemoryEntriesRequest

            client = self._client()
            entries: list[Any] = []
            try:
                cursor = None
                for _ in range(10):  # 最多翻 10 页，足够覆盖单个工程的任务状态量
                    page = await client.list_memory_entries(
                        ListMemoryEntriesRequest(scope_id=scope_id, limit=100, cursor=cursor)
                    )
                    entries.extend(getattr(page, "entries", []) or [])
                    cursor = getattr(page, "next_cursor", None)
                    if not cursor:
                        break
            finally:
                await client.aclose()
            return entries

        try:
            entries = _run(read())
        except Exception as exc:  # noqa: BLE001
            raise StateUnavailable(
                f"读取 PowerContext 失败：{type(exc).__name__}: {exc}"
            ) from exc

        best: dict[str, Any] | None = None
        for entry in entries:
            text = getattr(entry, "text", "") or ""
            if not text.startswith(STATE_PREFIX):
                continue
            try:
                payload = json.loads(text[len(STATE_PREFIX) :])
            except json.JSONDecodeError:
                continue
            if payload.get("task_id") != task_id:
                continue
            if best is None or int(payload.get("seq", 0)) > int(best.get("seq", 0)):
                best = payload
                artifact = getattr(entry, "artifact", None)
                if artifact is not None:
                    best["artifact_id"] = getattr(artifact, "artifact_id", None)
                    best["revision"] = getattr(artifact, "revision", None)
        return best

    def record_verification(
        self,
        task_id: str,
        *,
        name: str,
        command: str,
        exit_code: int,
        passed: bool,
        detail: str = "",
    ) -> dict[str, Any]:
        """把一条验证结果追加进任务状态。"""
        record = self.load(task_id) or {
            "task_id": task_id,
            "seq": 0,
            "done": [],
            "pending": [],
            "verifications": [],
        }
        verifications = list(record.get("verifications") or [])
        verifications.append(
            {
                "name": name,
                "command": command,
                "exit_code": exit_code,
                "passed": passed,
                "detail": detail,
                "at": _now(),
            }
        )
        record["verifications"] = verifications
        return self.save(task_id, record, reason=f"verification:{name}")
