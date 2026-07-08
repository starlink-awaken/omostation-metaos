"""Anti-corruption adapter for projects/agora (I0).

Re-exports the Agora MCP symbol used by MetaOS A2A task manager.
"""

from agora.mcp.mcp_bootstrap import get_data_dir

__all__ = [
    "get_data_dir",
]
