"""Minimal UniFi client for reading and flipping the enabled flag on one policy.

Why this talks to the internal v2 API rather than the official Integrations API
--------------------------------------------------------------------------
As of UniFi Network 9.x the official Integrations API (/proxy/network/integration/v1)
covers sites, devices, clients and hotspot vouchers. It does not expose firewall
policies or traffic rules, so there is no supported endpoint that can toggle the
rule you created in the UI. This client therefore uses the same internal v2
endpoints the Network web UI itself calls.

The API key you create under Control Plane > Integrations is validated by UniFi OS
at the reverse proxy layer, which is why it also works for those internal paths,
and why it sidesteps the 2FA challenge that username and password login triggers.
Because this is an internal API, a future Network release may move it. The service
probes at startup and reports what it found, so a break shows up as a clear error
on GET /status rather than a silent no-op.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("unifi_toggle.unifi")

# Probe order for UNIFI_POLICY_KIND=auto. Newest shape first, because a 9.x
# console is the common case and the zone based firewall policy is what the
# current UI creates.
AUTO_PROBE_ORDER = ("firewall-policy", "traffic-rule", "firewall-rule")


class UniFiError(RuntimeError):
    """Any failure talking to the console. Carries an HTTP status hint."""

    def __init__(self, message: str, status: int = 502, hint: str | None = None):
        super().__init__(message)
        self.status = status
        self.hint = hint


class PolicyNotFound(UniFiError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message, status=404, hint=hint)


class FatalUniFiError(UniFiError):
    """A failure that will repeat identically for every policy shape.

    The auto probe walks three different endpoints looking for the policy ID. A
    404 on one of them genuinely means "try the next shape", but a refused
    credential or an unreachable console does not. Reporting those as "policy
    not found" sends the operator hunting for a wrong ID when the real problem
    is the API key or the console address, so they abort the probe instead.
    """


class AuthError(FatalUniFiError):
    """The console rejected our credentials."""


class ConnectivityError(FatalUniFiError):
    """The console could not be reached at all."""


class AmbiguousPolicy(FatalUniFiError):
    """A configured policy name matched more than one policy.

    Fatal rather than "keep probing", because guessing which of two rules the
    operator meant is exactly the wrong thing to do when the rule controls
    network access.
    """

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message, status=409, hint=hint)


@dataclass(frozen=True)
class PolicyState:
    policy_id: str
    name: str
    enabled: bool
    kind: str
    site: str
    predefined: bool = False


def _decode_csrf_from_jwt(token: str) -> str | None:
    """UniFi OS puts csrfToken inside the TOKEN cookie, which is an unsigned-read JWT.

    We only read the payload. We never verify or trust it for anything beyond
    echoing the CSRF value back, which is exactly what the web UI does.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded).get("csrfToken")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


