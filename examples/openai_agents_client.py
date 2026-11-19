"""A minimal client: ask an agent to search a local folder through this MCP server.

Setup:
    uv sync --extra examples
    export OPENAI_API_KEY=...

Run:
    uv run --extra examples python examples/openai_agents_client.py \
        --root /path/to/your/project --prompt "Where are the config files?"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from agents import Agent, Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio

# Keep the example self-contained: no OpenAI tracing dashboard is needed.
set_tracing_disabled(True)

DEFAULT_MODEL = "gpt-5.6-luna"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.getcwd(), help="Folder the server may search (default: cwd).")
    parser.add_argument("--prompt", default="List the Python files in this project.", help="Question for the agent.")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL), help="OpenAI model to use.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Search root is not a directory: {root}")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY to use this example.")

    # MCPServerStdio replaces the child's environment entirely, so forward PATH/HOME.
    # Start the server with the same Python interpreter that runs this example.
    server = MCPServerStdio(
        params={
            "command": sys.executable,
            "args": ["-m", "agentic_search_mcp"],
            "env": {
                "AGENTIC_SEARCH_ROOT": str(root),
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            },
            "cwd": str(root),
        },
        cache_tools_list=True,
        client_session_timeout_seconds=60,
    )

    async with server:
        agent = Agent(
            name="repo-searcher",
            instructions=(
                "Search the codebase with the read, glob and grep tools. "
                "Use glob to confirm exact paths before reading, then grep to find matches "
                "and read to inspect files. Always cite file paths and line numbers."
            ),
            mcp_servers=[server],
            model=args.model,
        )
        result = await Runner.run(agent, args.prompt)

    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
