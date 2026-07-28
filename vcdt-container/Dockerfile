# Portable runner for the VCF Download Tool (VCFDT).
#
# This image deliberately does NOT contain VCFDT. Baking a licensed Broadcom
# binary into a distributable image is redistribution. Each user supplies their
# own VCFDT download and their own depot token, bind-mounted at run time.
#
# What the image provides: a known-good Linux userspace with a JRE, so VCFDT
# runs identically on a colleague's Mac, a Windows laptop, or the depot VM.
#
#   docker build -t vcdt-runner .
#   ./run.sh binaries list --vcf-version 9.0.2 --sku VCF
#
# Pinned to amd64: VCFDT ships a Linux x86-64 JRE. On Apple Silicon this runs
# under emulation — slower, but correct.
FROM --platform=linux/amd64 eclipse-temurin:21-jre-noble

# VCFDT bundles its own JRE, but that runtime is Linux-x86-64 only and is the
# usual source of "Exec format error". Providing a JRE here lets us override it
# via JAVA_HOME when the bundled one is unusable, and costs nothing when it is.

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl tree jq unzip less \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user whose UID is overridable at build time, so files
# written into the bind-mounted depot are owned by the caller, not by root.
# Mismatched ownership on the depot mount is the most common first-run failure.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" vcdt 2>/dev/null || true \
 && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash vcdt 2>/dev/null || true

# Mount points. Contents come from the host at run time — nothing licensed is
# ever committed into a layer.
#   /opt/vcdt      the VCFDT installation      (read-only)
#   /srv/vcf-depot the depot store             (read-write)
#   /etc/vcf-depot token file and config       (read-only)
RUN mkdir -p /opt/vcdt /srv/vcf-depot /etc/vcf-depot \
 && chown -R "${UID}:${GID}" /srv/vcf-depot

COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER vcdt
WORKDIR /srv/vcf-depot

ENV VCDT_HOME=/opt/vcdt
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
