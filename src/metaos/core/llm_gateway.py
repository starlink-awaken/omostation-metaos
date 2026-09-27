"""MetaOS → aetherforge 门面的唯一连接点(地址 + 密钥 + 默认别名)。

此前 m_layer / workflow_planner 各写一份, 且沿用 Ollama 协议习惯:
  - 探测 /api/tags(门面没有这个路由) → 判定"不可用" → 静默落到 Mock / 启发式
  - base_url 已带 /v1 又拼 /v1/chat/completions → /v1/v1 → 404
  - 不带鉴权 → 门面对 /v1/* 一律 401
解析顺序:
  地址  LLM_GATEWAY_URL → AETHERFORGE_URL → http://127.0.0.1:4000(返回值不带 /v1)
  密钥  LLM_GATEWAY_KEY → AETHERFORGE_API_KEY → macOS Keychain(aetherforge-gateway)
"""

from __future__ import annotations

import functools
import os
import subprocess

DEFAULT_URL = "http://127.0.0.1:4000"
# 门面别名(aetherforge aliases.yaml)
DEFAULT_MODEL = "fast"


def root(url: str | None = None) -> str:
    """门面根地址(去掉结尾 /v1), 调用方自行拼 /v1/chat/completions 或 /health。"""
    raw = url or os.environ.get("LLM_GATEWAY_URL") or os.environ.get("AETHERFORGE_URL") or DEFAULT_URL
    raw = raw.rstrip("/")
    return raw[: -len("/v1")] if raw.endswith("/v1") else raw


@functools.lru_cache(maxsize=1)
def _keychain_key() -> str:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "aetherforge-gateway", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def key() -> str:
    for name in ("LLM_GATEWAY_KEY", "AETHERFORGE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    return _keychain_key()


def auth_headers() -> dict[str, str]:
    k = key()
    return {"Authorization": f"Bearer {k}"} if k else {}
