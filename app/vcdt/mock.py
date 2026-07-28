"""A fake VCFDT, so the rest of the application can be built and tested now.

The fixture mirrors the structure described in ORCHESTRATION.md §3A — SKUs,
versions, components, install/upgrade types — with plausible sizes. Values are
invented; only the *shape* is meant to be right.

`MockVcdtAdapter` also simulates the failure modes worth designing against:
expired tokens, disk exhaustion, network drops, and progress output that
carries no parseable percentage at all (Risk R1's bad case).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime

from .models import (
    Bundle,
    BundleType,
    Catalog,
    FailureKind,
    ProgressEvent,
    ProgressKind,
    Release,
    Sku,
)

_GB = 1024**3
_MB = 1024**2

#: (component, filename stem, size) per release. Roughly the shape of a VCF
#: install set — sizes are illustrative.
_COMPONENTS: tuple[tuple[str, str, int], ...] = (
    ("ESX", "esx-installer", 9 * _GB),
    ("VCENTER", "vcenter-appliance", 14 * _GB),
    ("NSX", "nsx-unified-appliance", 11 * _GB),
    ("SDDC_MANAGER", "sddc-manager-appliance", 7 * _GB),
    ("VCF_INSTALLER", "vcf-installer-appliance", 8 * _GB),
    ("SUPERVISOR", "supervisor-services", 2 * _GB),
    ("VKS", "vks-guest-cluster-images", 4 * _GB),
    ("VSAN", "vsan-hcl-and-tools", 512 * _MB),
    ("OPS", "vcf-operations-appliance", 6 * _GB),
)

_RELEASES: tuple[tuple[str, Sku, str], ...] = (
    ("9.1.0", Sku.VCF, "2026-03-17"),
    ("9.0.2", Sku.VCF, "2025-11-04"),
    ("9.0.1", Sku.VCF, "2025-08-19"),
    ("9.0.0", Sku.VCF, "2025-06-17"),
    ("9.0.2", Sku.VVF, "2025-11-04"),
)


def _build_catalog() -> tuple[Release, ...]:
    releases: list[Release] = []
    for version, sku, date in _RELEASES:
        bundles: list[Bundle] = []
        for component, stem, size in _COMPONENTS:
            # VVF is the smaller product line — it omits the VCF-only pieces.
            if sku is Sku.VVF and component in {"SDDC_MANAGER", "NSX", "VCF_INSTALLER"}:
                continue
            for btype in (BundleType.INSTALL, BundleType.UPGRADE):
                # 9.0.0 is a base release: nothing to upgrade from.
                if btype is BundleType.UPGRADE and version.endswith(".0.0"):
                    continue
                scale = 1.0 if btype is BundleType.INSTALL else 0.35
                bundles.append(
                    Bundle(
                        vcdt_ref=f"{sku.value}:{version}:{component}:{btype.value}",
                        filename=f"{stem}-{version}-{btype.value.lower()}.tar.gz",
                        component=component,
                        version=version,
                        sku=sku,
                        bundle_type=btype,
                        size_bytes=int(size * scale),
                        checksum=f"{abs(hash((version, component, btype))):064x}"[:64],
                        checksum_algo="sha256",
                        description=(
                            f"{component} {btype.value.lower()} bundle "
                            f"for {sku.value} {version}"
                        ),
                    )
                )
        releases.append(
            Release(
                version=version, sku=sku, bundles=tuple(bundles), release_date=date
            )
        )
    return tuple(releases)


class MockVcdtAdapter:
    """Satisfies `VcdtAdapter` without VCFDT present.

    Args:
        speed: multiplier on simulated transfer rate. Higher is faster; the
            test suite uses a large value to keep runs instant.
        emit_percent: when False, progress lines carry no percentage — the
            Risk R1 bad case, used to prove the UI degrades gracefully.
        fail_with: force a specific failure part-way through a download.
    """

    def __init__(
        self,
        *,
        speed: float = 1.0,
        emit_percent: bool = True,
        fail_with: FailureKind | None = None,
        seed: int | None = 7,
    ) -> None:
        self.speed = max(speed, 0.01)
        self.emit_percent = emit_percent
        self.fail_with = fail_with
        self._rng = random.Random(seed)
        self._releases = _build_catalog()

    async def probe(self) -> str:
        await asyncio.sleep(0.01 / self.speed)
        return "vcf-download-tool 9.1.0.0 (mock)"

    async def fetch_catalog(
        self, versions: Iterable[str] | None = None
    ) -> Catalog:
        await asyncio.sleep(0.05 / self.speed)
        wanted = set(versions) if versions else None
        releases = tuple(
            r for r in self._releases if wanted is None or r.version in wanted
        )
        warnings: tuple[str, ...] = ()
        partial = False
        if wanted:
            missing = wanted - {r.version for r in releases}
            if missing:
                partial = True
                warnings = tuple(f"no catalog entry for version {v}" for v in sorted(missing))
        return Catalog(
            releases=releases,
            fetched_at=datetime.now(UTC),
            partial=partial,
            warnings=warnings,
        )

    async def _download_one(
        self, bundle: Bundle, *, fail_at: float | None
    ) -> AsyncIterator[ProgressEvent]:
        total = bundle.size_bytes or 0
        yield ProgressEvent(
            kind=ProgressKind.STARTED,
            raw=f"Downloading {bundle.filename}",
            current_file=bundle.filename,
            bytes_total=total,
        )

        done = 0
        step = max(total // 20, 1)
        while done < total:
            await asyncio.sleep(0.02 / self.speed)
            done = min(done + step, total)
            fraction = done / total if total else 1.0

            if fail_at is not None and fraction >= fail_at:
                kind = self.fail_with or FailureKind.NETWORK
                yield ProgressEvent(
                    kind=ProgressKind.FAILED,
                    raw=_failure_line(kind, bundle.filename),
                    current_file=bundle.filename,
                    failure=kind,
                    message=_failure_line(kind, bundle.filename),
                )
                return

            if self.emit_percent:
                raw = (
                    f"{bundle.filename}  {fraction * 100:.0f}% "
                    f"({done / _GB:.1f} GB / {total / _GB:.1f} GB)"
                )
                yield ProgressEvent(
                    kind=ProgressKind.PROGRESS,
                    raw=raw,
                    current_file=bundle.filename,
                    bytes_done=done,
                    bytes_total=total,
                    percent=round(fraction * 100, 2),
                )
            else:
                # Risk R1's bad case: output with nothing measurable in it.
                yield ProgressEvent(
                    kind=ProgressKind.LOG,
                    raw=f"... still transferring {bundle.filename}",
                    current_file=bundle.filename,
                )

        yield ProgressEvent(
            kind=ProgressKind.FILE_DONE,
            raw=f"Completed {bundle.filename}",
            current_file=bundle.filename,
            bytes_done=total,
            bytes_total=total,
            percent=100.0,
        )

    async def _stream(self, bundles: list[Bundle]) -> AsyncIterator[ProgressEvent]:
        if self.fail_with is FailureKind.AUTH:
            # Auth fails before any transfer starts — the realistic ordering,
            # and the case that must not produce N identical per-bundle errors.
            yield ProgressEvent(
                kind=ProgressKind.FAILED,
                raw=_failure_line(FailureKind.AUTH, ""),
                failure=FailureKind.AUTH,
                message="depot rejected the download token",
            )
            return

        fail_index = self._rng.randrange(len(bundles)) if self.fail_with and bundles else None
        for index, bundle in enumerate(bundles):
            fail_at = self._rng.uniform(0.2, 0.8) if index == fail_index else None
            async for event in self._download_one(bundle, fail_at=fail_at):
                yield event
                if event.kind is ProgressKind.FAILED:
                    return

        yield ProgressEvent(
            kind=ProgressKind.FINISHED,
            raw=f"Downloaded {len(bundles)} bundle(s)",
            message=f"{len(bundles)} bundle(s) complete",
        )

    def download(self, bundles: Iterable[Bundle]) -> AsyncIterator[ProgressEvent]:
        return self._stream(list(bundles))


def _failure_line(kind: FailureKind, filename: str) -> str:
    """Error text shaped like a real tool's, so `classify_failure` is exercised
    against something other than the enum it is meant to produce."""
    return {
        FailureKind.AUTH: "ERROR: 401 Unauthorized - the supplied download token has expired",
        FailureKind.NETWORK: f"ERROR: connection reset by peer while fetching {filename}",
        FailureKind.DISK_FULL: f"ERROR: write failed: No space left on device ({filename})",
        FailureKind.NOT_FOUND: f"ERROR: 404 Not Found - no such bundle {filename}",
        FailureKind.CANCELLED: "Cancelled by operator",
        FailureKind.UNKNOWN: f"ERROR: unexpected failure handling {filename}",
    }[kind]
