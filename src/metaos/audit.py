"""audit.py — metaos AppendOnlyLog 包装 (B-2 P0 跨仓 SSOT).

B-2 P0 接入: 从 omo._shared.append_only_log 复制 (Round 24 P0 实质化).
跨仓 SSOT: §12.1.1 不变量.

实现差异:
  - metaos 不依赖 omo (独立 monorepo), 所以本地 copy 一份
  - metaos 数据持久化走 SQLite (D Layer), 不是 jsonl;
    AppendOnlyLog 用作 audit trail 层 (新增), 不替换主存储
  - 写点:
      - d_layer.append_trace_log: 资产溯源事件 (POST 写审计轨)
      - task_manager.create_task/update_task: A2A 任务状态变更 (POST 写审计轨)
  - 锁策略: 跨进程走 fcntl, 单进程走 threading.Lock
"""

from __future__ import annotations

# ruff: noqa: UP035, N801, UP037
# 与 omo._shared.append_only_log 保持一致 (跨仓 SSOT 跨仓一致性).
# UP035: typing.ContextManager (deprecated by PEP 585, but omo 同款未修)
# N801:  fcntl_lock 命名与 omo 一致 (lowercase_with_underscores)
# UP037: 引号 type annotation (Python 3.7+ 兼容保留)
import json
import os
import threading
from pathlib import Path
from typing import Any, ContextManager


class fcntl_lock:
    """POSIX 文件锁 — 跨进程安全.

    用法:
        log = AppendOnlyLog(path, lock=fcntl_lock(path.with_suffix(".lock")))
        # 跨 2 进程并发 100 次 append, 0 交错, 0 丢行
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    def __enter__(self) -> "fcntl_lock":
        import fcntl  # POSIX-only; 延迟 import
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fd is not None:
            import fcntl
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


class AppendOnlyLog:
    """Append-only JSONL log — 跨仓物理 SSOT (§12.1.1)."""

    def __init__(
        self,
        path: Path,
        *,
        lock: ContextManager | None = None,
    ) -> None:
        self.path = Path(path)
        self._lock = lock if lock is not None else threading.Lock()

    def append(
        self,
        record: dict[str, Any] | Any,
        *,
        schema: type | None = None,
        **json_kwargs: Any,
    ) -> dict[str, Any]:
        """追加一条 record.

        Args:
            record: dict 或 Pydantic BaseModel 实例 (自动 model_dump).
            schema: 可选 Pydantic BaseModel class. 写前 model_validate 校验.
            **json_kwargs: 透传给 json.dumps (e.g. sort_keys=True).
        """
        if hasattr(record, "model_dump") and callable(getattr(record, "model_dump", None)):
            record = record.model_dump()

        if schema is not None:
            schema.model_validate(record)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # §12.1.4 跨仓 4 不变量: sort_keys=True 保 SSOT 跨仓顺序确定性
        kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
        kwargs.update(json_kwargs)
        line = json.dumps(record, **kwargs)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        return record

    def read_all(self) -> list[dict[str, Any]]:
        """读所有 records (容错: 错行保留为 {"raw": ...})."""
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line[:200]})
        return out

    def tail(self, n: int) -> list[dict[str, Any]]:
        """读最近 N 条 records."""
        if n <= 0 or not self.path.exists():
            return []
        return self.read_all()[-n:]

    def since(self, ts: str, *, field: str = "ts") -> list[dict[str, Any]]:
        """过滤 field >= ts 的 records."""
        return [r for r in self.read_all() if r.get(field, "") >= ts]

    def clear(self) -> int:
        """原子清空文件. 返回清空前 records 数."""
        if not self.path.exists():
            return 0
        n = len(self.read_all())
        self.path.write_text("", encoding="utf-8")
        return n

    def rotate(self, max_bytes: int) -> bool:
        """文件 > max_bytes 时 rename 到 .1 备份."""
        if max_bytes <= 0 or not self.path.exists():
            return False
        size = self.path.stat().st_size
        if size < max_bytes:
            return False
        backup = self.path.with_suffix(self.path.suffix + ".1")
        backup.unlink(missing_ok=True)
        self.path.rename(backup)
        return True

    def group_by(self, field: str, *, path: Path | None = None) -> dict[str, int]:
        """按 field 分组统计 record 数."""
        log = AppendOnlyLog(path) if path is not None else self
        from collections import defaultdict
        counter: dict[str, int] = defaultdict(int)
        for r in log.read_all():
            v = r.get(field, "<missing>")
            counter[str(v)] += 1
        return dict(counter)


def audit_log(audit_dir: Path, prefix: str) -> AppendOnlyLog:
    """构造 ISO-week 文件名 (B-2: 与 omo 一致的 helper)."""
    from datetime import UTC, datetime

    d = datetime.now(UTC)
    iso_year, iso_week, _ = d.isocalendar()
    fname = f"{prefix}-{iso_year}-W{iso_week:02d}.jsonl"
    return AppendOnlyLog(
        audit_dir / fname,
        lock=fcntl_lock((audit_dir / fname).with_suffix(".lock")),
    )


__all__ = ("AppendOnlyLog", "fcntl_lock", "audit_log")
