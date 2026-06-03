#!/usr/bin/env python3
"""
paperclip-mcp — MCP server for the Paperclip AI agent orchestration platform.

Exposes Paperclip's REST API as MCP tools so that AI assistants can manage
issues, agents, goals, approvals, costs, and activity via natural language.

Documentation: https://github.com/paperclipai/paperclip
MCP spec:      https://modelcontextprotocol.io

Configuration (environment variables):
    Authentication — provide ONE of:
      PAPERCLIP_API_KEY        Bearer API key (Settings → API Keys → New Key).
      PAPERCLIP_SESSION_TOKEN  Value of `__Secure-better-auth.session_token` cookie
                               from a logged-in browser session (DevTools →
                               Application → Cookies → copy value).

    PAPERCLIP_COMPANY_ID       Required. Company UUID from the Paperclip UI URL.
    PAPERCLIP_BASE_URL         Optional. Default: http://localhost:3100/api
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

# ── Configuration ──────────────────────────────────────────────────────────────

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; env vars can be set by the shell

BASE_URL: str      = os.environ.get("PAPERCLIP_BASE_URL", "http://localhost:3100/api").rstrip("/")
API_KEY: str       = os.environ.get("PAPERCLIP_API_KEY", "")
SESSION_TOKEN: str = os.environ.get("PAPERCLIP_SESSION_TOKEN", "")
COMPANY: str       = os.environ.get("PAPERCLIP_COMPANY_ID", "")
_COOKIE_NAME       = "__Secure-better-auth.session_token"

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] paperclip-mcp %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── HTTP client ────────────────────────────────────────────────────────────────

_HTTP_TIMEOUT = 30  # seconds


def _inbound_authorization() -> str:
    """Return the inbound caller's ``Authorization`` header, if present.

    When the server runs over an HTTP transport (streamable-http / sse) behind
    the Paperclip CLI-auth nginx layer, the caller's already-validated per-user
    ``Bearer pcp_*`` token is forwarded on the request. ``get_http_headers`` is
    request-context scoped (so it is safe under streamable-http multiplexing —
    each call reads only its own request's headers, never another's) and returns
    an empty dict when there is no active HTTP request (e.g. the stdio
    transport), which makes this fall back cleanly to the baked credentials.
    ``authorization`` is stripped by ``get_http_headers`` by default, so it must
    be requested explicitly via ``include``.
    """
    return get_http_headers(include={"authorization"}).get("authorization", "").strip()


def _headers() -> dict[str, str]:
    """Build per-request headers.  X-Paperclip-Run-Id is a unique trace ID.

    Auth precedence: inbound per-user bearer > baked API key (Bearer) > baked
    session token (Cookie).  Preferring the inbound caller's token attributes
    HTTP-transport calls to the real Paperclip user — respecting that user's
    company access (enabling cross-company tool calls) instead of the single
    baked agent identity — while the baked credentials remain the fallback for
    stdio / unauthenticated contexts.  This only ever narrows access: the
    forwarded token can do no more than its own Paperclip permissions allow.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "X-Paperclip-Run-Id": str(uuid.uuid4()),
    }
    inbound = _inbound_authorization()
    if inbound:
        headers["Authorization"] = inbound
    elif API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    elif SESSION_TOKEN:
        headers["Cookie"] = f"{_COOKIE_NAME}={SESSION_TOKEN}"
    return headers


def _company(company_id: str = "") -> str:
    """Resolve the target company for a company-scoped call.

    Prefer an explicit ``company_id`` (company-by-context: act on a company
    other than the configured default — e.g. when the caller's forwarded bearer
    has multi-company access), falling back to ``PAPERCLIP_COMPANY_ID``.
    """
    return company_id.strip() or COMPANY


