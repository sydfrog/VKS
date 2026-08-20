"""Tests for the UniFi client itself, against the fake console."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import make_settings
from tests.fake_unifi import (
    API_KEY,
    FIREWALL_RULE_ID,
    PASSWORD,
    PREDEFINED_ID,
    TRAFFIC_RULE_ID,
    USERNAME,
)
from unifi_toggle.unifi import (
    AuthError,
    ConnectivityError,
    PolicyNotFound,
    UniFiClient,
    UniFiError,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def test_reads_current_state(fake_console):
    http, _state = fake_console
    client = UniFiClient(make_settings(), http)
    state = await client.get_state()
    assert state.name == "Block Kids Internet"
    assert state.enabled is False
    assert state.kind == "firewall-policy"


async def test_enable_then_disable_round_trip(fake_console):
    http, st = fake_console
    client = UniFiClient(make_settings(), http)

    state, changed = await client.set_enabled(True)
    assert state.enabled is True
    assert changed is True
    assert st.policies[state.policy_id]["enabled"] is True

    state, changed = await client.set_enabled(False)
    assert state.enabled is False
    assert changed is True
    assert st.policies[state.policy_id]["enabled"] is False


async def test_enable_is_idempotent_and_reports_no_change(fake_console):
    http, _st = fake_console
    client = UniFiClient(make_settings(), http)
    await client.set_enabled(True)
    state, changed = await client.set_enabled(True)
    assert state.enabled is True
    assert changed is False


async def test_read_modify_write_preserves_other_fields(fake_console):
    """A blind PUT of {"enabled": true} would wipe the rule. It must not."""
    http, st = fake_console
    client = UniFiClient(make_settings(), http)
    await client.set_enabled(True)
    stored = st.policies[make_settings().policy_id]
    assert stored["action"] == "BLOCK"
    assert stored["source"] == {"zone_id": "lan"}
    assert stored["index"] == 10000


async def test_falls_back_to_batch_endpoint_when_item_put_rejected(fake_console):
    http, st = fake_console
    st.item_put_status = 405
    client = UniFiClient(make_settings(), http)
    state, changed = await client.set_enabled(True)
    assert state.enabled is True
    assert changed is True
    assert "batch_policies" in st.calls


async def test_auto_probe_finds_traffic_rule(fake_console):
    http, _st = fake_console
    client = UniFiClient(make_settings(policy_id=TRAFFIC_RULE_ID), http)
    state = await client.get_state()
    assert state.kind == "traffic-rule"
    assert state.name == "Pause Console"


async def test_auto_probe_finds_legacy_firewall_rule(fake_console):
    http, _st = fake_console
    client = UniFiClient(make_settings(policy_id=FIREWALL_RULE_ID), http)
    state, changed = await client.set_enabled(True)
    assert state.kind == "firewall-rule"
    assert state.enabled is True
    assert changed is True


async def test_unknown_policy_id_raises_not_found(fake_console):
    http, _st = fake_console
    client = UniFiClient(make_settings(policy_id="does-not-exist"), http)
    with pytest.raises(PolicyNotFound) as excinfo:
        await client.get_state()
    assert "probe-unifi.sh" in (excinfo.value.hint or "")


async def test_predefined_policy_refuses_edit(fake_console):
    http, _st = fake_console
    client = UniFiClient(make_settings(policy_id=PREDEFINED_ID), http)
    with pytest.raises(UniFiError) as excinfo:
        await client.set_enabled(False)
    assert excinfo.value.status == 409


async def test_bad_api_key_is_reported_clearly(fake_console):
    """An auth failure must not be reported as a missing policy."""
    http, st = fake_console
    st.accept_api_key = False
    client = UniFiClient(make_settings(), http)
    with pytest.raises(AuthError) as excinfo:
        await client.get_state()
    assert not isinstance(excinfo.value, PolicyNotFound)
    assert "API key" in (excinfo.value.hint or "")


async def test_cookie_login_mode_works_without_api_key(fake_console):
    http, st = fake_console
    settings = make_settings(
        unifi_auth_mode="login",
        unifi_api_key=None,
        unifi_username=USERNAME,
        unifi_password=PASSWORD,
    )
    client = UniFiClient(settings, http)
    state, changed = await client.set_enabled(True)
    assert state.enabled is True
    assert changed is True
    assert "login" in st.calls


async def test_login_mode_reports_mfa_challenge_with_actionable_hint(fake_console):
    """This is the case the operator hits when 2FA is on the account."""
    http, st = fake_console
    st.require_mfa = True
    settings = make_settings(
        unifi_auth_mode="login",
        unifi_api_key=None,
        unifi_username=USERNAME,
        unifi_password=PASSWORD,
    )
    client = UniFiClient(settings, http)
    with pytest.raises(AuthError) as excinfo:
        await client.get_state()
    assert "2FA" in str(excinfo.value)
    assert "Control Plane > Integrations" in (excinfo.value.hint or "")


async def test_api_key_mode_never_calls_login(fake_console):
    http, st = fake_console
    st.require_mfa = True  # would break a login, must not be reached
    client = UniFiClient(make_settings(unifi_api_key=API_KEY), http)
    state = await client.get_state()
    assert state.enabled is False
    assert "login" not in st.calls


async def test_connectivity_failure_is_not_reported_as_missing_policy(fake_console):
    """Wrong UNIFI_HOST must say "cannot reach", not "policy not found"."""
    _http, _st = fake_console
    client = UniFiClient(make_settings(unifi_base_url="http://127.0.0.1:9", unifi_timeout=2.0))
    with pytest.raises(ConnectivityError) as excinfo:
        await client.get_state()
    assert not isinstance(excinfo.value, PolicyNotFound)
    assert "cannot reach UniFi console" in str(excinfo.value)
    await client.aclose()


async def test_redirect_to_login_is_reported_as_an_auth_problem(fake_console):
    """A console that redirects instead of answering must not look like bad JSON."""
    http, _st = fake_console

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/login"})

    redirecting = httpx.AsyncClient(
        transport=httpx.MockTransport(redirect), base_url="https://unifi.test"
    )
    client = UniFiClient(make_settings(), redirecting)
    with pytest.raises(AuthError) as excinfo:
        await client.get_state()
    assert "redirected" in str(excinfo.value)
    await redirecting.aclose()
