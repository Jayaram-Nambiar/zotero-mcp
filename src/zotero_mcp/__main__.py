"""Run the Zotero MCP server on stdio."""

from __future__ import annotations

import logging
import os
import sys

from zotero_mcp.server import mcp


def main() -> None:
    """Speak MCP on stdin and stdout. Logs stay on stderr."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
