#!/usr/bin/env python3
"""MetaOS MCP Server — 多 session 隔离版 (B-03 修复)

!! 此独立入口已弃用 (deprecated) !!
请使用 bos://ecos/workflow 通过 Agora 路由调用。
参见: skills/workflow-orchestration-convergence/SKILL.md
"""

import contextlib
import io
import json
import logging
import secrets
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from metaos.cli import CLI  # type: ignore[import-not-found]

ENGINE_DIR = Path(__file__).parent.resolve()
from metaos.cli.ssot_scan import scan_ssot  # type: ignore[import-not-found]
from metaos.core.engine import SEngine  # type: ignore[import-not-found]

_DATA_DIR = str(Path.home() / ".metaos" / "data")
_lock = threading.Lock()
_sessions: dict[str, dict] = {}


def _create_session() -> dict:
    """创建独立 session：每个 MCP 连接自己的 H + token"""
    engine = SEngine(data_dir=_DATA_DIR)
    sid = secrets.token_hex(8)
    token = engine.register_h(f"mcp_{sid}", "MCP User")
    engine.authenticate(token)
    cli = CLI(engine)
    entry = {
        "engine": engine,
        "cli": cli,
        "token": token,
        "h_id": engine._current_h_id,
        "sid": sid,
        "created_at": datetime.now(),
    }
    with _lock:
        _sessions[sid] = entry
    return entry


def _get_session(sid: str = "") -> dict:
    with _lock:
        if sid and sid in _sessions:
            return _sessions[sid]
    return _create_session()


