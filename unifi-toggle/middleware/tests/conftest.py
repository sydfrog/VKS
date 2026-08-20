"""Shared fixtures. The UniFi client is pointed at an in-process fake console."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fake_unifi import API_KEY, POLICY_ID, FakeState, create_fake_unifi  # noqa: E402
from unifi_toggle.config import Settings  # noqa: E402

TEST_TOKEN = "test-bearer-token-1234567890"
FAKE_BASE = "https://unifi.test"


def make_settings(**overrides) -> Settings:
    base = {
        "api_token": TEST_TOKEN,
        "bind_host": "127.0.0.1",
        "port": 8080,
        "tls_cert_file": None,
        "tls_key_file": None,
        "log_level": "warning",
        "unifi_base_url": FAKE_BASE,
        "unifi_site": "default",
        "unifi_controller_type": "unifi-os",
        "unifi_auth_mode": "apikey",
        "unifi_api_key": API_KEY,
        "unifi_username": None,
        "unifi_password": None,
        "unifi_verify": False,
        "unifi_timeout": 5.0,
        "policy_id": POLICY_ID,
        "policy_kind": "auto",
        "warnings": (),
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def fake_console() -> tuple[httpx.AsyncClient, FakeState]:
    app, state = create_fake_unifi()
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=FAKE_BASE
    )
    return client, state
