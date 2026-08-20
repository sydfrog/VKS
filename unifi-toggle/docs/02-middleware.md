# Part 1b: install and test the middleware

Everything here happens on the Linux VM. Commands assume Debian or Ubuntu. On
Fedora or RHEL swap `apt` for `dnf` and the package names are the same.

## What you need first

* The API key and policy ID from [part 1a](01-unifi-setup.md)
* The VM's LAN address, the one the phone will reach. Find it with:

```bash
ip -4 addr show scope global | grep inet
```

Write that address down. It is used three times: in the certificate, in the env
file, and in the Android app. This guide calls it `<vm-ip>`.

## 1. Install the prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv openssl curl git
```

## 2. Get the code and install the service

```bash
git clone <this-repository> unifi-toggle-src
cd unifi-toggle-src/unifi-toggle/middleware
sudo scripts/install.sh
```

`install.sh` is idempotent, so re-run it any time you pull a change. It:

* creates the `unifi-toggle` system user, with no shell and no home directory
* copies the app to `/opt/unifi-toggle` and builds a virtualenv there
* creates `/etc/unifi-toggle` owned by root, group readable by the service user
* installs the unit file and runs `systemctl daemon-reload`

It deliberately does not start the service, because the env file has no real
values in it yet.

## 3. Generate the bearer token

```bash
/opt/unifi-toggle/scripts/gen-token.sh
```

Copy the output. This one value goes in two places: the env file below, and
`Config.kt` in the Android app.

## 4. Generate the TLS certificate

Use the VM's LAN address, not `localhost` and not a name that is not in DNS:

```bash
sudo /opt/unifi-toggle/scripts/make-cert.sh <vm-ip> /etc/unifi-toggle/tls
sudo chown root:unifi-toggle /etc/unifi-toggle/tls/*
sudo chmod 0640 /etc/unifi-toggle/tls/server.key /etc/unifi-toggle/tls/ca.key
sudo chmod 0644 /etc/unifi-toggle/tls/ca.crt /etc/unifi-toggle/tls/server-fullchain.pem
```

This makes a small private CA and one server certificate signed by it. Android
pins trust anchors, and a trust anchor has to be a CA certificate, so a lone self
signed certificate is not enough. That is the only reason there are two.

The address you pass goes into the certificate's Subject Alternative Name.
Android ignores the Common Name entirely and checks only the SAN, so this has to
match what you put in `Config.kt` exactly. `https://192.168.1.50:8080` and
`https://myvm.local:8080` are not interchangeable.

You will copy `/etc/unifi-toggle/tls/ca.crt` to your workstation in part 3.
`ca.key` never leaves the VM.

## 5. Fill in the env file

```bash
sudo nano /etc/unifi-toggle/unifi-toggle.env
```

Set these five, leave the rest at their defaults:

```
API_TOKEN=<the token from step 3>
UNIFI_HOST=<your-udm-pro-ip>
UNIFI_API_KEY=<the API key from part 1a>
UNIFI_POLICY_ID=<the policy ID from part 1a>
TLS_CERT_FILE=/etc/unifi-toggle/tls/server-fullchain.pem
TLS_KEY_FILE=/etc/unifi-toggle/tls/server.key
```

`PORT` defaults to 8080 and `BIND_HOST` to 0.0.0.0, which is what you asked for.
Change `PORT` here if 8080 is taken.

Lock the file down:

```bash
sudo chown root:unifi-toggle /etc/unifi-toggle/unifi-toggle.env
sudo chmod 0640 /etc/unifi-toggle/unifi-toggle.env
```

Now only root can write it and only the service user can read it. systemd reads
it as root before dropping to the service user, so this works.

## 6. Start it

```bash
sudo systemctl enable --now unifi-toggle
sudo systemctl status unifi-toggle
```

`enable --now` does both things you want: enable makes it start on boot, and
now starts it immediately.

A healthy start looks like this in `systemctl status`:

```
● unifi-toggle.service - UniFi policy toggle middleware
     Loaded: loaded (/etc/systemd/system/unifi-toggle.service; enabled; preset: enabled)
     Active: active (running) since ...
```

The log line that tells you it actually reached your console:

```bash
journalctl -u unifi-toggle -n 20 --no-pager
```

```
unifi-toggle 1.0.0 ready. console=https://192.168.1.1 site=default auth=apikey policy=665f... kind=auto
resolved policy 665f1c2a9b1e4a0001abcdef as kind firewall-policy
startup probe found policy 'Block Kids Internet' (firewall-policy) currently disabled
```

If the probe fails the service still starts, on purpose. A restart loop would
just hide the error. The failure is reported on `GET /status` instead.

## 7. Test it end to end

This is the step to not skip.

```bash
sudo /opt/unifi-toggle/scripts/smoke-test.sh
```

It checks that an unauthenticated call is refused, that a wrong token is
refused, and then runs status, enable, status, disable, status against your real
console. Expected output:

```
--- unauthenticated GET /status should be 401
  HTTP 401

--- wrong token GET /status should be 403
  HTTP 403

--- GET /healthz
{"ok":true,"version":"1.0.0","checked_at":"..."}
  HTTP 200

--- GET /status (before)
{"policy_id":"665f...","name":"Block Kids Internet","enabled":false,...}
  HTTP 200

--- POST /enable
{...,"enabled":true,"changed":true,...}
  HTTP 200

--- GET /status (should be enabled true)
{...,"enabled":true,...}
  HTTP 200

--- POST /disable
{...,"enabled":false,"changed":true,...}
  HTTP 200

--- GET /status (should be enabled false)
{...,"enabled":false,...}
  HTTP 200

Smoke test finished. Check that enabled flipped true then false above.
```

Now confirm it in the UniFi UI. Open the Network application, find your policy,
and watch the enabled switch move while you run:

```bash
TOKEN=$(sudo grep '^API_TOKEN=' /etc/unifi-toggle/unifi-toggle.env | cut -d= -f2-)
curl -sk -X POST -H "Authorization: Bearer $TOKEN" https://<vm-ip>:8080/enable
curl -sk -X POST -H "Authorization: Bearer $TOKEN" https://<vm-ip>:8080/disable
```

Run those from another machine on the LAN, using the VM's real address. That
proves the whole path the phone will take, including that the VM's firewall is
letting port 8080 through.

Only move on to the Android app once you have seen the switch move in the UniFi
UI.

## Testing without touching your console

If you want to exercise the service without flipping a real policy, there is a
self contained run that starts a fake UniFi console and points a real instance of
the service at it:

```bash
cd unifi-toggle-src/unifi-toggle/middleware
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
scripts/local-e2e.sh
```

The unit tests run the same way:

```bash
.venv/bin/python -m pytest
```

## Opening the port

If the VM runs a firewall, let the phone in. With ufw:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8080 proto tcp
```

With firewalld:

```bash
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload
```

Do not forward this port from the internet. It is meant to be reachable from
your LAN or over a VPN, nothing more.

## Day to day commands

```bash
sudo systemctl status unifi-toggle      # is it running
sudo systemctl restart unifi-toggle     # after editing the env file
sudo systemctl stop unifi-toggle        # stop until next boot
sudo systemctl disable --now unifi-toggle   # stop and do not start on boot
journalctl -u unifi-toggle -f           # follow the log
journalctl -u unifi-toggle -n 100 --no-pager   # last 100 lines
```

The unit restarts on failure after 5 seconds, with no give up limit, so a
console reboot or a network blip recovers on its own.

## When something is wrong

Read the error and hint from `/status` first:

```bash
TOKEN=$(sudo grep '^API_TOKEN=' /etc/unifi-toggle/unifi-toggle.env | cut -d= -f2-)
curl -sk -H "Authorization: Bearer $TOKEN" https://127.0.0.1:8080/status
```

| What you see | What it means |
| --- | --- |
| `configuration error: ...` and the service will not start | A required variable is missing or malformed. The message names it. |
| HTTP 401 | No bearer token was sent. |
| HTTP 403 | The token does not match `API_TOKEN`. |
| HTTP 404, "policy not found" | Wrong `UNIFI_POLICY_ID`, or the right ID on a different site. Re-run `probe-unifi.sh`. |
| HTTP 409, "predefined" | You pointed it at a built in policy. Pick one you created. |
| HTTP 502, "UniFi denied" | The API key was refused. Re-check it in Control Plane, Integrations. |
| HTTP 502, "demanded a 2FA code" | It fell back to username and password login. Set `UNIFI_API_KEY` and clear `UNIFI_USERNAME` and `UNIFI_PASSWORD`. |
| HTTP 502, "cannot reach UniFi console" | Wrong `UNIFI_HOST`, or the VM cannot route to the UDM Pro. |

Auth failures and connectivity failures are reported as themselves, never as
"policy not found". If you see a 404 it really is the policy ID.

Next: [docs/03-android.md](03-android.md)
