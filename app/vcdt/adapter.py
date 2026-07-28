"""The VCDT seam.

Every piece of VCFDT-specific knowledge lives behind `VcdtAdapter`. Swapping
the mock for the real implementation must not require a change anywhere else.

Design rule, from ORCHESTRATION.md §7.2: **parsers degrade, they do not raise.**
An unrecognised line is logged verbatim and the run continues. The failure mode
of a strict parser here is a job marked failed after successfully transferring
200 GB, which is far worse than an unstyled log line.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from typing import Protocol, runtime_checkable

from .models import Bundle, Catalog, FailureKind, ProgressEvent


@runtime_checkable
class VcdtAdapter(Protocol):
    """What the rest of the application is allowed to assume about VCFDT."""

    async def probe(self) -> str:
        """Return a version string. Raises if the tool is unusable."""
        ...

    async def fetch_catalog(
        self, versions: Iterable[str] | None = None
    ) -> Catalog:
        """Assemble a catalog.

        VCFDT's list command reportedly requires at least one filter, so this
        may issue several calls and merge them. Partial results are returned
        with `Catalog.partial` set rather than discarded.
        """
        ...

    def download(self, bundles: Iterable[Bundle]) -> AsyncIterator[ProgressEvent]:
        """Download bundles, yielding progress as it happens.

        Not `async def` — returns the iterator directly so callers can attach
        to the stream before the first event arrives.
        """
        ...


# --------------------------------------------------------------------------
# Output classification
#
# Shared by every adapter implementation, and the part most likely to need
# correction once real VCFDT output arrives. Written to be extended by adding
# patterns, not by restructuring.
# --------------------------------------------------------------------------

#: Ordered most-specific first — the first match wins.
_FAILURE_PATTERNS: tuple[tuple[FailureKind, re.Pattern[str]], ...] = (
    (
        FailureKind.AUTH,
        re.compile(
            r"\b(401|403|unauthor|forbidden|invalid token|token (has )?expired"
            r"|authentication fail|not entitled|entitlement)\b",
            re.I,
        ),
    ),
    (
        FailureKind.DISK_FULL,
        re.compile(r"\b(no space left|disk (is )?full|enospc|quota exceeded)\b", re.I),
    ),
    (
        FailureKind.NOT_FOUND,
        re.compile(r"\b(404|not found|no such (bundle|version|component))\b", re.I),
    ),
    (
        FailureKind.NETWORK,
        re.compile(
            r"\b(connection (refused|reset|timed out)|timeout|unreachable"
            r"|temporary failure in name resolution|ssl|certificate|proxy)\b",
            re.I,
        ),
    ),
)


def classify_failure(text: str) -> FailureKind:
    """Map error output to a cause.

    Ordering matters: a proxy returning 403 on an auth failure would match both
    AUTH and NETWORK, and AUTH is the more actionable answer.
    """
    for kind, pattern in _FAILURE_PATTERNS:
        if pattern.search(text):
            return kind
    return FailureKind.UNKNOWN


#: Progress line shapes, tried in order. Each must expose named groups from
#: {percent, done, total, unit, file}. Real patterns get added once we have
#: genuine output (NEED 3.3); these cover the common CLI conventions.
_PROGRESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Downloading foo.tar  45% (1.2 GB / 2.7 GB)"
    re.compile(
        r"(?P<file>\S+)?\s*(?P<percent>\d{1,3}(?:\.\d+)?)\s*%"
        r"(?:\s*\(\s*(?P<done>[\d.]+)\s*(?P<unit>[KMGT]?i?B)\s*/\s*"
        r"(?P<total>[\d.]+)\s*[KMGT]?i?B\s*\))?",
        re.I,
    ),
    # "foo.tar: 1234567/7654321 bytes"
    re.compile(
        r"(?P<file>\S+)?[:\s]+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*bytes", re.I
    ),
)

_UNIT_SCALE = {
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024**2,
    "MIB": 1024**2,
    "GB": 1024**3,
    "GIB": 1024**3,
    "TB": 1024**4,
    "TIB": 1024**4,
}

#: Strips ANSI escapes and carriage returns. A redrawing progress bar reduces
#: to its final state rather than a wall of control codes — the Risk R1
#: fallback, and harmless when the output was plain to begin with.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def strip_control(line: str) -> str:
    """Reduce a terminal-rendered line to its last visible state."""
    line = _ANSI.sub("", line)
    if "\r" in line:
        line = line.rsplit("\r", 1)[-1]
    return line.rstrip("\n")


def _to_bytes(value: str, unit: str | None) -> int | None:
    try:
        scale = _UNIT_SCALE.get((unit or "B").upper(), 1)
        return int(float(value) * scale)
    except (TypeError, ValueError):
        return None


def parse_progress(line: str) -> ProgressEvent | None:
    """Extract progress from one line, or `None` if it carries none.

    `None` is not an error — most lines are ordinary logging. The caller
    records those as LOG events so nothing is lost.
    """
    clean = strip_control(line).strip()
    if not clean:
        return None

    for pattern in _PROGRESS_PATTERNS:
        m = pattern.search(clean)
        if not m:
            continue
        groups = m.groupdict()

        percent: float | None = None
        if groups.get("percent"):
            try:
                percent = max(0.0, min(100.0, float(groups["percent"])))
            except ValueError:
                percent = None

        done = total = None
        if groups.get("done") and groups.get("total"):
            unit = groups.get("unit")
            done = _to_bytes(groups["done"], unit)
            total = _to_bytes(groups["total"], unit)

        # A match with nothing extractable is not progress.
        if percent is None and done is None:
            continue

        # Derive whichever side is missing, when we can.
        if percent is None and done is not None and total:
            percent = round(done / total * 100, 2)

        from .models import ProgressKind  # local import avoids a cycle

        return ProgressEvent(
            kind=ProgressKind.PROGRESS,
            raw=clean,
            current_file=(groups.get("file") or None),
            bytes_done=done,
            bytes_total=total,
            percent=percent,
        )
    return None
