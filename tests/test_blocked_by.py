"""Tests for blocked_by_issue_ids passthrough on create_issue / update_issue."""

from typing import Any

import pytest

from paperclip_mcp import server


@pytest.fixture(autouse=True)
def _baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "COMPANY", "co-1")


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the (method, path, body) of the outbound API call."""
    calls: dict[str, Any] = {}

    async def fake_request(
        method: str,
        path: str,
        params: Any = None,
        body: Any = None,
        company_id: str = "",
    ) -> Any:
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        calls["company_id"] = company_id
        return {"ok": True}

    monkeypatch.setattr(server, "_request", fake_request)
    return calls


async def test_create_threads_blocked_by(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await server.create_issue(title="t", blocked_by_issue_ids=["a", "b"])
    assert calls["method"] == "POST"
    assert calls["body"]["blockedByIssueIds"] == ["a", "b"]


async def test_create_omits_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await server.create_issue(title="t")
    assert "blockedByIssueIds" not in calls["body"]


async def test_update_threads_blocked_by(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await server.update_issue(issue_id="X-1", blocked_by_issue_ids=["a"])
    assert calls["method"] == "PATCH"
    assert calls["path"] == "/issues/X-1"
    assert calls["body"]["blockedByIssueIds"] == ["a"]


async def test_update_empty_list_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await server.update_issue(issue_id="X-1", blocked_by_issue_ids=[])
    assert calls["body"]["blockedByIssueIds"] == []


async def test_update_blockers_only_is_not_no_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    res = await server.update_issue(issue_id="X-1", blocked_by_issue_ids=["a"])
    assert res == {"ok": True}
    assert calls.get("method") == "PATCH"


async def test_update_none_keeps_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    await server.update_issue(issue_id="X-1", title="t")
    assert "blockedByIssueIds" not in calls["body"]
