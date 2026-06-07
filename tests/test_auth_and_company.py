"""Tests for per-user bearer passthrough (_headers) and company-by-context (_company)."""

from typing import Any

import pytest

from paperclip_mcp import server


@pytest.fixture(autouse=True)
def _baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known baseline so each test controls precedence explicitly."""
    monkeypatch.setattr(server, "API_KEY", "")
    monkeypatch.setattr(server, "SESSION_TOKEN", "")
    monkeypatch.setattr(server, "COMPANY", "default-co")


def _stub_inbound(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    """Stub get_http_headers as used inside server._inbound_authorization()."""

    def fake(include: Any = None, include_all: bool = False) -> dict[str, str]:
        return dict(headers)

    monkeypatch.setattr(server, "get_http_headers", fake)


# ── _headers: auth precedence ────────────────────────────────────────────────

def test_inbound_bearer_preferred_over_baked_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {"authorization": "Bearer pcp_user_token"})
    assert server._headers()["Authorization"] == "Bearer pcp_user_token"


def test_falls_back_to_api_key_when_no_inbound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {})  # no HTTP request context (e.g. stdio)
    assert server._headers()["Authorization"] == "Bearer baked-agent-key"


def test_falls_back_to_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "SESSION_TOKEN", "sess-abc")
    _stub_inbound(monkeypatch, {})
    headers = server._headers()
    assert "Authorization" not in headers
    assert headers["Cookie"] == f"{server._COOKIE_NAME}=sess-abc"


def test_blank_inbound_bearer_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {"authorization": "   "})
    assert server._headers()["Authorization"] == "Bearer baked-agent-key"


def test_no_cross_request_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Request A's bearer must not bleed into request B (no HTTP context)."""
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {"authorization": "Bearer pcp_user_A"})
    assert server._headers()["Authorization"] == "Bearer pcp_user_A"
    _stub_inbound(monkeypatch, {})  # next request: no inbound auth
    assert server._headers()["Authorization"] == "Bearer baked-agent-key"


def test_run_id_present_and_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {})
    assert server._headers()["X-Paperclip-Run-Id"] != server._headers()["X-Paperclip-Run-Id"]


# ── _company: company-by-context ─────────────────────────────────────────────

def test_company_defaults_to_configured() -> None:
    assert server._company() == "default-co"
    assert server._company("") == "default-co"
    assert server._company("   ") == "default-co"


def test_company_override_wins() -> None:
    assert server._company("other-co") == "other-co"
    assert server._company("  other-co  ") == "other-co"


def test_company_header_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "API_KEY", "baked-agent-key")
    _stub_inbound(monkeypatch, {})
    assert server._headers("other-co")["X-Paperclip-Company"] == "other-co"
