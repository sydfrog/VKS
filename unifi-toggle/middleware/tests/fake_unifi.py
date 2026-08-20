"""A stand-in UniFi OS console used by the test suite and the local smoke test.

It speaks the same shapes as a real UCG Ultra running Network 9.x:
  POST /api/auth/login                                       cookie login plus CSRF
  GET  /proxy/network/v2/api/site/{site}/firewall-policies   zone based policies
  PUT  /proxy/network/v2/api/site/{site}/firewall-policies/{id}
  PUT  /proxy/network/v2/api/site/{site}/firewall-policies/batch
  GET  /proxy/network/v2/api/site/{site}/trafficrules
  PUT  /proxy/network/v2/api/site/{site}/trafficrules/{id}
  GET  /proxy/network/api/s/{site}/rest/firewallrule
  PUT  /proxy/network/api/s/{site}/rest/firewallrule/{id}

Knobs let a test demand MFA, reject the API key, or refuse the single item PUT so
the batch fallback is exercised.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

API_KEY = "fake-api-key-0123456789"
USERNAME = "toggle-svc"
PASSWORD = "correct horse battery staple"
CSRF = "csrf-token-abcdef"
SITE = "default"

POLICY_ID = "665f1c2a9b1e4a0001abcdef"
TRAFFIC_RULE_ID = "665f1c2a9b1e4a0001aaaaaa"
FIREWALL_RULE_ID = "665f1c2a9b1e4a0001bbbbbb"
PREDEFINED_ID = "665f1c2a9b1e4a0001ffffff"


def _jwt_with_csrf(csrf: str) -> str:
    def seg(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg': 'HS256'})}.{seg({'csrfToken': csrf})}.signature"


@dataclass
class FakeState:
    """Mutable knobs and the policy store."""

    require_mfa: bool = False
    accept_api_key: bool = True
    item_put_status: int = 200  # set to 405 to force the batch fallback
    calls: list[str] = field(default_factory=list)
    policies: dict[str, dict] = field(default_factory=dict)
    traffic_rules: dict[str, dict] = field(default_factory=dict)
    firewall_rules: dict[str, dict] = field(default_factory=dict)

    def reset(self) -> None:
        self.require_mfa = False
        self.accept_api_key = True
        self.item_put_status = 200
        self.calls = []
        self.policies = {
            POLICY_ID: {
                "_id": POLICY_ID,
                "name": "Block Kids from Internet",
                "enabled": False,
                "action": "BLOCK",
                "predefined": False,
                "index": 10000,
                "source": {"zone_id": "lan"},
                "destination": {"zone_id": "wan"},
            },
            PREDEFINED_ID: {
                "_id": PREDEFINED_ID,
                "name": "Allow Return Traffic",
                "enabled": True,
                "predefined": True,
            },
        }
        self.traffic_rules = {
            TRAFFIC_RULE_ID: {
                "_id": TRAFFIC_RULE_ID,
                "description": "Pause Console",
                "enabled": False,
                "action": "BLOCK",
            }
        }
        self.firewall_rules = {
            FIREWALL_RULE_ID: {
                "_id": FIREWALL_RULE_ID,
                "name": "Legacy Block",
                "enabled": False,
                "ruleset": "LAN_IN",
            }
        }


def create_fake_unifi(state: FakeState | None = None) -> tuple[FastAPI, FakeState]:
    st = state or FakeState()
    st.reset()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authorised(request: Request) -> JSONResponse | None:
        key = request.headers.get("x-api-key")
        if key:
            if st.accept_api_key and key == API_KEY:
                return None
            return JSONResponse({"error": "invalid api key"}, status_code=401)
        if request.cookies.get("TOKEN"):
            if request.method != "GET" and request.headers.get("x-csrf-token") != CSRF:
                return JSONResponse({"error": "csrf mismatch"}, status_code=401)
            return None
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    @app.post("/api/auth/login")
    async def login(request: Request) -> Response:
        body: dict[str, Any] = await request.json()
        st.calls.append("login")
        if body.get("username") != USERNAME or body.get("password") != PASSWORD:
            return JSONResponse({"error": "invalid credentials"}, status_code=401)
        if st.require_mfa:
            return JSONResponse({"errorCode": 499, "message": "Ubic MFA required"}, status_code=499)
        resp = JSONResponse({"unique_id": "fake", "username": USERNAME})
        resp.set_cookie("TOKEN", _jwt_with_csrf(CSRF), httponly=True)
        resp.headers["X-CSRF-Token"] = CSRF
        return resp

    # ------------------------------------------------- zone based policies

    @app.get("/proxy/network/v2/api/site/{site}/firewall-policies")
    async def list_policies(site: str, request: Request) -> Response:
        st.calls.append("list_policies")
        denied = authorised(request)
        if denied:
            return denied
        if site != SITE:
            return JSONResponse([], status_code=200)
        return JSONResponse(list(st.policies.values()))

    @app.put("/proxy/network/v2/api/site/{site}/firewall-policies/batch")
    async def batch_policies(site: str, request: Request) -> Response:
        st.calls.append("batch_policies")
        denied = authorised(request)
        if denied:
            return denied
        items = await request.json()
        updated = []
        for item in items:
            pid = item.get("_id")
            if pid in st.policies:
                st.policies[pid] = {**st.policies[pid], **item}
                updated.append(st.policies[pid])
        return JSONResponse(updated)

    @app.put("/proxy/network/v2/api/site/{site}/firewall-policies/{policy_id}")
    async def put_policy(site: str, policy_id: str, request: Request) -> Response:
        st.calls.append("put_policy")
        denied = authorised(request)
        if denied:
            return denied
        if st.item_put_status != 200:
            return JSONResponse({"error": "method not allowed"}, status_code=st.item_put_status)
        if policy_id not in st.policies:
            return JSONResponse({"error": "not found"}, status_code=404)
        st.policies[policy_id] = {**st.policies[policy_id], **await request.json()}
        return JSONResponse(st.policies[policy_id])

    # ------------------------------------------------------- traffic rules

    @app.get("/proxy/network/v2/api/site/{site}/trafficrules")
    async def list_traffic(site: str, request: Request) -> Response:
        st.calls.append("list_traffic")
        denied = authorised(request)
        if denied:
            return denied
        return JSONResponse(list(st.traffic_rules.values()))

    @app.put("/proxy/network/v2/api/site/{site}/trafficrules/{rule_id}")
    async def put_traffic(site: str, rule_id: str, request: Request) -> Response:
        st.calls.append("put_traffic")
        denied = authorised(request)
        if denied:
            return denied
        if rule_id not in st.traffic_rules:
            return JSONResponse({"error": "not found"}, status_code=404)
        st.traffic_rules[rule_id] = {**st.traffic_rules[rule_id], **await request.json()}
        return JSONResponse(st.traffic_rules[rule_id])

    # ------------------------------------- legacy v1 rest firewall rules

    @app.get("/proxy/network/api/s/{site}/rest/firewallrule")
    async def list_firewall(site: str, request: Request) -> Response:
        st.calls.append("list_firewall")
        denied = authorised(request)
        if denied:
            return denied
        return JSONResponse({"meta": {"rc": "ok"}, "data": list(st.firewall_rules.values())})

    @app.put("/proxy/network/api/s/{site}/rest/firewallrule/{rule_id}")
    async def put_firewall(site: str, rule_id: str, request: Request) -> Response:
        st.calls.append("put_firewall")
        denied = authorised(request)
        if denied:
            return denied
        if rule_id not in st.firewall_rules:
            return JSONResponse({"meta": {"rc": "error"}, "data": []}, status_code=404)
        st.firewall_rules[rule_id] = {**st.firewall_rules[rule_id], **await request.json()}
        return JSONResponse({"meta": {"rc": "ok"}, "data": [st.firewall_rules[rule_id]]})

    return app, st
