"""Tests for environment parsing. Bad config must fail loudly at startup."""

from __future__ import annotations

import os

import pytest

from unifi_toggle.config import ConfigError, load_settings

BASE_ENV = {
    "API_TOKEN": "a-sufficiently-long-token",
    "UNIFI_HOST": "192.168.0.1",
    "UNIFI_API_KEY": "some-api-key",
    "UNIFI_POLICY_ID": "665f1c2a9b1e4a0001abcdef",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "API_TOKEN", "BIND_HOST", "PORT", "TLS_CERT_FILE", "TLS_KEY_FILE",
        "LOG_LEVEL", "UNIFI_HOST", "UNIFI_SITE", "UNIFI_CONTROLLER_TYPE",
        "UNIFI_AUTH_MODE", "UNIFI_API_KEY", "UNIFI_USERNAME", "UNIFI_PASSWORD",
        "UNIFI_VERIFY_SSL", "UNIFI_TIMEOUT", "UNIFI_POLICY_ID", "UNIFI_POLICY_KIND",
        "UNIFI_POLICY_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


def apply(monkeypatch, **extra):
    for key, value in {**BASE_ENV, **extra}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_defaults(monkeypatch):
    apply(monkeypatch)
    s = load_settings()
    assert s.bind_host == "0.0.0.0"
    assert s.port == 8080
    assert s.unifi_base_url == "https://192.168.0.1"
    assert s.unifi_site == "default"
    assert s.network_prefix == "/proxy/network"
    assert s.login_path == "/api/auth/login"
    assert s.unifi_verify is False
    assert s.tls_enabled is False


def test_port_is_configurable(monkeypatch):
    apply(monkeypatch, PORT="9443")
    assert load_settings().port == 9443


def test_bare_host_gets_https_scheme(monkeypatch):
    apply(monkeypatch, UNIFI_HOST="unifi.lan")
    assert load_settings().unifi_base_url == "https://unifi.lan"


def test_explicit_scheme_and_port_are_preserved(monkeypatch):
    apply(monkeypatch, UNIFI_HOST="https://unifi.lan:8443/")
    assert load_settings().unifi_base_url == "https://unifi.lan:8443"


def test_self_hosted_controller_drops_proxy_prefix(monkeypatch):
    apply(monkeypatch, UNIFI_CONTROLLER_TYPE="network-server")
    s = load_settings()
    assert s.network_prefix == ""
    assert s.login_path == "/api/login"


def test_missing_token_is_rejected(monkeypatch):
    apply(monkeypatch, API_TOKEN=None)
    with pytest.raises(ConfigError, match="API_TOKEN"):
        load_settings()


def test_short_token_is_rejected(monkeypatch):
    apply(monkeypatch, API_TOKEN="short")
    with pytest.raises(ConfigError, match="at least 16"):
        load_settings()


def test_missing_both_policy_selectors_is_rejected(monkeypatch):
    apply(monkeypatch, UNIFI_POLICY_ID=None)
    with pytest.raises(ConfigError, match="UNIFI_POLICY_NAME"):
        load_settings()


def test_policy_name_alone_is_enough(monkeypatch):
    apply(monkeypatch, UNIFI_POLICY_ID=None, UNIFI_POLICY_NAME="Block Kids from Internet")
    s = load_settings()
    assert s.policy_id is None
    assert s.policy_name == "Block Kids from Internet"
    assert s.policy_descriptor == 'policy named "Block Kids from Internet"'


def test_policy_id_alone_is_enough(monkeypatch):
    apply(monkeypatch)
    s = load_settings()
    assert s.policy_name is None
    assert s.policy_descriptor.startswith("policy 665f")


def test_setting_both_warns_that_the_name_is_ignored(monkeypatch):
    apply(monkeypatch, UNIFI_POLICY_NAME="Some Other Rule")
    s = load_settings()
    assert any("name is ignored" in w for w in s.warnings)


def test_no_credentials_at_all_is_rejected(monkeypatch):
    apply(monkeypatch, UNIFI_API_KEY=None)
    with pytest.raises(ConfigError, match="no UniFi credentials"):
        load_settings()


def test_apikey_mode_without_key_is_rejected(monkeypatch):
    apply(monkeypatch, UNIFI_API_KEY=None, UNIFI_AUTH_MODE="apikey")
    with pytest.raises(ConfigError, match="UNIFI_API_KEY is not set"):
        load_settings()


def test_login_mode_without_password_is_rejected(monkeypatch):
    apply(monkeypatch, UNIFI_AUTH_MODE="login", UNIFI_USERNAME="svc")
    with pytest.raises(ConfigError, match="UNIFI_PASSWORD"):
        load_settings()


def test_password_only_setup_warns_about_2fa(monkeypatch):
    apply(monkeypatch, UNIFI_API_KEY=None, UNIFI_USERNAME="svc", UNIFI_PASSWORD="pw")
    s = load_settings()
    assert any("2FA" in w for w in s.warnings)


def test_api_key_setup_does_not_warn(monkeypatch):
    apply(monkeypatch)
    assert load_settings().warnings == ()


def test_half_configured_tls_is_rejected(monkeypatch, tmp_path):
    cert = tmp_path / "cert.pem"
    cert.write_text("x")
    apply(monkeypatch, TLS_CERT_FILE=str(cert))
    with pytest.raises(ConfigError, match="both TLS_CERT_FILE and TLS_KEY_FILE"):
        load_settings()


def test_tls_paths_must_exist(monkeypatch, tmp_path):
    apply(
        monkeypatch,
        TLS_CERT_FILE=str(tmp_path / "missing.pem"),
        TLS_KEY_FILE=str(tmp_path / "missing.key"),
    )
    with pytest.raises(ConfigError, match="not a file"):
        load_settings()


def test_tls_enables_when_both_present(monkeypatch, tmp_path):
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("y")
    apply(monkeypatch, TLS_CERT_FILE=str(cert), TLS_KEY_FILE=str(key))
    assert load_settings().tls_enabled is True


def test_verify_ssl_accepts_a_ca_bundle_path(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x")
    apply(monkeypatch, UNIFI_VERIFY_SSL=str(bundle))
    assert load_settings().unifi_verify == str(bundle)


def test_verify_ssl_rejects_a_missing_bundle(monkeypatch, tmp_path):
    apply(monkeypatch, UNIFI_VERIFY_SSL=str(tmp_path / "nope.pem"))
    with pytest.raises(ConfigError, match="not a file"):
        load_settings()


def test_invalid_choice_is_rejected(monkeypatch):
    apply(monkeypatch, UNIFI_POLICY_KIND="banana")
    with pytest.raises(ConfigError, match="UNIFI_POLICY_KIND"):
        load_settings()


def test_unreadable_tls_key_is_named_with_a_fix(monkeypatch, tmp_path):
    """A key the service cannot read must not surface as a bare PermissionError.

    os.access is stubbed rather than using real modes, because root bypasses
    permission bits entirely and CI often runs as root. The production service
    runs as the unprivileged unifi-toggle user, where the real check applies.
    """
    import os as os_module

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("y")

    real_access = os_module.access

    def fake_access(path, mode, **kwargs):
        if str(path) == str(key) and mode == os_module.R_OK:
            return False
        return real_access(path, mode, **kwargs)

    monkeypatch.setattr("unifi_toggle.config.os.access", fake_access)
    apply(monkeypatch, TLS_CERT_FILE=str(cert), TLS_KEY_FILE=str(key))
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "TLS_KEY_FILE" in message
    assert "not readable" in message
    assert "chmod 0640" in message
    assert str(key) in message


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_unreadable_tls_key_with_real_permissions(monkeypatch, tmp_path):
    """The same check, against real modes, when the suite is not run as root."""
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("y")
    os.chmod(key, 0o000)
    apply(monkeypatch, TLS_CERT_FILE=str(cert), TLS_KEY_FILE=str(key))
    try:
        with pytest.raises(ConfigError, match="not readable"):
            load_settings()
    finally:
        os.chmod(key, 0o600)


def test_readable_tls_pair_is_accepted(monkeypatch, tmp_path):
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("y")
    apply(monkeypatch, TLS_CERT_FILE=str(cert), TLS_KEY_FILE=str(key))
    assert load_settings().tls_enabled is True
