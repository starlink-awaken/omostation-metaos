"""MCP request parsing shared by capability validation and provider adapters."""

from __future__ import annotations

from collections.abc import Iterable


def parse_mcp_requests(requested: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Parse `mcp:server` and `mcp:server:tool` requests.

    A server-only request is represented by `*` and is intentionally broader
    than tool-specific requests. The output is stable and de-duplicated.
    """
    policy: dict[str, list[str]] = {}
    for item in requested:
        if not item.startswith("mcp:"):
            continue
        body = item.removeprefix("mcp:")
        server, separator, tool = body.partition(":")
        server = server.strip()
        tool = tool.strip()
        if not server or (separator and not tool):
            raise ValueError(f"Invalid MCP request: {item!r}")
        allowed = policy.setdefault(server, [])
        value = tool if separator else "*"
        if value not in allowed:
            allowed.append(value)
    return {server: tuple(tools) for server, tools in policy.items()}


def requested_mcp_servers(requested: Iterable[str]) -> tuple[str, ...]:
    return tuple(parse_mcp_requests(requested))


def requested_mcp_tools(requested: Iterable[str]) -> dict[str, tuple[str, ...]]:
    return parse_mcp_requests(requested)
