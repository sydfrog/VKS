# One tap UniFi policy toggle

Enable and disable one fixed UniFi firewall policy from a home screen widget,
with no UniFi app and nothing to navigate.

Built for the gear you described:

| Item | Value |
| --- | --- |
| Gateway | UCG Ultra at 192.168.0.1, running UniFi OS |
| UniFi Network | 9.0 or newer |
| Phone to VM transport | HTTPS with a self signed certificate |
| Policy toggled | `Block Kids from Internet` |
| Ubiquiti account | 2FA is on, so the service authenticates with an API key |

## How it fits together

```
  Phone widget                 Linux VM                      UCG Ultra
  ------------                 --------                      -------
  [Enable] [Disable]  HTTPS    unifi-toggle service   HTTPS   UniFi Network
  bearer token        ----->   FastAPI on uvicorn     ----->  firewall policy
                               API key stays here
```

The phone only ever knows two things: the address of the VM and a bearer token.
Your UniFi API key never leaves the VM, which is why a stolen or decompiled APK
cannot touch your network beyond flipping this one policy.

## Read these in order

1. [docs/01-unifi-setup.md](docs/01-unifi-setup.md)
   Create the API key and find the policy ID.
2. [docs/02-middleware.md](docs/02-middleware.md)
   Install the service on the VM, run it under systemd, test it end to end.
3. [docs/03-android.md](docs/03-android.md)
   Build the widget in Android Studio and sideload it.

Do not start part 3 until the smoke test in part 2 passes. If the middleware
is not toggling the policy, the widget cannot tell you anything useful.

## What is in here

```
middleware/
  unifi_toggle/          the FastAPI service
    config.py            environment parsing, fails loudly on bad input
    unifi.py             the UniFi client
    main.py              the HTTP endpoints and bearer auth
    __main__.py          entry point, "python -m unifi_toggle"
  systemd/
    unifi-toggle.service the unit file
  scripts/
    install.sh           installs the service, venv and unit file
    gen-token.sh         prints a random bearer token
    make-cert.sh         makes the CA and server certificate
    probe-unifi.sh       lists every policy ID on the console
    smoke-test.sh        exercises a running service
    local-e2e.sh         full test with a fake console, no UniFi needed
  tests/                 pytest suite, 65 tests
  unifi-toggle.env.example

android/
  app/src/main/java/com/homelab/unifitoggle/
    Config.kt            the only file you edit
    ToggleClient.kt      one HTTPS request per tap
    ToggleWidgetProvider.kt  the widget itself
  app/src/main/res/      layout, colours, network security config, CA
```

## The API surface

Every endpoint needs `Authorization: Bearer <API_TOKEN>`. There is no
unauthenticated route, health check included.

| Method | Path | Does |
| --- | --- | --- |
| GET | `/status` | Reports the policy's current enabled state |
| POST | `/enable` | Turns the policy on |
| POST | `/disable` | Turns the policy off |
| GET | `/healthz` | Liveness only, does not touch the console |

All three policy endpoints return the same JSON shape:

```json
{
  "policy_id": "665f1c2a9b1e4a0001abcdef",
  "name": "Block Kids from Internet",
  "enabled": true,
  "kind": "firewall-policy",
  "site": "default",
  "changed": true,
  "checked_at": "2026-08-20T04:32:58+00:00"
}
```

`changed` is false when the policy was already in the state you asked for, so
tapping Enable twice is safe and tells you the truth.

## Which policy it toggles

Set one of these in the env file on the VM:

* `UNIFI_POLICY_NAME="Block Kids from Internet"`, the name as it reads in the
  UniFi UI. Case and surrounding spaces are ignored. Quickest to set up.
* `UNIFI_POLICY_ID=665f...`, which survives renaming the policy in the UI.

The ID wins if both are set. If two policies share a name the service returns
409 and names both IDs rather than picking one, because guessing which rule
controls your kids' internet is not a thing it should do.

The service works with zone based firewall policies, traffic rules and legacy
firewall rules, and probes all three to find yours. On Network 9.x a rule like
this one is a firewall policy.

Failures return `{"error": "...", "hint": "..."}` with a real status code:
401 no token, 403 wrong token, 404 policy ID not on the console, 409 the policy
is predefined and cannot be edited, 502 the VM could not reach the console.
