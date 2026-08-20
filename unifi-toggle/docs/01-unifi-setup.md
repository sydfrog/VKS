# Part 1a: get an API key and the policy ID

You need one value from the UCG Ultra before anything else works:

* `UNIFI_API_KEY`, so the service can talk to the console

You also need to name the policy the widget toggles. You already know its name,
`Block Kids from Internet`, and the service accepts that directly, so the policy
ID is optional. Getting it anyway is worth the one command, because an ID keeps
working if you ever rename the policy.

## Why an API key and not your username and password

You said 2FA is required for access to your Ubiquiti network. That matters.

A username and password login to `/api/auth/login` returns HTTP 499 with an MFA
challenge, and a headless service has no way to answer it. There is no flag that
turns that off for a service.

An API key created on the console is a separate credential that is not subject
to the MFA prompt. That is what it is for. It is also revocable on its own, so
if the VM is ever compromised you revoke one key instead of rotating your
Ubiquiti account password.

The service does still support username and password login, and the code and
tests cover it, but only for a local console account with 2FA disabled. Use the
API key.

## Create the API key

1. On a computer on the same network, open `https://<udm-ip>` in a browser,
   for example `https://192.168.0.1`. Use the local address, not `unifi.ui.com`.
   The browser will warn about the certificate because the UCG Ultra signs its own.
   Continue past the warning.
2. Sign in. This is the point where you answer your 2FA prompt, by hand, once.
3. Open **Settings**, the gear icon.
4. Go to **Control Plane**, then **Integrations**.
5. Click **Create API Key**.
6. Give it a name such as `unifi-toggle`.
7. Copy the key immediately. The console shows it exactly once. If you lose it,
   delete the key and make another.

If your firmware puts this elsewhere, the other place it appears is the account
menu in the top right of the UniFi OS dashboard, under **Control Plane** and then
**Integrations**. The wording **Create API Key** is the same either way.

Keep the key somewhere safe for the next step. It goes into the env file on the
VM and nowhere else.

## Find the policy ID

You can skip this and set `UNIFI_POLICY_NAME="Block Kids from Internet"` in the
env file instead. Do that if you want to get running quickly. The trade off is
that renaming the policy in the UniFi UI later breaks the widget, whereas an ID
survives a rename.

To get the ID, ask the console. On the VM, after you have cloned this
repository:

```bash
cd unifi-toggle/middleware
UNIFI_HOST=192.168.0.1 UNIFI_API_KEY=<the-key-you-just-copied> scripts/probe-unifi.sh
```

Replace `192.168.0.1` with your UCG Ultra address and paste your real key.

It prints something like this:

```
Console: https://192.168.0.1   site: default

=== Firewall policies (Network 9.x zone based)
    https://192.168.0.1/proxy/network/v2/api/site/default/firewall-policies
    665f1c2a9b1e4a0001abcdef  disabled  Block Kids from Internet
    665f1c2a9b1e4a0001ffffff  enabled   Allow Return Traffic  [predefined, cannot be toggled]

=== Traffic rules
    https://192.168.0.1/proxy/network/v2/api/site/default/trafficrules
    none found

=== Legacy firewall rules
    https://192.168.0.1/proxy/network/api/s/default/rest/firewallrule
    none found

Copy the ID of the policy you want into UNIFI_POLICY_ID.
```

Find the line reading `Block Kids from Internet` and copy the long hex ID from
the start of it. That is `UNIFI_POLICY_ID`.

Two things to watch for:

* Anything marked `[predefined, cannot be toggled]` is a built in policy. The
  console will not let anyone edit it, and the service returns HTTP 409 if you
  point it at one. Pick a policy you created.
* If the script prints `HTTP 401` or `HTTP 403`, the API key was refused. Check
  that you pasted the whole key and that it has not been deleted.

### If the script cannot run yet

You can also read the ID out of the browser. In the Network application, open
your firewall policy for editing and look at the address bar. The long hex
string in the URL is the same ID. The script is the better source, because it
also tells you which of the three kinds of policy you have.

## Which API this uses, and why

As of UniFi Network 9.x the official Integrations API covers sites, devices,
clients and hotspot vouchers. It does not expose firewall policies or traffic
rules, so there is no supported endpoint that can toggle the rule you made in
the UI.

The service therefore calls the same internal endpoint the Network web UI calls,
`/proxy/network/v2/api/site/<site>/firewall-policies`. Your API key still
authenticates it, because UniFi OS validates the key at the proxy layer in front
of the Network application.

The practical consequence: this is an internal API, and a future Network release
could move it. If that happens you will see a clear error on `GET /status`
rather than a silent failure, because the service verifies the state actually
changed after every write. The service also understands traffic rules and legacy
firewall rules, and probes all three by default, so a policy of any of those
three shapes works without a config change.

## What goes where

| Value | Ends up in | Ever on the phone? |
| --- | --- | --- |
| UniFi API key | `/etc/unifi-toggle/unifi-toggle.env` on the VM | No |
| Policy name or ID | `/etc/unifi-toggle/unifi-toggle.env` on the VM | No |
| Bearer token | The env file, and `Config.kt` in the app | Yes |
| CA certificate | The VM, and `res/raw/unifi_toggle_ca.pem` | Yes, public part only |

Next: [docs/02-middleware.md](02-middleware.md)
