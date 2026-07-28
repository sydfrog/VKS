# Your checklist

Everything I need from you, in order. Nothing else is blocking.

---

## 1. Build the VM

On your vSphere/VCF cluster — Ubuntu 24.04 LTS:

- [ ] 4 vCPU, 8 GB RAM
- [ ] 60 GB OS disk
- [ ] **Second disk, 1 TB, thin-provisioned** — this is the depot
- [ ] Network + SSH access

Full instructions, scripted and manual: `docs/linux-vm-build.md`

## 2. Prepare the host

```sh
ssh <you>@<vm>
git clone https://github.com/sydfrog/VKS.git && cd VKS

lsblk                                    # find the 1 TB disk — do NOT assume /dev/sdb
sudo ./scripts/setup-depot-host.sh --depot-device /dev/sdX --dry-run
sudo ./scripts/setup-depot-host.sh --depot-device /dev/sdX
```

- [ ] Ran it. **Send me the summary block it prints at the end.**

Installs Docker, mounts the depot, creates `/opt/vcdt` and `/etc/vcf-depot`.

## 3. Install VCFDT

From the Broadcom support portal:

```sh
sudo tar -xzf vcf-download-tool-*.tar.gz -C /opt/vcdt --strip-components=1
sudo chown -R "$USER" /opt/vcdt

printf '%s' 'YOUR-DOWNLOAD-TOKEN' > /etc/vcf-depot/token.txt
chmod 600 /etc/vcf-depot/token.txt
```

- [ ] VCFDT unpacked to `/opt/vcdt`
- [ ] Token in `/etc/vcf-depot/token.txt`

## 4. Capture its interface — the part that unblocks me

```sh
cd ~/VKS/vcdt-reference
./capture.sh /opt/vcdt/vcf-download-tool /srv/vcf-depot
```

- [ ] **Send me `capture-out/`**

Collects version, help text, subcommands, a catalog sample and the depot layout.

## 5. Capture a real download — the highest-value item

Start any download, let it run ~1 minute, Ctrl-C. Do it **both** ways:

```sh
cd ~/VKS/vcdt-container

./run.sh binaries download --vcf-version 9.0.2 --type INSTALL \
   --depot-download-token-file /etc/vcf-depot/token.txt \
   --depot-store /srv/vcf-depot 2>&1 | tee ~/progress-piped.txt

script -qc './run.sh binaries download --vcf-version 9.0.2 --type INSTALL \
   --depot-download-token-file /etc/vcf-depot/token.txt \
   --depot-store /srv/vcf-depot' ~/progress-tty.txt
```

- [ ] Send both files
- [ ] Send the tail of any failure you happen to hit (bad token, interrupted)

**If either file comes out empty or full of `\r` and escape codes, send it
anyway.** That is the answer, not a broken capture — it tells me whether a live
progress bar is buildable at all.

---

## Before sending anything

The repo is **public**. `capture.sh` scrubs credential-shaped patterns, but
skim the files first for site IDs, account references, internal hostnames.
If in doubt, paste into chat instead of committing.

**Never commit the VCFDT binary itself.**

---

## Decisions still open

All have defaults I'll use unless you say otherwise — reply "defaults are fine"
and that's a complete answer.

| | Question | Default |
|---|---|---|
| 4.1 | What's in v1 | Download + inventory + checksum verify |
| 4.3 | Login | Single admin user, token in a root-only file |
| 4.5 | Catalog | Cached, manual refresh button |
| 4.6 | Downloads | One at a time, queued |
| 4.7 | Selection | Release → component → bundle tree |

Already decided: Python/FastAPI, Docker Compose, VCDT in a container, Ubuntu VM
on vSphere.

---

## Meanwhile

I'm building against a mock VCFDT — job queue, runner, progress, selection
tree, inventory scanner, all five screens. Roughly two-thirds of the work needs
nothing from you. Steps 4 and 5 are what let me swap the mock for the real
thing.
