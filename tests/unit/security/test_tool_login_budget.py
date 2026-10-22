"""The tool password login shares the viewer's server-wide budget design (M11, 2026-10-22).

The per-client limiter keys on addresses; the budget bounds the PBKDF2 work
across all of them. Link-token logins are a cheap hash compare and stay outside it.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_tool_auth
from app.services import viewer_login_limits as limits
from app.services.request_security import LoginRateLimit


def _app(monkeypatch, *, attempts: str):
    monkeypatch.setattr(routes_tool_auth, "PASSWORD_BUDGET", limits.ViewerPasswordBudget("Tool"))
    monkeypatch.setattr(routes_tool_auth, "LOGIN_RATE_LIMIT", LoginRateLimit("TOOL"))
    monkeypatch.setattr(routes_tool_auth, "tool_access_enabled", lambda: True)
    monkeypatch.setenv("COPYLOT_TOOL_PASSWORD_MAX_ATTEMPTS", attempts)
    monkeypatch.setenv("COPYLOT_TOOL_PASSWORD_WINDOW_SECONDS", "60")
    app = FastAPI()
    app.include_router(routes_tool_auth.router)
    return app


def test_budget_spans_clients_and_rejected_attempts_do_no_hashing(monkeypatch) -> None:
    calls: list[str] = []

    def wrong(password):
        calls.append(password)
        raise ValueError("Invalid tool password.")

    monkeypatch.setattr(routes_tool_auth, "authenticate_tool_password", wrong)
    app = _app(monkeypatch, attempts="2")
    for index, status in enumerate([401, 401, 429]):
        with TestClient(app, client=(f"203.0.113.{index + 1}", 50000)) as client:
            response = client.post("/api/tool/auth/login", json={"password": "wrong"})
        assert response.status_code == status
    assert len(calls) == 2, "the third attempt was refused before the hash"
    assert response.headers["Retry-After"] == "60"
    assert response.json()["detail"] == "Tool login is busy. Please wait and try again."


def test_viewer_and_tool_budgets_are_separate(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("COPYLOT_TOOL_PASSWORD_MAX_ATTEMPTS", "3")
    viewer, tool = limits.ViewerPasswordBudget(), limits.ViewerPasswordBudget("Tool")
    with viewer.check():
        pass
    for _ in range(3):
        with tool.check():
            pass
    try:
        with viewer.check():
            pass
    except limits.ViewerLoginCapacityError as exc:
        assert str(exc).startswith("Viewer login")
    else:
        raise AssertionError("the viewer budget of 1 was not spent")


def test_link_token_login_is_not_budgeted(monkeypatch) -> None:
    monkeypatch.setattr(routes_tool_auth, "authenticate_tool_token", lambda token: "session")
    monkeypatch.setattr(routes_tool_auth, "set_session_cookie", lambda response, session: None)
    app = _app(monkeypatch, attempts="1")
    with TestClient(app) as client:
        for _ in range(3):
            assert client.post("/api/tool/auth/link-login", json={"token": "t"}).status_code == 200
