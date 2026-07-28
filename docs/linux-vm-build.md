# Building the Linux VM for the VCF depot

Target: a VM on your vSphere/VCF cluster that runs both **VCFDT** (to capture
its interface, and later to do the real downloading) and the **depot manager**
web app.

Two paths below. The scripted one is reproducible and is what you want for the
real host; the manual one is fine if you just need something today.

---

## Sizing

| Resource | Recommendation | Why |
|---|---|---|
| vCPU | 4 | Downloads are I/O-bound; checksum verification is the only CPU burst. |
| RAM | 8 GB | Comfortable for the app, VCFDT's JVM, and page cache. 4 GB works. |
| OS disk | 60 GB | Root, container images, logs. |
| **Depot disk** | **separate VMDK, 1 TB thin** | The real question — see below. |
| Network | one NIC, static IP or DHCP reservation | SDDC Manager will point at this host later. |

**Give the depot its own disk.** A full depot must never be able to fill root
and take the OS down with it. Thin-provision it: you pay only for what lands.

**On depot size:** a single VCF release train runs to hundreds of GB, and you
will likely hold more than one version at a time. 1 TB thin is a sensible start
and can be grown online later. Once VCFDT runs, `binaries list` gives real
figures and you can size properly — the app's selection screen (§8) shows the
projected total before you commit to a download.

**Guest OS: Ubuntu 24.04 LTS.** Broad tooling, current Docker packages, easy
cloud-init. Commands below assume Ubuntu.

`scripts/setup-depot-host.sh` also supports the RHEL family — Rocky, AlmaLinux,
CentOS Stream and RHEL — so switching later is a different base image, not a
rewrite. Two differences it handles automatically there:

- **SELinux is enforcing**, so the depot and `/opt/vcdt` need
  `container_file_t` labels or every bind mount fails in a way that looks like
  a permissions bug. The script sets them persistently rather than using
  Docker's `:z` flag, which would relabel the whole depot on every run.
- **Docker CE has no packages for the newest CentOS Stream**, so the script
  falls back to `podman`, which ships natively there.

Note that **CentOS Linux itself is end-of-life** (7 ended June 2024, 8 in
2021). If you want the RHEL family, use CentOS Stream 10, Rocky, or AlmaLinux —
not CentOS 7/8.

---

## Path A — scripted with `govc` (recommended)

`govc` is a single Go binary, runs anywhere, and makes this repeatable.

### 1. Install govc and point it at vCenter

```sh
curl -L -o - "https://github.com/vmware/govmomi/releases/latest/download/govc_$(uname -s)_$(uname -m).tar.gz" \
  | tar -C /usr/local/bin -xvzf - govc

export GOVC_URL='vcenter.lab.local'
export GOVC_USERNAME='administrator@vsphere.local'
export GOVC_PASSWORD='...'          # or omit and let govc prompt
export GOVC_INSECURE=1              # drop this once certs are trusted
export GOVC_DATACENTER='Datacenter'
export GOVC_DATASTORE='vsanDatastore'
export GOVC_RESOURCE_POOL='Cluster/Resources'
export GOVC_NETWORK='VM Network'

govc about                          # confirm connectivity
```

Prefer not to put the password in your shell history — `govc` prompts if
`GOVC_PASSWORD` is unset.

### 2. Fetch the Ubuntu cloud image

```sh
curl -LO https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.ova
```

### 3. Write the cloud-init config

`metadata.yaml` — set a static IP here, or drop `ethernets` entirely for DHCP:

```yaml
instance-id: vcf-depot-01
local-hostname: vcf-depot-01
network:
  version: 2
  ethernets:
    ens192:
      dhcp4: true
      # For a static address, replace dhcp4 with:
      # addresses: [10.0.0.50/24]
      # routes: [{to: default, via: 10.0.0.1}]
      # nameservers: {addresses: [10.0.0.1]}
```

`userdata.yaml` — just the user and the base packages. Storage, Docker,
firewall and directory layout are handled afterwards by
`scripts/setup-depot-host.sh`, which is idempotent and refuses to format a disk
that already holds data. Doing it there rather than inline means a mistake is
recoverable by re-running a script, not by rebuilding the VM.

