# agentic-search-mcp

A minimal [Model Context Protocol](https://modelcontextprotocol.io) server that gives an MCP client three filesystem tools: `read`, `glob`, and `grep`.

Every path is resolved against a single **search root**. The agent can only see files inside that root; paths that escape it (including through symlinks) are rejected. Only text files are read, and common generated directories (`.git`, `.venv`, `node_modules`, `__pycache__`, ...) are skipped during searches.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
cd agentic-search-mcp
uv sync
```

This creates a `.venv` with the server and its `mcp` dependency installed. To also install the optional dependencies for the example client, use `uv sync --extra examples`.

## Run the server

The server communicates over stdio, which is how an SDK client (such as the OpenAI Agents SDK example below) launches it. Set the folder it is allowed to search, then start it:

```bash
export AGENTIC_SEARCH_ROOT=/path/to/your/project
uv run agentic-search-mcp
```

`AGENTIC_SEARCH_ROOT` defaults to the current working directory if it is not set. One server process serves one root; start a separate server for each folder you want to expose.

## Tools

| Tool | Description | Key arguments |
| --- | --- | --- |
| `read` | Read a text file as numbered lines. | `path`, `offset=0`, `limit=2000` |
| `glob` | Match files/directories with a pathlib-style glob. | `pattern`, `path="."`, `max_results=1000` |
| `grep` | Regex (Python `re`) or literal search over file contents. | `pattern`, `path="."`, `glob_filter=None`, `literal=False`, `ignore_case=False`, `max_results=100` |

Paths may be absolute or relative to the search root. Typical calls:

- `read(path="src/main.py", offset=0, limit=100)`
- `glob(pattern="**/*.py", path="src")`
- `grep(pattern="def .*config", glob_filter="*.py", path=".")`
- `grep(pattern="TODO", literal=True, ignore_case=True, glob_filter="*.md")`

`grep` patterns use Python `re` syntax per line: `|` means "or", `.*` matches any run of characters, and `(a|b)` groups alternatives. Do not escape `|` — GNU grep's `\|` syntax is not supported. Use `literal=True` for plain text, `ignore_case=True` for case-insensitive matching, and `max_results` to cap the output. A missing `read` path returns the closest matching file names to help the agent correct itself; agents should confirm paths with `glob` before reading.

Invalid calls (missing file, directory passed to `read`, invalid regex, or a path outside the root) return readable error text so the model can retry with a corrected call.

## Example client

[`examples/openai_agents_client.py`](examples/openai_agents_client.py) is a minimal client that launches the server as a subprocess, points it at a folder, and asks an agent a question. It uses the OpenAI Agents SDK with an OpenAI model.

```bash
uv sync --extra examples
export OPENAI_API_KEY=your-api-key

uv run --extra examples python examples/openai_agents_client.py \
  --root /path/to/your/project \
  --prompt "Find where configuration is loaded"
```

The default model is `gpt-5.6-luna`; override it with `--model` or `OPENAI_MODEL`. By default the agent is asked to list the Python files in the root if no `--prompt` is given, and `--root` defaults to the current directory.

The client passes the search root to the server with `AGENTIC_SEARCH_ROOT` and forwards `PATH` and `HOME` because the SDK replaces the child's environment. `OPENAI_API_KEY` stays in the client process and is never sent to the MCP server.