def _silent_call(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def recommend_device_for_task(task: str, devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the best available device for a task."""
    task_text = (task or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for device in devices:
        if str(device.get("status", "online")).lower() not in {"online", "ready"}:
            continue
        capabilities = {str(item).lower() for item in device.get("capabilities", [])}
        kind = str(device.get("kind", "")).lower()
        score = 0
        if any(word in task_text for word in ("code", "编码", "调试", "debug")):
            if "code" in capabilities:
                score += 8
            if "multi_window" in capabilities:
                score += 4
            if "long_running_tasks" in capabilities:
                score += 3
            if kind == "desktop":
                score += 5
        if any(word in task_text for word in ("chat", "消息", "通知", "reminder")):
            if kind == "mobile":
                score += 5
            if "chat" in capabilities:
                score += 3
        if any(word in task_text for word in ("meeting", "演示", "presentation")) and "camera" in capabilities:
            score += 4
        scored.append((score, device))
    if not scored:
        return {"id": "unassigned", "status": "no_device_available"}
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    best = dict(scored[0][1])
    best["score"] = scored[0][0]
    return best


def build_family_brief(events: list[dict[str, Any]], reminders: list[str] | None = None) -> dict[str, Any]:
    """Build a short family agenda with alerts for near-term birthdays."""
    today = datetime.now().date()
    agenda = sorted(events, key=lambda item: str(item.get("date", "")))
    alerts: list[str] = []
    for event in agenda:
        raw_date = str(event.get("date", ""))
        try:
            event_date = datetime.fromisoformat(raw_date).date()
        except ValueError:
            continue
        days_until = (event_date - today).days
        title = str(event.get("title", ""))
        if 0 <= days_until <= 7 and "生日" in title:
            alerts.append(f"{title} 将在 {days_until} 天后到来")
    return {
        "generated_at": datetime.now().isoformat(),
        "agenda": agenda,
        "alerts": alerts,
        "reminders": reminders or [],
    }


# ── MCP 协议 ──


def jsonrpc_result(result: Any, _id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def jsonrpc_error(code: int, message: str, _id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": _id, "error": {"code": code, "message": message}}


# ── 工具定义 ──

TOOLS = [
    {
        "name": "metaos_morning",
        "description": "晨间仪式 — 启动今日认知聚焦",
        "inputSchema": {
            "type": "object",
            "properties": {"input": {"type": "string", "description": "晨间引导语（可选）", "default": ""}},
        },
    },
    {
        "name": "metaos_evening",
        "description": "晚间整合 — 回顾认知收获",
        "inputSchema": {
            "type": "object",
            "properties": {"input": {"type": "string", "description": "晚间引导语（可选）", "default": ""}},
        },
    },
    {
        "name": "metaos_review",
        "description": "微粒复盘 — 归因分析",
        "inputSchema": {
            "type": "object",
            "properties": {"action": {"type": "string"}, "expected": {"type": "string"}, "actual": {"type": "string"}},
            "required": ["action", "expected", "actual"],
        },
    },
    {
        "name": "metaos_gate",
        "description": "决策门控 — 绿/黄/红灯判定",
        "inputSchema": {"type": "object", "properties": {"decision": {"type": "string"}}, "required": ["decision"]},
    },
    {"name": "metaos_status", "description": "体系健康度", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "metaos_day",
        "description": "启动指南日课 (1-7)",
        "inputSchema": {
            "type": "object",
            "properties": {"day": {"type": "number", "minimum": 1, "maximum": 7}},
            "required": ["day"],
        },
    },
    {
        "name": "metaos_trace",
        "description": "最近决策日志",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "number", "default": 10}}},
    },
    {
        "name": "metaos_ssot",
        "description": "SSOT 覆盖扫描",
        "inputSchema": {"type": "object", "properties": {"verbose": {"type": "boolean", "default": False}}},
    },
    {"name": "metaos_health", "description": "全链路健康检查", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "metaos_device_orchestrator",
        "description": "按任务形态推荐最合适的设备或执行位",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "任务描述"},
                "devices": {"type": "array", "items": {"type": "object"}, "description": "候选设备清单"},
            },
            "required": ["task", "devices"],
        },
    },
    {
        "name": "metaos_family_brief",
        "description": "生成家庭协同简报：agenda、alerts、reminders",
        "inputSchema": {
            "type": "object",
            "properties": {
                "events": {"type": "array", "items": {"type": "object"}, "description": "家庭事件列表"},
                "reminders": {"type": "array", "items": {"type": "string"}, "description": "提醒事项"},
            },
            "required": ["events"],
        },
    },
]


# ── 工具执行（各 handler 从 session 获取 engine/cli）──

TOOL_HANDLERS = {}


def _h(name):
    """注册 handler 的装饰器"""

    def wrap(fn):
        TOOL_HANDLERS[name] = fn
        return fn

    return wrap


@_h("metaos_morning")
def handle_morning(sess, params):
    cli = sess["cli"]
    text = params.get("input", "") or "今日最值得聚焦的认知点是？"
    r = _silent_call(cli.morning, text)
    return {
        "status": r.get("status"),
        "output": r.get("output", ""),
        "level": r.get("level"),
        "backend": sess["engine"].m.backend_name,
    }


@_h("metaos_evening")
def handle_evening(sess, params):
    cli = sess["cli"]
    text = params.get("input", "") or "今日最重要的认知收获是什么？"
    r = _silent_call(cli.evening, text)
    return {"status": r.get("status"), "output": r.get("output", ""), "backend": sess["engine"].m.backend_name}


@_h("metaos_review")
def handle_review(sess, params):
    cli = sess["cli"]
    r = _silent_call(cli.review, params["action"], params["expected"], params["actual"])
    return {"status": r.get("status"), "output": r.get("output", ""), "backend": sess["engine"].m.backend_name}


@_h("metaos_gate")
def handle_gate(sess, params):
    cli = sess["cli"]
    decision = params["decision"]
    level = _silent_call(cli.gate, decision)
    labels = {"red": "🔴 红灯区", "yellow": "🟡 黄灯区", "green": "🟢 绿灯区"}
    return {
        "decision": decision,
        "level": level,
        "label": labels.get(level, "未知"),
        "backend": sess["engine"].m.backend_name,
    }


@_h("metaos_status")
def handle_status(sess, params):
    engine = sess["engine"]
    health = _silent_call(sess["cli"].status)
    ollama = engine.m.get_ollama_info()
    decisions = engine.d.get_decisions(engine._current_h_id or "", 5) if engine._current_h_id else []
    try:
        entries = scan_ssot(str(ENGINE_DIR.parent))
        total = len(entries)
        has = sum(1 for e in entries if e["ssot"])
        ssot = f"{round(has / total * 100, 1)}% ({has}/{total})"
    except Exception:  # defensive fallback  # noqa: BLE001
        ssot = "?"
    return {
        "backend": engine.m.backend_name,
        "m_pool": health.get("m_pool", "?"),
        "ollama": {"available": ollama.get("available"), "model": ollama.get("model")},
        "ssot": ssot,
        "h_id": engine._current_h_id,
        "pending": health.get("pending_reviews", 0),
        "decisions": len(decisions),
    }


@_h("metaos_day")
def handle_day(sess, params):
    cli = sess["cli"]
    day = int(params["day"])
    if day < 1 or day > 7:
        return {"error": "Day 仅支持 1-7"}
    outputs = []
    if day == 1:
        outputs.append(("晨间", _silent_call(cli.morning, "今日最值得聚焦的认知点是？").get("output", "")))
        outputs.append(("晚间", _silent_call(cli.evening, "今日最重要的认知收获是？").get("output", "")))
    elif day == 2:
        _silent_call(cli.morning, "今日焦点")
        outputs.append(("复盘", _silent_call(cli.review, "今日行动复盘", "预期", "实际").get("output", "")))
    elif day == 3:
        _silent_call(cli.morning, "今日焦点")
        outputs.append(("晨间", "完成"))
    elif day == 4:
        _silent_call(cli.morning, "今日焦点")
        outputs.append(("晚间", _silent_call(cli.evening, "帮我提炼一条原则草稿").get("output", "")))
    elif day == 5:
        _silent_call(cli.morning, "今日焦点")
    elif day == 6:
        outputs.append(("周复盘", _silent_call(cli.review, "简化周复盘", "本周预期", "本周实际").get("output", "")))
    elif day == 7:
        _silent_call(cli.morning, "今日焦点")
        outputs.append(("复盘", _silent_call(cli.evening, "系统启动复盘").get("output", "")))
    return {"day": day, "outputs": [{"step": k, "content": v[:200]} for k, v in outputs]}


@_h("metaos_trace")
def handle_trace(sess, params):
    engine = sess["engine"]
    decisions = (
        engine.d.get_decisions(engine._current_h_id or "", params.get("limit", 10)) if engine._current_h_id else []
    )
    return {
        "count": len(decisions),
        "decisions": [
            {
                "id": d.decision_id[:8],
                "time": d.timestamp.strftime("%m-%d %H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp),
                "level": d.level,
                "desc": d.description[:60],
                "pending": d.outcome_pending_review,
            }
            for d in decisions
        ],
    }


@_h("metaos_ssot")
def handle_ssot(sess, params):
    try:
        entries = scan_ssot(str(ENGINE_DIR.parent))
        total, has = len(entries), sum(1 for e in entries if e["ssot"])
        missing = [e["file"] for e in entries if not e["ssot"]]
        return {
            "total": total,
            "with_ssot": has,
            "coverage_pct": round(has / total * 100, 1) if total else 0,
            "missing": missing[:20] if params.get("verbose") else [],
        }
    except Exception as e:  # defensive fallback  # noqa: BLE001
        return {"error": str(e)}


@_h("metaos_health")
def handle_health(sess, params):
    result = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py")], capture_output=True, text=True, timeout=120, cwd=str(ENGINE_DIR)
    )
    return {"passed": result.returncode == 0, "output": result.stdout[-500:]}


@_h("metaos_device_orchestrator")
def handle_device_orchestrator(sess, params):
    recommended = recommend_device_for_task(params.get("task", ""), params.get("devices", []))
    return {
        "status": "ok",
        "task": params.get("task", ""),
        "recommended_device": recommended,
    }


@_h("metaos_family_brief")
def handle_family_brief(sess, params):
    brief = build_family_brief(params.get("events", []), params.get("reminders", []))
    return {"status": "ok", **brief}


# ── 请求处理 ──


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return jsonrpc_result(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "metaos-engine", "version": "7.1.0"},
            },
            msg_id,
        )

    elif method == "tools/list":
        return jsonrpc_result({"tools": TOOLS}, msg_id)

    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return jsonrpc_error(-32601, f"未知工具: {name}", msg_id)
        try:
            sess = _create_session()  # 每个 tools/call 独立 session
            result = handler(sess, args)
            return jsonrpc_result(
                {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}, msg_id
            )
        except Exception as e:  # defensive fallback  # noqa: BLE001
            return jsonrpc_error(-32603, f"执行失败: {e}", msg_id)

    elif method == "resources/list":
        return jsonrpc_result(
            {
                "resources": [
                    {"uri": "metaos://status", "name": "引擎状态", "description": "当前运行状态"},
                    {"uri": "metaos://ssot", "name": "SSOT 报告", "description": "文档 SSOT 覆盖率"},
                ]
            },
            msg_id,
        )

    elif method == "resources/read":
        uri = params.get("uri", "")
        sess = _create_session()
        if uri == "metaos://status":
            return jsonrpc_result(
                {"contents": [{"uri": uri, "text": json.dumps(handle_status(sess, {}), ensure_ascii=False, indent=2)}]},
                msg_id,
            )
        elif uri == "metaos://ssot":
            return jsonrpc_result(
                {
                    "contents": [
                        {
                            "uri": uri,
                            "text": json.dumps(handle_ssot(sess, {"verbose": True}), ensure_ascii=False, indent=2),
                        }
                    ]
                },
                msg_id,
            )
        return jsonrpc_error(-32602, f"未知资源: {uri}", msg_id)

    elif method == "notifications/initialized":
        return None

    return jsonrpc_error(-32601, f"未知方法: {method}", msg_id)


# ── 主循环（B-03 修复：每个 tools/call 用独立 session）──


def main():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] metaos-mcp: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("metaos.mcp")
    logger.info("MetaOS MCP 服务器启动 (多 session 隔离)")
    logger.warning("!! 此独立入口已弃用 (deprecated) !! 请使用 bos://ecos/workflow 通过 Agora 路由调用")

    buffer = ""
    for line in sys.stdin:
        buffer += line
        try:
            msg = json.loads(buffer)
            buffer = ""
        except json.JSONDecodeError:
            continue
        response = handle_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
