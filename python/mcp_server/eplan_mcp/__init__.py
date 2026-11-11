"""
eplan_mcp - the public, versioned surface of this server.

Extensions (private tool packs loaded from EPLAN_MCP_EXTENSIONS) depend on `eplan_mcp.ext` and on
nothing else. Every other module here is internal and may change between releases.
"""

from . import ext  # noqa: F401
