"""Domain vocabulary for the depot manager.

Everything above the adapter layer speaks these types, never VCFDT's. When
Broadcom renames a flag or reshapes its output, the change is absorbed in
`adapter.py` and nothing here moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BundleType(StrEnum):
    """What a bundle is for. Mirrors VCFDT's `--type`."""

    INSTALL = "INSTALL"
    UPGRADE = "UPGRADE"
    PATCH = "PATCH"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, raw: str | None) -> BundleType:
        """Never raise on an unrecognised value — record it as UNKNOWN.

        A new bundle type appearing upstream must not break a catalog refresh.
        """
        if not raw:
            return cls.UNKNOWN
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class Sku(StrEnum):
    """Product line. Mirrors VCFDT's `--sku`."""

    VCF = "VCF"
    VVF = "VVF"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, raw: str | None) -> Sku:
        if not raw:
            return cls.UNKNOWN
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class Bundle:
    """One downloadable unit.

    `vcdt_ref` is the opaque handle the adapter needs to ask for this bundle
    again. Its shape is VCFDT's business; nothing above the adapter interprets
    it.
    """

    vcdt_ref: str
    filename: str
    component: str
    version: str
    sku: Sku
    bundle_type: BundleType
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_algo: str | None = None
    description: str = ""

    @property
    def size_display(self) -> str:
        return human_bytes(self.size_bytes)


@dataclass(frozen=True, slots=True)
class Release:
    """A VCF version, and everything downloadable under it."""

    version: str
    sku: Sku
    bundles: tuple[Bundle, ...] = ()
    release_date: str | None = None

    @property
    def total_bytes(self) -> int:
        return sum(b.size_bytes or 0 for b in self.bundles)

    def components(self) -> dict[str, list[Bundle]]:
        """Group bundles by component — the middle tier of the selection tree."""
        grouped: dict[str, list[Bundle]] = {}
        for b in self.bundles:
            grouped.setdefault(b.component, []).append(b)
        return grouped


@dataclass(frozen=True, slots=True)
class Catalog:
    """A point-in-time view of what the depot offers.

    `partial` matters: VCFDT's list command reportedly requires at least one
    filter, so a catalog is assembled from several calls. If any of them fail
    we still want the rest, clearly marked as incomplete rather than silently
    presented as the whole truth.
    """

    releases: tuple[Release, ...]
    fetched_at: datetime
    partial: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def bundle_count(self) -> int:
        return sum(len(r.bundles) for r in self.releases)


class ProgressKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    FILE_DONE = "file_done"
    LOG = "log"
    FINISHED = "finished"
    FAILED = "failed"


class FailureKind(StrEnum):
    """Why a run failed.

    Distinguishing these is what stops the UI showing fifty identical red rows
    when the real problem is one expired token (Risk R5).
    """

    AUTH = "auth"
    NETWORK = "network"
    DISK_FULL = "disk_full"
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One observation from a running download.

    Emitted as VCFDT produces output. `percent` and `bytes_done` are optional
    because we may not be able to extract them — see Risk R1. A consumer must
    render usefully with neither.
    """

    kind: ProgressKind
    raw: str = ""
    current_file: str | None = None
    bytes_done: int | None = None
    bytes_total: int | None = None
    percent: float | None = None
    failure: FailureKind | None = None
    message: str = ""

    @property
    def has_measurable_progress(self) -> bool:
        return self.percent is not None or self.bytes_done is not None


def human_bytes(n: int | None) -> str:
    """Format a byte count for display. `None` renders as an em dash."""
    if n is None:
        return "—"
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < step or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} TB"
