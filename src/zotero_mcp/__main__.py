"""Run the Zotero MCP server on stdio."""

from __future__ import annotations

import logging
import os
import sys

from zotero_mcp.server import mcp


def log_level(value: str | None) -> int:
    """Read LOG_LEVEL in any letter case. An unknown level means INFO."""
    level = logging.getLevelName((value or "INFO").strip().upper())
    return level if isinstance(level, int) else logging.INFO


def main() -> None:
    """Speak MCP on stdin and stdout. Logs stay on stderr."""
    # force=True replaces the handler the MCP SDK installs when the server is created.
    logging.basicConfig(
        level=log_level(os.environ.get("LOG_LEVEL")),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
