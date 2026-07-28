# Portable VCFDT runner

A container that runs the **VCF Download Tool** identically on a Linux host, a
Windows laptop, or a colleague's Mac — without anyone having to fight the
bundled Linux JRE.

## What this is not

**It does not contain VCFDT.** The image is a Linux userspace with a JRE and a
launcher; the tool itself is bind-mounted from the host at run time.

That is deliberate, not an oversight. VCFDT is licensed Broadcom software, and
shipping it inside an image you pass around is redistribution. What you share
with colleagues is **this directory** — three small files. Each person supplies
their own VCFDT download and their own depot token.

It also means the image doesn't go stale: when Broadcom ships a new VCFDT, you
replace `/opt/vcdt` on the host and rebuild nothing.

## Setup

**1. Get VCFDT** from the Broadcom support portal and unpack it on the host:

```sh
sudo mkdir -p /opt/vcdt
sudo tar -xzf vcf-download-tool-*.tar.gz -C /opt/vcdt --strip-components=1
sudo chown -R "$USER" /opt/vcdt
```

**2. Put your depot token where the container can read it:**

```sh
sudo mkdir -p /etc/vcf-depot && sudo chown "$USER" /etc/vcf-depot
chmod 750 /etc/vcf-depot
printf '%s' 'YOUR-TOKEN' > /etc/vcf-depot/token.txt
chmod 600 /etc/vcf-depot/token.txt
```

**3. Create the depot store:**

```sh
sudo mkdir -p /srv/vcf-depot && sudo chown "$USER" /srv/vcf-depot
```

**4. Run.** The image builds itself on first use:

```sh
./run.sh binaries --help
./run.sh binaries list --vcf-version 9.0.2 --sku VCF \
         --depot-download-token-file /etc/vcf-depot/token.txt
```

## Paths

Defaults match `docs/linux-vm-build.md`. Override per-invocation or export them:

| Variable | Default | Mounted at | Mode |
|---|---|---|---|
| `VCDT_DIR` | `/opt/vcdt` | `/opt/vcdt` | read-only |
| `DEPOT_DIR` | `/srv/vcf-depot` | `/srv/vcf-depot` | read-write |
| `CONF_DIR` | `/etc/vcf-depot` | `/etc/vcf-depot` | read-only |
| `VCDT_BIN` | auto-detected | — | set if the launcher isn't found |

```sh
VCDT_DIR=~/vcdt DEPOT_DIR=~/depot CONF_DIR=~/vcdt-conf ./run.sh binaries --help
```

**Paths inside commands are container paths.** Pass
`--depot-download-token-file /etc/vcf-depot/token.txt`, not the host path — they
coincide with the defaults above, which is why those defaults were chosen.

## Notes

**File ownership.** The image builds with your UID/GID, so files written into
the depot belong to you rather than root. If you move the depot between hosts
with different UIDs, rebuild: `docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t vcdt-runner .`

**Apple Silicon.** Pinned to `linux/amd64` because VCFDT's bundled JRE is
x86-64. It runs under emulation — slower, but it works, and it beats the
native-JRE workaround for portability.

**Proxies.** `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY` pass through from your
environment if set.

**TTY.** `run.sh` attaches a TTY when stdout is a terminal and drops it when
piped. That matters more than it looks: whether VCFDT renders a redrawing
progress bar or plain log lines when *not* attached to a terminal is the open
question behind Risk R1 in `../ORCHESTRATION.md`. Capture both:

```sh
./run.sh binaries download ... | tee progress-piped.txt      # no TTY
script -qc './run.sh binaries download ...' progress-tty.txt # with TTY
```

Send both. The difference is the answer.

## Sharing with colleagues

Give them this directory plus these three steps: install Docker, download
VCFDT from the portal, supply their own token. Nothing licensed changes hands.