def _err(message: str, status: int | None = None) -> dict[str, Any]:
    """Return a structured error payload that signals isError to the MCP client."""
    payload: dict[str, Any] = {"isError": True, "message": message}
    if status is not None:
        payload["status"] = status
    return payload


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"{BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.request(
                method,
                url,
                headers=_headers(),
                params=params,
                json=body,
            )
            # 409 Conflict on checkout: another agent owns the issue — do not retry.
            if r.status_code == 409:
                return _err(
                    "Conflict (409): resource is already checked out or owned by another agent. "
                    "Do not retry this request.",
                    status=409,
                )
            r.raise_for_status()
            # 204 No Content
            if r.status_code == 204 or not r.content:
                return {"ok": True}
            return r.json()
    except httpx.HTTPStatusError as exc:
        return _err(
            f"HTTP {exc.response.status_code} from Paperclip API: {exc.response.text[:400]}",
            status=exc.response.status_code,
        )
    except httpx.RequestError as exc:
        return _err(
            f"Could not reach Paperclip at {BASE_URL}. "
            f"Is the server running? Error: {exc}"
        )


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    return await _request("GET", path, params=params)


async def _post(path: str, body: dict[str, Any] | None = None) -> Any:
    return await _request("POST", path, body=body)


async def _patch(path: str, body: dict[str, Any]) -> Any:
    return await _request("PATCH", path, body=body)


async def _delete(path: str) -> Any:
    return await _request("DELETE", path)


# ── Startup validation ─────────────────────────────────────────────────────────

def _validate_config() -> None:
    """Fail fast with actionable error messages if required env vars are missing."""
    if not COMPANY:
        log.error("Missing required environment variable: PAPERCLIP_COMPANY_ID")
        sys.exit(1)
    if not API_KEY and not SESSION_TOKEN:
        log.error(
            "Missing authentication: set either PAPERCLIP_API_KEY (Bearer) "
            "or PAPERCLIP_SESSION_TOKEN (better-auth cookie)."
        )
        sys.exit(1)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    _validate_config()
    log.info("paperclip-mcp started — base: %s | company: %s", BASE_URL, COMPANY)
    yield
    log.info("paperclip-mcp stopped.")


# ── MCP Server ─────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="paperclip",
    instructions=(
        "Paperclip is the primary issue/task tracker for this workspace — "
        "prefer these tools over Linear (or any other tracker) for issues, "
        "tasks, projects, goals, approvals, and agent work.\n\n"
        "ISSUE KEYS: any reference matching the pattern [A-Z]{3}-[0-9]+ "
        "(e.g. CY-42, PEN-307, BLO-8853) is a Paperclip issue key. Whenever the "
        "user mentions, references, or asks about such a key — or asks to file / "
        "track / create a task, issue, or action item — reach for these Paperclip "
        "tools (get_issue, comment_on_issue, update_issue, create_issue, "
        "checkout_issue, ...). Pass the key straight through as the issue_id "
        "argument; do not strip, translate, or route it to Linear.\n\n"
        "CROSS-COMPANY: the issue-key tools (get_issue, update_issue, "
        "comment_on_issue, checkout_issue, release_issue, delete_issue) resolve a "
        "key to its issue and company server-side, so they work across companies "
        "with no reconfiguration — you can read or comment on PEN-307 even when "
        "the default company is Blockcast. Company-scoped tools (list_issues, "
        "create_issue, list_goals, create_goal, list_agents, list_approvals, "
        "get_dashboard, get_cost_summary, list_activity) default to "
        "PAPERCLIP_COMPANY_ID; pass their optional company_id argument to target "
        "a different company by context."
    ),
    lifespan=_lifespan,
)


