"""Tests for the HTTP surface: bearer auth, the three endpoints, error mapping."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_TOKEN, make_settings
from tests.fake_unifi import PREDEFINED_ID, create_fake_unifi
from unifi_toggle.main import create_app

PROTECTED = [
    ("GET", "/status"),
    ("GET", "/healthz"),
    ("POST", "/enable"),
    ("POST", "/disable"),
]


@pytest.fixture
def api(request):
    overrides = getattr(request, "param", {}) or {}
    fake_app, state = create_fake_unifi()
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake_app), base_url="https://unifi.test"
    )
    app = create_app(make_settings(**overrides), http)
    with TestClient(app) as client:
        yield client, state


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


# ------------------------------------------------------------------- auth


@pytest.mark.parametrize("method,path", PROTECTED)
def test_no_token_is_rejected(api, method, path):
    client, _ = api
    resp = client.request(method, path)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,path", PROTECTED)
def test_wrong_token_is_rejected(api, method, path):
    client, _ = api
    resp = client.request(method, path, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path", PROTECTED)
def test_correct_token_is_accepted(api, method, path):
    client, _ = api
    resp = client.request(method, path, headers=auth())
    assert resp.status_code == 200


def test_wrong_scheme_is_rejected(api):
    client, _ = api
    resp = client.get("/status", headers={"Authorization": f"Basic {TEST_TOKEN}"})
    assert resp.status_code == 401


def test_token_prefix_does_not_pass(api):
    """Guards against a truncating comparison."""
    client, _ = api
    resp = client.get("/status", headers={"Authorization": f"Bearer {TEST_TOKEN[:-1]}"})
    assert resp.status_code == 403


def test_no_unauthenticated_route_exists(api):
    client, _ = api
    for path in ("/", "/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code in (401, 403, 404)


# -------------------------------------------------------------- endpoints


def test_status_reports_current_state(api):
    client, _ = api
    body = client.get("/status", headers=auth()).json()
    assert body["enabled"] is False
    assert body["name"] == "Block Kids Internet"
    assert body["kind"] == "firewall-policy"
    assert body["site"] == "default"
    assert body["checked_at"]


def test_enable_disable_cycle_through_http(api):
    client, state = api

    body = client.post("/enable", headers=auth()).json()
    assert body["enabled"] is True
    assert body["changed"] is True

    assert client.get("/status", headers=auth()).json()["enabled"] is True

    body = client.post("/disable", headers=auth()).json()
    assert body["enabled"] is False
    assert body["changed"] is True

    assert client.get("/status", headers=auth()).json()["enabled"] is False
    assert state.policies[body["policy_id"]]["enabled"] is False


def test_repeat_enable_reports_changed_false(api):
    client, _ = api
    client.post("/enable", headers=auth())
    body = client.post("/enable", headers=auth()).json()
    assert body["enabled"] is True
    assert body["changed"] is False


@pytest.mark.parametrize("api", [{"policy_id": "no-such-policy"}], indirect=True)
def test_missing_policy_returns_404_with_hint(api):
    client, _ = api
    resp = client.get("/status", headers=auth())
    assert resp.status_code == 404
    assert "hint" in resp.json()


@pytest.mark.parametrize("api", [{"policy_id": PREDEFINED_ID}], indirect=True)
def test_predefined_policy_returns_409(api):
    client, _ = api
    resp = client.post("/disable", headers=auth())
    assert resp.status_code == 409
    assert "predefined" in resp.json()["error"]


def test_unreachable_console_returns_502_not_404(api):
    """An unreachable console must not masquerade as a missing policy.

    Points the client at a port nothing is listening on.
    """
    settings = make_settings(unifi_base_url="http://127.0.0.1:9", unifi_timeout=2.0)
    app = create_app(settings)
    with TestClient(app) as client:
        resp = client.get("/status", headers=auth())
    assert resp.status_code == 502
    assert "cannot reach UniFi console" in resp.json()["error"]
