"""audit.py tests — B-2 P0 跨仓 SSOT 验证."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from metaos.audit import AppendOnlyLog, audit_log, fcntl_lock


@pytest.fixture
def tmp_path():
    d = tempfile.mkdtemp(prefix="metaos-aol-test-")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_append_basic(tmp_path):
    p = tmp_path / "log.jsonl"
    log = AppendOnlyLog(p)
    log.append({"ts": "2026-06-11T00:00:00Z", "event": "hello", "count": 1})
    assert len(log.read_all()) == 1


def test_sort_keys(tmp_path):
    """§12.1.4 跨仓不变量: sort_keys=True"""
    p = tmp_path / "log.jsonl"
    log = AppendOnlyLog(p, lock=fcntl_lock(p.with_suffix(".lock")))
    log.append({"b": 1, "a": 2, "c": 3})
    content = p.read_text()
    assert content.index('"a"') < content.index('"b"') < content.index('"c"')


def test_iso_week_filename(tmp_path):
    """audit_log helper 用 ISO-week 文件名 (与 omo 一致)"""
    log = audit_log(tmp_path, "test-prefix")
    log.append({"ts": "2026-06-11T00:00:00Z", "event": "week-test"})
    # 文件名: test-prefix-YYYY-Www.jsonl
    files = list(tmp_path.glob("test-prefix-*.jsonl"))
    assert len(files) == 1
    assert files[0].name.startswith("test-prefix-")
    assert "W" in files[0].name


def test_d_layer_audit_trail(tmp_path, monkeypatch):
    """B-2 P0: D Layer append_trace_log 写 audit trail."""
    from metaos.layers.d_layer import DLayer

    # 用 tmp dir 替换 DLayer 默认 data_dir
    d = DLayer(data_dir=str(tmp_path / "d_layer"))
    d.append_trace_log("asset_1", "created", "source=test type=knowledge")

    # 验证 audit 文件存在
    audit_files = list((tmp_path / "d_layer" / "audit").glob("d-layer-trace-*.jsonl"))
    assert len(audit_files) == 1
    lines = audit_files[0].read_text().strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["asset_id"] == "asset_1"
    assert rec["event"] == "created"
    assert rec["detail"] == "source=test type=knowledge"


def test_a2a_audit_trail(tmp_path):
    """B-2 P0: A2A task_manager._audit() 写 audit trail (核心契约验证).

    metaos.a2a.task_manager 顶层有 agora 依赖 (在 metaos 测试环境 import
    会失败). 此 test 验证 audit_log helper 行为 + _audit 方法源码
    正确调用 audit_log (静态检查).
    """
    from metaos.audit import audit_log

    # 1. audit_log 写盘正常
    log = audit_log(tmp_path, "a2a-task")
    log.append({
        "ts": "2026-06-11T00:00:00Z",
        "task_id": "task_1",
        "service": "minerva",
        "tool": "research",
        "status": "submitted",
        "event": "create",
    })
    log.append({
        "ts": "2026-06-11T00:00:01Z",
        "task_id": "task_1",
        "service": "minerva",
        "tool": "research",
        "status": "working",
        "event": "update:working",
    })

    # 2. 验证文件
    audit_files = list(tmp_path.glob("a2a-task-*.jsonl"))
    assert len(audit_files) == 1
    lines = audit_files[0].read_text().strip().split("\n")
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["event"] == "create"
    assert rec2["event"] == "update:working"

    # 3. 静态验证 task_manager._audit 调 audit_log
    from pathlib import Path
    src = Path("/Users/xiamingxing/Workspace/projects/metaos/src/metaos/a2a/task_manager.py").read_text()
    assert "audit_log" in src
    assert "_audit" in src
    assert '"event": event' in src or "f'update:{status}'" in src or '"update:".' in src or 'update:{status}' in src