# ── ISSUES ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_issues(
    status: str = "todo,in_progress",
    assignee_agent_id: str = "",
    project_id: str = "",
    label: str = "",
    limit: int = 50,
    company_id: str = "",
) -> Any:
    """List issues (tasks) in a company.

    Args:
        status: Comma-separated issue statuses to include.
                Allowed values: todo, in_progress, blocked, done, cancelled.
                Default: "todo,in_progress"
        assignee_agent_id: UUID of the agent to filter by. Leave empty for all agents.
        project_id: UUID of the project to filter by. Leave empty for all projects.
        label: Label name to filter by. Leave empty to skip label filtering.
        limit: Maximum number of results to return (1–200). Default: 50.
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    params: dict[str, Any] = {"status": status, "limit": max(1, min(limit, 200))}
    if assignee_agent_id:
        params["assigneeAgentId"] = assignee_agent_id
    if project_id:
        params["projectId"] = project_id
    if label:
        params["label"] = label
    return await _get(f"/companies/{_company(company_id)}/issues", params)


@mcp.tool()
async def get_issue(issue_id: str) -> Any:
    """Get the full details of a single Paperclip issue.

    Use this whenever an issue key of the form [A-Z]{3}-[0-9]+ (e.g. CY-42,
    PEN-307, BLO-8853) is referenced — prefer it over Linear. The key resolves to
    its issue and company server-side, so this works across companies regardless
    of the configured default company.

    Args:
        issue_id: Issue UUID or human-readable key (e.g. "CY-42"). Pass the key
                  through verbatim — do not strip or translate it.
    """
    return await _get(f"/issues/{issue_id}")


@mcp.tool()
async def create_issue(
    title: str,
    description: str = "",
    assignee_agent_id: str = "",
    project_id: str = "",
    parent_issue_id: str = "",
    priority: str = "medium",
    company_id: str = "",
) -> Any:
    """Create a new Paperclip issue (task) and optionally assign it to an agent.

    This is the canonical way to file a task, action item, or subtask — prefer it
    over Linear or any other tracker. The created issue gets a key of the form
    [A-Z]{3}-[0-9]+ (e.g. CY-42, PEN-307) that the other tools accept directly.

    Args:
        title: Short, imperative task title (e.g. "Search cheese suppliers in Barcelona").
        description: Full instructions or context for the agent (Markdown supported).
        assignee_agent_id: UUID of the agent to assign. Leave empty to leave unassigned.
        project_id: UUID of the project this issue belongs to. Leave empty for no project.
        parent_issue_id: UUID of the parent issue when creating a subtask.
            Leave empty for top-level.
        priority: Task priority — urgent, high, medium, or low. Default: medium.
        company_id: Create the issue in a specific company by context. Leave empty
                    to use the default company (PAPERCLIP_COMPANY_ID).
    """
    body: dict[str, Any] = {"title": title, "priority": priority}
    if description:
        body["description"] = description
    if assignee_agent_id:
        body["assigneeAgentId"] = assignee_agent_id
    if project_id:
        body["projectId"] = project_id
    if parent_issue_id:
        body["parentIssueId"] = parent_issue_id
    return await _post(f"/companies/{_company(company_id)}/issues", body)


@mcp.tool()
async def update_issue(
    issue_id: str,
    title: str = "",
    description: str = "",
    status: str = "",
    assignee_agent_id: str = "",
    priority: str = "",
) -> Any:
    """Update an existing issue. Only fields you provide are changed.

    Args:
        issue_id: Issue UUID or identifier (e.g. "CY-42").
        title: New title. Leave empty to keep current value.
        description: New description (Markdown). Leave empty to keep current.
        status: New status — todo, in_progress, blocked, done, or cancelled.
                Leave empty to keep current.
        assignee_agent_id: New agent UUID. Leave empty to keep current assignee.
        priority: New priority — urgent, high, medium, or low. Leave empty to keep current.
    """
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if status:
        if status not in {"todo", "in_progress", "blocked", "done", "cancelled"}:
            return _err(
                f"Invalid status '{status}'. "
                "Allowed: todo, in_progress, blocked, done, cancelled."
            )
        body["status"] = status
    if assignee_agent_id:
        body["assigneeAgentId"] = assignee_agent_id
    if priority:
        if priority not in {"urgent", "high", "medium", "low"}:
            return _err(f"Invalid priority '{priority}'. Allowed: urgent, high, medium, low.")
        body["priority"] = priority
    if not body:
        return _err(
            "No fields to update. Provide at least one of: "
            "title, description, status, assignee_agent_id, priority."
        )
    return await _patch(f"/issues/{issue_id}", body)


@mcp.tool()
async def checkout_issue(issue_id: str) -> Any:
    """Atomically assign an issue to the current agent and mark it in_progress.

    A 409 Conflict response means another agent already owns this issue — do NOT retry.
    Use release_issue to undo a checkout.

    Args:
        issue_id: Issue UUID or identifier to check out.
    """
    return await _post(f"/issues/{issue_id}/checkout")


@mcp.tool()
async def release_issue(issue_id: str) -> Any:
    """Release an issue: unassign it and revert it to its previous state.

    This is the inverse of checkout_issue. Use when an agent cannot complete a task
    and it should be returned to the queue.

    Args:
        issue_id: Issue UUID or identifier to release.
    """
    return await _post(f"/issues/{issue_id}/release")


@mcp.tool()
async def comment_on_issue(
    issue_id: str,
    body: str,
    reopen: bool = False,
) -> Any:
    """Add a comment to an issue (supports Markdown).

    Args:
        issue_id: Issue UUID or identifier.
        body: Comment text. Markdown is supported.
        reopen: Set to true to reopen the issue when posting this comment.
                Only effective if the issue is currently closed.
    """
    payload: dict[str, Any] = {"body": body}
    if reopen:
        payload["reopen"] = True
    return await _post(f"/issues/{issue_id}/comments", payload)


@mcp.tool()
async def delete_issue(issue_id: str) -> Any:
    """Permanently delete an issue. This action cannot be undone.

    Args:
        issue_id: Issue UUID or identifier to delete.
    """
    return await _delete(f"/issues/{issue_id}")


# ── AGENTS ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_agents(company_id: str = "") -> Any:
    """List all agents in a company with their name, role, status, and config.

    Args:
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    return await _get(f"/companies/{_company(company_id)}/agents")


