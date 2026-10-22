from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_viewer_auth
from app.services import viewer_login_limits as limits, viewer_portal
from app.services.password_hashing import hash_password
from app.services.request_security import LoginRateLimit


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setattr(viewer_portal, 'PASSWORD_BUDGET', limits.ViewerPasswordBudget())
    monkeypatch.setattr(viewer_portal, 'viewer_portal_enabled', lambda: True)
    monkeypatch.setattr(routes_viewer_auth, 'viewer_portal_enabled', lambda: True)
    monkeypatch.setattr(routes_viewer_auth, 'LOGIN_RATE_LIMIT', LoginRateLimit('VIEWER'))
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_CONCURRENCY', '2')
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS', '30')
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_WINDOW_SECONDS', '60')
    entries = [viewer_portal.ViewerAccessEntry('first', 'First', 'unused'),
               viewer_portal.ViewerAccessEntry('second', 'Second', 'unused')]
    monkeypatch.setattr(viewer_portal, '_load_access_entries', lambda root: entries)
    monkeypatch.setattr(viewer_portal, '_initialize_authenticated_viewer', viewer_portal.ViewerSessionAuth)
    return entries


def test_global_budget_spans_clients_and_does_not_hash_rejected_attempts(portal, monkeypatch):
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS', '2')
    calls = []
    monkeypatch.setattr(viewer_portal, '_password_matches', lambda password, entry: calls.append(entry) or False)
    app = FastAPI()
    app.include_router(routes_viewer_auth.router)
    for index, status in enumerate([401, 401, 429]):
        with TestClient(app, client=(f'198.51.100.{index + 1}', 50000)) as client:
            response = client.post('/api/viewer/auth/login', json={'password': 'wrong'})
        assert response.status_code == status
    assert len(calls) == 4  # two admitted attempts, each checking both projects
    assert response.headers['Retry-After'] == '60'
    assert response.json()['detail'] == 'Viewer login is busy. Please wait and try again.'


def test_success_preserves_password_only_workflow_and_spends_budget(portal, monkeypatch):
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS', '1')
    entries = [viewer_portal.ViewerAccessEntry('first', 'First', hash_password('other', iterations=100_000)),
               viewer_portal.ViewerAccessEntry('second', 'Second', hash_password('correct', iterations=100_000))]
    monkeypatch.setattr(viewer_portal, '_load_access_entries', lambda root: entries)
    app = FastAPI()
    app.include_router(routes_viewer_auth.router)
    with TestClient(app) as client:
        response = client.post('/api/viewer/auth/login', json={'password': 'correct'})
        assert response.status_code == 200
        assert response.json() == {'ok': True, 'project': 'second', 'projectLabel': 'Second'}
        assert 'copylot_session_id=' in response.headers['set-cookie']
        assert client.post('/api/viewer/auth/login', json={'password': 'correct'}).status_code == 429


def test_parallel_checks_are_bounded_without_queueing(portal, monkeypatch):
    entered = Barrier(3)
    release = Event()

    def match(password, entry):
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        return True

    monkeypatch.setattr(viewer_portal, '_password_matches', match)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(viewer_portal.authenticate_viewer_session, 'correct') for _ in range(2)]
        try:
            entered.wait(timeout=5)
            with pytest.raises(limits.ViewerLoginCapacityError) as error:
                viewer_portal.authenticate_viewer_session('correct')
            assert error.value.retry_after == 1
        finally:
            release.set()
        assert all(future.result(timeout=5).project == 'first' for future in futures)
    monkeypatch.setattr(viewer_portal, '_password_matches', lambda *args: True)
    assert viewer_portal.authenticate_viewer_session('correct').project == 'first'


@pytest.mark.parametrize('error', [ValueError, RuntimeError])
def test_slot_is_released_after_failure(portal, monkeypatch, error):
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_CONCURRENCY', '1')

    def fail(*args):
        raise error('check failed')

    monkeypatch.setattr(viewer_portal, '_password_matches', fail)
    with pytest.raises(error):
        viewer_portal.authenticate_viewer_session('wrong')
    monkeypatch.setattr(viewer_portal, '_password_matches', lambda *args: True)
    assert viewer_portal.authenticate_viewer_session('correct').project == 'first'


def test_window_expires_and_per_client_setting_cannot_disable_global_limit(portal, monkeypatch):
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS', '1')
    monkeypatch.setenv('COPYLOT_VIEWER_LOGIN_RATE_LIMIT_ENABLED', '0')
    now = [100.0]
    monkeypatch.setattr(limits.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(viewer_portal, '_password_matches', lambda *args: True)
    viewer_portal.authenticate_viewer_session('correct')
    now[0] = 159.5
    with pytest.raises(limits.ViewerLoginCapacityError) as error:
        viewer_portal.authenticate_viewer_session('correct')
    assert error.value.retry_after == 1
    now[0] = 160.0
    assert viewer_portal.authenticate_viewer_session('correct').project == 'first'


def test_qr_login_and_status_still_work_when_password_budget_is_exhausted(portal, monkeypatch):
    monkeypatch.setenv('COPYLOT_VIEWER_PASSWORD_MAX_ATTEMPTS', '1')
    monkeypatch.setattr(viewer_portal, '_password_matches', lambda *args: True)
    auth = viewer_portal.authenticate_viewer_session('correct')
    monkeypatch.setattr(routes_viewer_auth, 'authenticate_viewer_qr_session', lambda token: auth)
    monkeypatch.setattr(routes_viewer_auth, 'viewer_session_auth', lambda: auth)
    monkeypatch.setattr(routes_viewer_auth, 'ensure_viewer_session_bootstrapped', lambda **kwargs: auth)
    app = FastAPI()
    app.include_router(routes_viewer_auth.router)
    with TestClient(app) as client:
        assert client.post('/api/viewer/auth/login', json={'password': 'correct'}).status_code == 429
        assert client.post('/api/viewer/auth/qr-login', json={'token': 'link'}).status_code == 200
        assert client.get('/api/viewer/auth/status').json()['authenticated'] is True