class UniFiClient:
    """One long lived client. Safe to share across requests."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self._s = settings
        self._csrf: str | None = None
        self._logged_in = False
        self._resolved_kind: str | None = (
            None if settings.policy_kind == "auto" else settings.policy_kind
        )
        self._auth_lock = asyncio.Lock()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.unifi_base_url,
            verify=settings.unifi_verify,
            timeout=settings.unifi_timeout,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def resolved_kind(self) -> str | None:
        return self._resolved_kind

    @property
    def auth_mode(self) -> str:
        if self._s.unifi_auth_mode != "auto":
            return self._s.unifi_auth_mode
        return "apikey" if self._s.unifi_api_key else "login"

    # ---------------------------------------------------------------- paths

    def _v2(self, suffix: str) -> str:
        return f"{self._s.network_prefix}/v2/api/site/{self._s.unifi_site}{suffix}"

    def _v1(self, suffix: str) -> str:
        return f"{self._s.network_prefix}/api/s/{self._s.unifi_site}{suffix}"

    def _list_path(self, kind: str) -> str:
        if kind == "firewall-policy":
            return self._v2("/firewall-policies")
        if kind == "traffic-rule":
            return self._v2("/trafficrules")
        if kind == "firewall-rule":
            return self._v1("/rest/firewallrule")
        raise UniFiError(f"unknown policy kind {kind!r}", status=500)

    # ----------------------------------------------------------------- auth

    async def _ensure_login(self) -> None:
        """Cookie login, used only when no API key is configured."""
        if self._logged_in:
            return
        async with self._auth_lock:
            if self._logged_in:
                return
            if not (self._s.unifi_username and self._s.unifi_password):
                raise UniFiError(
                    "no UniFi credentials available for cookie login",
                    status=500,
                    hint="set UNIFI_API_KEY, or UNIFI_USERNAME and UNIFI_PASSWORD",
                )
            body = {
                "username": self._s.unifi_username,
                "password": self._s.unifi_password,
                "rememberMe": True,
            }
            try:
                resp = await self._client.post(self._s.login_path, json=body)
            except httpx.RequestError as exc:
                raise ConnectivityError(f"cannot reach UniFi console: {exc}") from exc

            if resp.status_code == 499:
                raise AuthError(
                    "UniFi console demanded a 2FA code for this account",
                    status=502,
                    hint=(
                        "2FA cannot be answered by a headless service. Create an API key "
                        "under Control Plane > Integrations and set UNIFI_API_KEY instead."
                    ),
                )
            if resp.status_code in (400, 401, 403):
                raise AuthError(
                    f"UniFi login rejected the credentials (HTTP {resp.status_code})",
                    status=502,
                    hint="check UNIFI_USERNAME and UNIFI_PASSWORD, or switch to UNIFI_API_KEY",
                )
            if resp.status_code >= 400:
                raise UniFiError(f"UniFi login failed with HTTP {resp.status_code}")

            csrf = resp.headers.get("x-csrf-token") or resp.headers.get("x-updated-csrf-token")
            if not csrf:
                token_cookie = self._client.cookies.get("TOKEN")
                if token_cookie:
                    csrf = _decode_csrf_from_jwt(token_cookie)
            self._csrf = csrf
            self._logged_in = True
            log.info("logged in to UniFi console as %s", self._s.unifi_username)

    def _auth_headers(self, mutating: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_mode == "apikey":
            headers["X-API-KEY"] = self._s.unifi_api_key or ""
        elif mutating and self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    # ------------------------------------------------------------- requests

    async def _request(self, method: str, path: str, json_body: Any = None) -> httpx.Response:
        """Issue one request, re-authenticating once on a 401."""
        for attempt in (1, 2):
            if self.auth_mode == "login":
                await self._ensure_login()
            headers = self._auth_headers(mutating=method.upper() != "GET")
            try:
                resp = await self._client.request(
                    method, path, headers=headers, json=json_body
                )
            except httpx.RequestError as exc:
                raise ConnectivityError(f"cannot reach UniFi console: {exc}") from exc

            refreshed = resp.headers.get("x-updated-csrf-token")
            if refreshed:
                self._csrf = refreshed

            if resp.status_code == 401 and attempt == 1 and self.auth_mode == "login":
                self._logged_in = False
                continue
            return resp
        raise UniFiError("UniFi console kept returning 401 after re-login")

    def _check(self, resp: httpx.Response, what: str) -> None:
        if 300 <= resp.status_code < 400:
            # follow_redirects is off so a stale session cannot be replayed to
            # wherever the console points. A redirect here almost always means
            # the login page, so say that rather than failing on the HTML body.
            raise AuthError(
                f"UniFi redirected {what} to {resp.headers.get('location', 'an unknown location')}",
                hint=(
                    "the console answered with a redirect instead of data, which "
                    "usually means the credential was not accepted. Check UNIFI_API_KEY."
                ),
            )
        if resp.status_code in (401, 403):
            hint = (
                "the API key was rejected. Confirm it is an API key from "
                "Control Plane > Integrations and that it has not been revoked."
                if self.auth_mode == "apikey"
                else "the session was rejected. Check the account permissions."
            )
            raise AuthError(f"UniFi denied {what} (HTTP {resp.status_code})", hint=hint)
        if resp.status_code >= 400:
            raise UniFiError(
                f"UniFi returned HTTP {resp.status_code} for {what}: "
                f"{resp.text[:300]}"
            )

    @staticmethod
    def _unwrap(payload: Any) -> list[dict]:
        """v2 returns a bare list. The legacy v1 rest API wraps it in {meta,data}."""
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                return [item for item in payload["data"] if isinstance(item, dict)]
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        raise UniFiError(f"unexpected JSON shape from UniFi: {type(payload).__name__}")

    async def _fetch_list(self, kind: str) -> list[dict]:
        resp = await self._request("GET", self._list_path(kind))
        if resp.status_code == 404:
            return []
        self._check(resp, f"listing {kind}s")
        try:
            return self._unwrap(resp.json())
        except json.JSONDecodeError as exc:
            raise UniFiError(f"UniFi returned non-JSON when listing {kind}s") from exc

    # ------------------------------------------------------------ discovery

    def _matches(self, item: dict) -> bool:
        """Match on ID when one is configured, otherwise on the display name."""
        if self._s.policy_id:
            return (
                item.get("_id") == self._s.policy_id or item.get("id") == self._s.policy_id
            )
        wanted = (self._s.policy_name or "").strip().casefold()
        # Firewall policies use "name". Legacy traffic rules use "description".
        actual = str(item.get("name") or item.get("description") or "").strip().casefold()
        return bool(wanted) and actual == wanted

    async def _find(self, kind: str) -> dict | None:
        matches = [item for item in await self._fetch_list(kind) if self._matches(item)]
        if len(matches) > 1:
            ids = ", ".join(str(m.get("_id") or m.get("id")) for m in matches)
            raise AmbiguousPolicy(
                f'{len(matches)} policies are named "{self._s.policy_name}" ({ids})',
                hint=(
                    "rename one of them in the UniFi UI, or set UNIFI_POLICY_ID to "
                    "the one you want and clear UNIFI_POLICY_NAME."
                ),
            )
        return matches[0] if matches else None

    async def _locate(self) -> tuple[str, dict]:
        """Return (kind, policy object) for the configured policy ID or name."""
        if self._resolved_kind:
            found = await self._find(self._resolved_kind)
            if found is None:
                raise PolicyNotFound(
                    f"{self._s.policy_descriptor} not found as a {self._resolved_kind}",
                    hint=(
                        "confirm UNIFI_POLICY_ID or UNIFI_POLICY_NAME, and UNIFI_SITE. "
                        "Run scripts/probe-unifi.sh to list every policy on the console."
                    ),
                )
            return self._resolved_kind, found

        errors: list[str] = []
        for kind in AUTO_PROBE_ORDER:
            try:
                found = await self._find(kind)
            except FatalUniFiError:
                # Bad credentials or an unreachable console. Every other kind
                # would fail identically, so surface this one as is.
                raise
            except UniFiError as exc:
                errors.append(f"{kind}: {exc}")
                continue
            if found is not None:
                self._resolved_kind = kind
                log.info(
                    "resolved %s as kind %s, id %s",
                    self._s.policy_descriptor,
                    kind,
                    found.get("_id") or found.get("id"),
                )
                return kind, found
        detail = "; ".join(errors) if errors else "it matched no policy of any kind"
        raise PolicyNotFound(
            f"{self._s.policy_descriptor} not found on site "
            f"{self._s.unifi_site} ({detail})",
            hint=(
                "run scripts/probe-unifi.sh to list what the console actually has. "
                "A name has to match exactly apart from case and surrounding spaces, "
                "and check UNIFI_SITE if you use more than one site."
            ),
        )

    @staticmethod
    def _to_state(kind: str, obj: dict, site: str) -> PolicyState:
        return PolicyState(
            policy_id=str(obj.get("_id") or obj.get("id") or ""),
            name=str(obj.get("name") or obj.get("description") or "(unnamed)"),
            enabled=bool(obj.get("enabled", False)),
            kind=kind,
            site=site,
            predefined=bool(obj.get("predefined", False)),
        )

    # ------------------------------------------------------------ public API

    async def get_state(self) -> PolicyState:
        kind, obj = await self._locate()
        return self._to_state(kind, obj, self._s.unifi_site)

    async def set_enabled(self, enabled: bool) -> tuple[PolicyState, bool]:
        """Read, modify, write. Returns the new state and whether it changed."""
        kind, obj = await self._locate()
        before = self._to_state(kind, obj, self._s.unifi_site)
        if before.enabled == enabled:
            return before, False
        if before.predefined:
            raise UniFiError(
                f"policy {before.policy_id} is predefined and cannot be edited",
                status=409,
                hint="predefined policies are read only. Toggle a policy you created.",
            )

        updated = dict(obj)
        updated["enabled"] = enabled
        written = await self._write(kind, updated)
        after = self._to_state(kind, written or updated, self._s.unifi_site)
        if after.enabled != enabled:
            raise UniFiError(
                f"UniFi accepted the update but the policy is still "
                f"{'enabled' if after.enabled else 'disabled'}"
            )
        return after, True

    async def _write(self, kind: str, obj: dict) -> dict | None:
        policy_id = obj.get("_id") or obj.get("id")
        if kind == "firewall-policy":
            item = f"{self._list_path(kind)}/{policy_id}"
            resp = await self._request("PUT", item, json_body=obj)
            if resp.status_code in (404, 405):
                # Some 9.x builds only accept the batch form for policy edits.
                batch = f"{self._list_path(kind)}/batch"
                resp = await self._request("PUT", batch, json_body=[obj])
        elif kind == "traffic-rule":
            resp = await self._request(
                "PUT", f"{self._list_path(kind)}/{policy_id}", json_body=obj
            )
        elif kind == "firewall-rule":
            resp = await self._request(
                "PUT", f"{self._list_path(kind)}/{policy_id}", json_body=obj
            )
        else:
            raise UniFiError(f"unknown policy kind {kind!r}", status=500)

        self._check(resp, f"updating {kind} {policy_id}")
        if not resp.content:
            return None
        try:
            items = self._unwrap(resp.json())
        except json.JSONDecodeError:
            return None
        for item in items:
            if item.get("_id") == policy_id or item.get("id") == policy_id:
                return item
        return items[0] if items else None
