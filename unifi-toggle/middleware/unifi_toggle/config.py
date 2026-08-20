"""Runtime configuration, read entirely from the process environment.

Nothing in here has a credential baked in. Every secret arrives through the
systemd EnvironmentFile (see systemd/unifi-toggle.service).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VALID_AUTH_MODES = ("auto", "apikey", "login")
VALID_POLICY_KINDS = ("auto", "firewall-policy", "traffic-rule", "firewall-rule")
VALID_CONTROLLER_TYPES = ("unifi-os", "network-server")


class ConfigError(RuntimeError):
    """Raised when the environment is missing or contradicts itself."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_required(name: str) -> str:
    value = _env(name)
    if not value:
        raise ConfigError(f"{name} is required but not set")
    return value


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = (_env(name, default) or default).lower()
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {value!r}")
    return value


def _normalise_base_url(raw: str) -> str:
    """Accept '192.168.0.1', 'https://192.168.0.1' or 'https://host:8443'."""
    candidate = raw.strip().rstrip("/")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    if not candidate.startswith(("http://", "https://")):
        raise ConfigError(f"UNIFI_HOST must be an http or https URL, got {raw!r}")
    return candidate


@dataclass(frozen=True)
class Settings:
    """Everything the service needs, resolved once at startup."""

    api_token: str
    bind_host: str
    port: int
    tls_cert_file: str | None
    tls_key_file: str | None
    log_level: str

    unifi_base_url: str
    unifi_site: str
    unifi_controller_type: str
    unifi_auth_mode: str
    unifi_api_key: str | None
    unifi_username: str | None
    unifi_password: str | None
    unifi_verify: bool | str
    unifi_timeout: float

    policy_id: str | None
    policy_name: str | None
    policy_kind: str

    # Populated by resolve_auth_mode() so /status can report what is in use.
    warnings: tuple[str, ...] = field(default=())

    @property
    def policy_descriptor(self) -> str:
        """How to refer to the target policy in a log line or an error."""
        if self.policy_id:
            return f"policy {self.policy_id}"
        return f'policy named "{self.policy_name}"'

    @property
    def network_prefix(self) -> str:
        """UniFi OS consoles put the Network application behind /proxy/network."""
        return "/proxy/network" if self.unifi_controller_type == "unifi-os" else ""

    @property
    def login_path(self) -> str:
        if self.unifi_controller_type == "unifi-os":
            return "/api/auth/login"
        return "/api/login"

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_file and self.tls_key_file)


def _resolve_verify() -> bool | str:
    """UNIFI_VERIFY_SSL is either a boolean or a path to a CA bundle."""
    raw = _env("UNIFI_VERIFY_SSL")
    if raw is None:
        # A UCG Ultra ships a self-signed certificate, so verification is off by
        # default. Point this at a CA bundle once you trust the console cert.
        return False
    lowered = raw.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    if not os.path.isfile(raw):
        raise ConfigError(f"UNIFI_VERIFY_SSL points at {raw!r} which is not a file")
    return raw


def load_settings() -> Settings:
    """Build Settings from the environment, failing loudly on bad input."""
    api_token = _env_required("API_TOKEN")
    if len(api_token) < 16:
        raise ConfigError("API_TOKEN must be at least 16 characters, generate one with scripts/gen-token.sh")

    tls_cert = _env("TLS_CERT_FILE")
    tls_key = _env("TLS_KEY_FILE")
    if bool(tls_cert) != bool(tls_key):
        raise ConfigError("set both TLS_CERT_FILE and TLS_KEY_FILE, or neither")
    for label, path in (("TLS_CERT_FILE", tls_cert), ("TLS_KEY_FILE", tls_key)):
        if not path:
            continue
        if not os.path.isfile(path):
            raise ConfigError(f"{label} points at {path!r} which is not a file")
        # Existence is not enough. The service runs unprivileged, and a key
        # left at 0600 root:root makes uvicorn die deep inside its TLS setup
        # with a bare PermissionError and no mention of which file. Check it
        # here, where we can name the file and the fix.
        if not os.access(path, os.R_OK):
            raise ConfigError(
                f"{label} at {path!r} exists but is not readable by this user. "
                f"Fix it with: sudo chown root:unifi-toggle {path} && "
                f"sudo chmod 0640 {path}"
            )

    auth_mode = _env_choice("UNIFI_AUTH_MODE", "auto", VALID_AUTH_MODES)
    api_key = _env("UNIFI_API_KEY")
    username = _env("UNIFI_USERNAME")
    password = _env("UNIFI_PASSWORD")

    warnings: list[str] = []
    if auth_mode == "apikey" and not api_key:
        raise ConfigError("UNIFI_AUTH_MODE=apikey but UNIFI_API_KEY is not set")
    if auth_mode == "login" and not (username and password):
        raise ConfigError("UNIFI_AUTH_MODE=login but UNIFI_USERNAME or UNIFI_PASSWORD is not set")
    if auth_mode == "auto" and not api_key and not (username and password):
        raise ConfigError(
            "no UniFi credentials found. Set UNIFI_API_KEY, or set both "
            "UNIFI_USERNAME and UNIFI_PASSWORD"
        )
    if auth_mode != "apikey" and (username and password) and not api_key:
        warnings.append(
            "using username and password login. If your Ubiquiti account has 2FA "
            "enabled this will fail with an MFA challenge. Prefer UNIFI_API_KEY."
        )

    # The policy can be named by ID or by the name shown in the UniFi UI.
    # The ID is stable across renames, so it wins when both are set.
    policy_id = _env("UNIFI_POLICY_ID")
    policy_name = _env("UNIFI_POLICY_NAME")
    if not policy_id and not policy_name:
        raise ConfigError(
            "set UNIFI_POLICY_ID, or UNIFI_POLICY_NAME to match the name shown "
            "in the UniFi UI. Run scripts/probe-unifi.sh to see both."
        )
    if policy_id and policy_name:
        warnings.append(
            "both UNIFI_POLICY_ID and UNIFI_POLICY_NAME are set. The ID is used "
            "and the name is ignored."
        )

    return Settings(
        api_token=api_token,
        bind_host=_env("BIND_HOST", "0.0.0.0") or "0.0.0.0",
        port=_env_int("PORT", 8080),
        tls_cert_file=tls_cert,
        tls_key_file=tls_key,
        log_level=(_env("LOG_LEVEL", "info") or "info").lower(),
        unifi_base_url=_normalise_base_url(_env_required("UNIFI_HOST")),
        unifi_site=_env("UNIFI_SITE", "default") or "default",
        unifi_controller_type=_env_choice(
            "UNIFI_CONTROLLER_TYPE", "unifi-os", VALID_CONTROLLER_TYPES
        ),
        unifi_auth_mode=auth_mode,
        unifi_api_key=api_key,
        unifi_username=username,
        unifi_password=password,
        unifi_verify=_resolve_verify(),
        unifi_timeout=float(_env_int("UNIFI_TIMEOUT", 10)),
        policy_id=policy_id,
        policy_name=policy_name,
        policy_kind=_env_choice("UNIFI_POLICY_KIND", "auto", VALID_POLICY_KINDS),
        warnings=tuple(warnings),
    )