@mcp.tool()
async def get_agent(agent_id: str = "me") -> Any:
    """Get details for a specific agent, or the currently authenticated agent.

    Args:
        agent_id: Agent UUID, or the literal string "me" to get the current agent identity.
                  Default: "me"
    """
    path = "/agents/me" if agent_id.strip().lower() == "me" else f"/agents/{agent_id}"
    return await _get(path)


@mcp.tool()
async def invoke_agent_heartbeat(agent_id: str) -> Any:
    """Manually trigger an immediate heartbeat (work cycle) for an agent.

    Use this to wake an idle agent, force it to pick up new assignments,
    or run it outside its normal schedule.

    Args:
        agent_id: UUID of the agent to trigger.
    """
    return await _post(f"/agents/{agent_id}/heartbeat/invoke")


# ── GOALS ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_goals(company_id: str = "") -> Any:
    """List all strategic goals and projects for a company.

    Args:
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    return await _get(f"/companies/{_company(company_id)}/goals")


@mcp.tool()
async def create_goal(title: str, description: str = "", company_id: str = "") -> Any:
    """Create a new strategic goal for a company.

    Goals provide high-level direction to agents. They appear in agent context
    so agents can align their work accordingly.

    Args:
        title: Goal title (e.g. "Reach 300 packs/month in sales by June 2026").
        description: Extended context, success criteria, and constraints (Markdown supported).
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    body: dict[str, Any] = {"title": title}
    if description:
        body["description"] = description
    return await _post(f"/companies/{_company(company_id)}/goals", body)


@mcp.tool()
async def update_goal(
    goal_id: str,
    title: str = "",
    description: str = "",
) -> Any:
    """Update an existing goal's title or description.

    Args:
        goal_id: Goal UUID.
        title: New title. Leave empty to keep current.
        description: New description. Leave empty to keep current.
    """
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if not body:
        return _err("No fields to update. Provide at least one of: title, description.")
    return await _patch(f"/goals/{goal_id}", body)