```yaml
#cloud-config
users:
  - name: depot
    groups: [sudo]
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...   # your public key

package_update: true
packages: [ca-certificates, curl, gnupg, git, tree, jq, unzip, xfsprogs, open-vm-tools]
```

### 4. Import and configure

```sh
govc import.ova -name=vcf-depot-01 ubuntu-24.04-server-cloudimg-amd64.ova

govc vm.change -vm vcf-depot-01 -c 4 -m 8192

# Depot disk, thin-provisioned
govc vm.disk.create -vm vcf-depot-01 -name vcf-depot-01/depot -size 1000G -thick=false

# Feed cloud-init through guestinfo
govc vm.change -vm vcf-depot-01 \
  -e guestinfo.metadata="$(base64 -w0 metadata.yaml)" \
  -e guestinfo.metadata.encoding="base64" \
  -e guestinfo.userdata="$(base64 -w0 userdata.yaml)" \
  -e guestinfo.userdata.encoding="base64"

govc vm.power -on vcf-depot-01
govc vm.ip vcf-depot-01
```

`base64 -w0` is GNU. On macOS use `base64 -i metadata.yaml` (no wrap flag).

### 5. Finish the host setup

```sh
ssh depot@<ip>
git clone https://github.com/sydfrog/VKS.git && cd VKS

lsblk                              # identify the depot disk — do not assume /dev/sdb
sudo ./scripts/setup-depot-host.sh --depot-device /dev/sdb --dry-run
sudo ./scripts/setup-depot-host.sh --depot-device /dev/sdb
```

The script installs Docker, formats and mounts the depot disk, creates
`/opt/vcdt` and `/etc/vcf-depot`, opens the firewall, and prints a summary
block to send back — that block is exactly NEED 3.6 in the orchestration file.

Run `--dry-run` first. It prints every action without taking any.

### 6. Verify

```sh
df -h /srv/vcf-depot     # depot disk mounted, right size
docker run --rm hello-world
```

---

## Path B — manual, via the vSphere Client

1. **Deploy OVF Template** → the Ubuntu cloud image OVA (or install from ISO).
2. 4 vCPU, 8 GB RAM, 60 GB OS disk. **Add a second disk**, 1 TB, thin.
3. Boot, log in, then run the same setup script as Path A step 5.

**`--depot-device` is required and never guessed.** `/dev/sdb` is the usual
name for a second disk but is not guaranteed; check `lsblk` first. The script
refuses to touch a device that is mounted or already carries a filesystem, and
asks you to retype the path before formatting — but the device you name is
still the device it formats.

---

## Just need to capture VCFDT today?

If the real VM is a while away and you only want the interface capture, any
Linux userspace will do — see `../vcdt-reference/README.md`. Fastest options:

```sh
# On any machine with Docker, an interactive Linux shell:
docker run -it --rm -v "$PWD:/work" -w /work ubuntu:24.04 bash

# Or a throwaway VM:
multipass launch 24.04 --name vcdt --disk 40G && multipass shell vcdt
```

Neither is the production host — they just need to run VCFDT long enough to
capture `--help` and a progress sample.

---

## What to record for me

After the build, run this and send the output — it fills §3.6 of the
orchestration file:

```sh
{
  echo "## os";     cat /etc/os-release | grep -E '^(NAME|VERSION)='
  echo "## arch";   uname -m
  echo "## depot";  df -h /srv/vcf-depot; ls -ld /srv/vcf-depot
  echo "## uid";    id
  echo "## docker"; docker --version; docker compose version
  echo "## proxy";  env | grep -iE '^(https?_proxy|no_proxy)=' || echo none
} 2>&1
```

The **UID:GID** matters most — it goes in the compose bind mount, and a mismatch
there is the classic first-run failure.

---

## Then

1. Download VCFDT from the Broadcom portal onto this VM, unpack to `/opt/vcdt`.
2. Build the portable runner: `vcdt-container/` (see its README).
3. Run `vcdt-reference/capture.sh` and send me the output.
4. I swap the mock adapter for the real one.
