# paperclip-mcp

MCP server for the [Paperclip](https://github.com/paperclipai/paperclip) AI agent orchestration platform.

Exposes Paperclip's REST API as [Model Context Protocol](https://modelcontextprotocol.io) tools, so any MCP-compatible AI assistant (Claude, etc.) can manage issues, agents, goals, approvals, and costs through natural language.

---

## Features

| Category | Tools |
|---|---|
| **Issues** | `list_issues` · `get_issue` · `create_issue` · `update_issue` · `checkout_issue` · `release_issue` · `comment_on_issue` · `delete_issue` |
| **Agents** | `list_agents` · `get_agent` · `invoke_agent_heartbeat` |
| **Goals** | `list_goals` · `create_goal` · `update_goal` |
| **Approvals** | `list_approvals` · `approve` · `reject` · `request_approval_revision` |
| **Monitoring** | `get_cost_summary` · `get_dashboard` · `list_activity` |

---

## Requirements

- Python 3.10+
- A running [Paperclip](https://github.com/paperclipai/paperclip) instance
- Authentication — **one of**:
  - An Agent API key (Paperclip UI → Settings → API Keys), **or**
  - A browser session token (`__Secure-better-auth.session_token` cookie)

---

## Installation

### Option A — `uvx` (zero-install, recommended)

No install step needed. [`uvx`](https://docs.astral.sh/uv/) fetches and runs the latest published release on demand:

```bash
uvx paperclip-mcp --transport stdio
```

### Option B — pip / uv

```bash
pip install paperclip-mcp
# or
uv pip install paperclip-mcp
```

### Option C — from source

```bash
git clone https://github.com/elevateinformatics/paperclip-mcp
cd paperclip-mcp
pip install -e .
```

---

## Configuration

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `PAPERCLIP_COMPANY_ID` | ✅ | Company UUID from the Paperclip URL |
| `PAPERCLIP_API_KEY` | ⚠️ one-of | Bearer API key (Settings → API Keys → New Key) |
| `PAPERCLIP_SESSION_TOKEN` | ⚠️ one-of | Value of `__Secure-better-auth.session_token` cookie |
| `PAPERCLIP_BASE_URL` | ❌ | Defaults to `http://localhost:3100/api` |

Provide **either** `PAPERCLIP_API_KEY` (preferred for production) **or** `PAPERCLIP_SESSION_TOKEN` (useful when API keys are not available — uses your logged-in browser session).

### How to get a session token

1. Log in to Paperclip in Chrome/Edge
2. DevTools → Application → Cookies → pick your Paperclip domain
3. Copy the value of `__Secure-better-auth.session_token`

> **Security**: Session tokens grant full access to your user account. Treat them like passwords — never commit `.env` or share the value. They also expire and must be refreshed periodically.

### `.env` file (local dev)

```dotenv
PAPERCLIP_BASE_URL=https://elevate-ai.up.railway.app/api
PAPERCLIP_COMPANY_ID=your_company_uuid
PAPERCLIP_API_KEY=your_api_key            # OR
PAPERCLIP_SESSION_TOKEN=your_session_cookie_value
```

---

## Usage

### Start the server

```bash
# HTTP (for Claude Code / mcp-proxy) — default port 9011
paperclip-mcp

# Custom port
paperclip-mcp --port 9012

# stdio transport (for Claude Desktop)
paperclip-mcp --transport stdio

# All options
paperclip-mcp --help
```

### Register with Claude Code

```bash
# HTTP transport (persistent — survives Claude restarts)
claude mcp add paperclip --transport http http://localhost:9011/mcp

# stdio transport (Claude Desktop — add to claude_desktop_config.json)
```

#### Claude Desktop (`claude_desktop_config.json`)

Using `uvx` (no install required):

```json
{
  "mcpServers": {
    "paperclip": {
      "command": "uvx",
      "args": ["paperclip-mcp@latest", "--transport", "stdio"],
      "env": {
        "PAPERCLIP_BASE_URL": "https://your-paperclip.example.com/api",
        "PAPERCLIP_COMPANY_ID": "your_company_uuid",
        "PAPERCLIP_API_KEY": "your_api_key"
      }
    }
  }
}
```

Or with a session token instead of an API key:

```json
"env": {
  "PAPERCLIP_BASE_URL": "https://your-paperclip.example.com/api",
  "PAPERCLIP_COMPANY_ID": "your_company_uuid",
  "PAPERCLIP_SESSION_TOKEN": "your_session_cookie_value"
}
```

---

## Example interactions

Once registered, you can ask your AI assistant:

```
"What tasks does the Purchasing agent have open?"
→ calls list_issues(assignee_agent_id="...", status="todo,in_progress")

"Create a task for the CEO agent to search for new cheese suppliers in Barcelona"
→ calls create_issue(title="Search cheese suppliers in Barcelona", assignee_agent_id="...")

"Approve the pending hire request"
→ calls list_approvals(status="pending") + approve(approval_id="...")

"How much have we spent on tokens this month, broken down by agent?"
→ calls get_cost_summary()

"Wake up the Administration agent now"
→ calls invoke_agent_heartbeat(agent_id="...")
```

---

## Auto-start with the MCP stack

Add to your stack startup script:

```bash
# Check if already running
curl -s --max-time 1 http://localhost:9011/mcp > /dev/null 2>&1 || \
  nohup paperclip-mcp > /tmp/paperclip-mcp.log 2>&1 &
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Lint
ruff check src/
ruff format src/

# Type check
mypy src/

# Tests
pytest
```

---

## Architecture notes

- **Who should use this MCP**: Human operators managing agents via Claude Code or Claude Desktop.
- **Do agents need this MCP?**: No — Paperclip agents already interact with the REST API directly via HTTP in their HEARTBEAT protocol. This MCP is for the human operator layer.
- **Hermes agents**: If you switch to [Hermes](https://github.com/NousResearch/hermes-paperclip-adapter), this MCP is automatically available since Hermes supports MCP natively.
- **Transport choice**: Use `streamable-http` for Claude Code and mcp-proxy integrations. Use `stdio` for Claude Desktop.
- **Security**: The server binds to `127.0.0.1` by default (localhost only). Do not expose it publicly — it carries your Paperclip credentials.

---

## License

MIT — see [LICENSE](LICENSE).