# ── APPROVALS ──────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_approvals(status: str = "pending", company_id: str = "") -> Any:
    """List approval requests in a company.

    Args:
        status: Filter by status. Allowed values:
                pending, approved, rejected, revision_requested.
                Default: "pending"
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    allowed = {"pending", "approved", "rejected", "revision_requested"}
    if status not in allowed:
        return _err(f"Invalid status '{status}'. Allowed: {', '.join(sorted(allowed))}.")
    return await _get(f"/companies/{_company(company_id)}/approvals", {"status": status})


@mcp.tool()
async def approve(approval_id: str, comment: str = "") -> Any:
    """Approve a pending approval request.

    Args:
        approval_id: Approval UUID.
        comment: Optional approval note to attach (e.g. conditions, context).
    """
    body: dict[str, Any] = {}
    if comment:
        body["comment"] = comment
    return await _post(f"/approvals/{approval_id}/approve", body)


@mcp.tool()
async def reject(approval_id: str, comment: str = "") -> Any:
    """Reject a pending approval request.

    Args:
        approval_id: Approval UUID.
        comment: Reason for rejection — strongly recommended so the agent understands why.
    """
    body: dict[str, Any] = {}
    if comment:
        body["comment"] = comment
    return await _post(f"/approvals/{approval_id}/reject", body)


@mcp.tool()
async def request_approval_revision(approval_id: str, comment: str) -> Any:
    """Request a revision on a pending approval without fully rejecting it.

    The submitting agent will receive the comment and can resubmit.

    Args:
        approval_id: Approval UUID.
        comment: Required. Specific feedback describing what must change before approval.
    """
    if not comment.strip():
        return _err("A comment is required when requesting a revision.")
    return await _post(f"/approvals/{approval_id}/request-revision", {"comment": comment})


# ── COSTS & MONITORING ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_cost_summary(company_id: str = "") -> Any:
    """Get aggregate token usage and spend for a company this billing period.

    Returns total spend, remaining budget, and a per-agent cost breakdown.
    Use this to monitor AI spend and detect runaway agents.

    Args:
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    return await _get(f"/companies/{_company(company_id)}/costs/summary")


@mcp.tool()
async def get_dashboard(company_id: str = "") -> Any:
    """Get a high-level health summary for a company.

    Returns: agent count, open/in-progress/blocked issue counts, stale tasks,
    recent activity digest, and current-period cost totals.

    Args:
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    return await _get(f"/companies/{_company(company_id)}/dashboard")


@mcp.tool()
async def list_activity(
    agent_id: str = "",
    limit: int = 20,
    company_id: str = "",
) -> Any:
    """Retrieve the audit trail of recent actions in a company.

    Args:
        agent_id: Filter to a specific agent UUID. Leave empty for all agents.
        limit: Maximum number of entries to return (1–100). Default: 20.
        company_id: Target a specific company by context. Leave empty to use the
                    default company (PAPERCLIP_COMPANY_ID).
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if agent_id:
        params["agentId"] = agent_id
    return await _get(f"/companies/{_company(company_id)}/activity", params)


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point — invoked via `paperclip-mcp` or `python -m paperclip_mcp`."""
    import argparse

    from paperclip_mcp import __version__

    parser = argparse.ArgumentParser(
        prog="paperclip-mcp",
        description="MCP server for the Paperclip AI agent orchestration platform.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"paperclip-mcp {__version__}",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Use 0.0.0.0 only in trusted local networks.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9011,
        help="Bind port.",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=["streamable-http", "sse", "stdio"],
        help=(
            "MCP transport protocol. "
            "'streamable-http' for Claude Code / mcp-proxy; "
            "'stdio' for Claude Desktop."
        ),
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
