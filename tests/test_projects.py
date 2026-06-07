"""Tests for project tools and issue project assignment."""

from typing import Any

import pytest

from paperclip_mcp import server


@pytest.fixture(autouse=True)
def _baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "COMPANY", "co-1")


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
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
        calls["params"] = params
        calls["body"] = body
        calls["company_id"] = company_id
        return {"ok": True}

    monkeypatch.setattr(server, "_request", fake_request)
    return calls


async def test_update_issue_sets_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.update_issue(issue_id="PEN-503", project_id="project-1", company_id="pen-co")

    assert calls["method"] == "PATCH"
    assert calls["path"] == "/issues/PEN-503"
    assert calls["company_id"] == "pen-co"
    assert calls["body"] == {"projectId": "project-1"}


async def test_update_issue_can_clear_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.update_issue(issue_id="PEN-503", project_id="")

    assert calls["body"] == {"projectId": None}


async def test_list_projects_uses_company_context(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.list_projects(company_id="pen-co")

    assert calls["method"] == "GET"
    assert calls["path"] == "/companies/pen-co/projects"
    assert calls["company_id"] == "pen-co"


async def test_get_project_passes_company_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.get_project(project_id="project-1", company_id="pen-co")

    assert calls["method"] == "GET"
    assert calls["path"] == "/projects/project-1"
    assert calls["params"] == {"companyId": "pen-co"}
    assert calls["company_id"] == "pen-co"


async def test_create_project_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.create_project(
        name="Gate triage",
        description="Project for gate issues",
        status="in_progress",
        goal_ids=["goal-1"],
        lead_agent_id="agent-1",
        target_date="2026-06-30",
        color="#0ea5e9",
        company_id="pen-co",
    )

    assert calls["method"] == "POST"
    assert calls["path"] == "/companies/pen-co/projects"
    assert calls["company_id"] == "pen-co"
    assert calls["body"] == {
        "name": "Gate triage",
        "description": "Project for gate issues",
        "status": "in_progress",
        "goalIds": ["goal-1"],
        "leadAgentId": "agent-1",
        "targetDate": "2026-06-30",
        "color": "#0ea5e9",
    }


async def test_update_project_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.update_project(
        project_id="project-1",
        status="completed",
        target_date="",
        company_id="pen-co",
    )

    assert calls["method"] == "PATCH"
    assert calls["path"] == "/projects/project-1"
    assert calls["company_id"] == "pen-co"
    assert calls["body"] == {
        "status": "completed",
        "targetDate": None,
    }


async def test_list_goals_remains_goal_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)

    await server.list_goals(company_id="pen-co")

    assert calls["method"] == "GET"
    assert calls["path"] == "/companies/pen-co/goals"
    assert calls["company_id"] == "pen-co"
