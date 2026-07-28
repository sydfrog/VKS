"""Tests for the VCDT seam.

These run without VCFDT, without a network, and without a depot. When real
output arrives (NEED 3.3), the parser cases here are the ones to extend.
"""

from __future__ import annotations

import asyncio

import pytest

from app.vcdt import (
    BundleType,
    FailureKind,
    MockVcdtAdapter,
    ProgressKind,
    Sku,
    classify_failure,
    human_bytes,
    parse_progress,
    strip_control,
)

# --------------------------------------------------------------------------
# Failure classification — Risk R5
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("ERROR: 401 Unauthorized", FailureKind.AUTH),
        ("the supplied download token has expired", FailureKind.AUTH),
        ("account is not entitled to this bundle", FailureKind.AUTH),
        ("write failed: No space left on device", FailureKind.DISK_FULL),
        ("Disk full while writing bundle", FailureKind.DISK_FULL),
        ("404 Not Found", FailureKind.NOT_FOUND),
        ("connection reset by peer", FailureKind.NETWORK),
        ("Temporary failure in name resolution", FailureKind.NETWORK),
        ("certificate verify failed", FailureKind.NETWORK),
        ("something nobody predicted", FailureKind.UNKNOWN),
    ],
)
def test_classify_failure(text: str, expected: FailureKind) -> None:
    assert classify_failure(text) is expected


def test_auth_wins_over_network_on_ambiguous_403() -> None:
    """A proxy 403 matches both patterns; auth is the actionable answer."""
    assert classify_failure("proxy returned 403 forbidden") is FailureKind.AUTH


# --------------------------------------------------------------------------
# Progress parsing — Risk R1
# --------------------------------------------------------------------------

def test_parses_percent_with_byte_counts() -> None:
    event = parse_progress("esx-installer.tar.gz  45% (4.1 GB / 9.0 GB)")
    assert event is not None
    assert event.percent == 45.0
    assert event.current_file == "esx-installer.tar.gz"
    assert event.bytes_total == int(9.0 * 1024**3)


def test_parses_raw_byte_pairs_and_derives_percent() -> None:
    event = parse_progress("vcenter.tar: 500/1000 bytes")
    assert event is not None
    assert event.percent == 50.0
    assert event.bytes_done == 500


def test_percent_is_clamped() -> None:
    event = parse_progress("weird.tar 150%")
    assert event is not None and event.percent == 100.0


def test_ordinary_log_lines_yield_no_progress() -> None:
    """Not an error — the caller records these as LOG so nothing is lost."""
    assert parse_progress("Connecting to depot.broadcom.com") is None
    assert parse_progress("") is None
    assert parse_progress("   ") is None


def test_unparseable_line_does_not_raise() -> None:
    """The core degradation rule from ORCHESTRATION.md §7.2."""
    for junk in ("\x00\x01\x02", "%%%%", "100%%%", "—" * 50, "\x1b[2K\x1b[1G"):
        parse_progress(junk)  # must not raise


def test_strips_ansi_and_carriage_returns() -> None:
    """A redrawing progress bar must reduce to its final state, not a wall of
    control codes. This is the Risk R1 fallback path."""
    line = "\x1b[2K\rdownloading 10%\rdownloading 55%\x1b[0m"
    assert strip_control(line) == "downloading 55%"

    event = parse_progress(line)
    assert event is not None and event.percent == 55.0


# --------------------------------------------------------------------------
# Mock adapter
# --------------------------------------------------------------------------

def test_catalog_shape() -> None:
    catalog = asyncio.run(MockVcdtAdapter(speed=1000).fetch_catalog())
    assert catalog.releases
    assert catalog.bundle_count > 0
    assert not catalog.partial

    vcf_910 = next(
        r for r in catalog.releases if r.version == "9.1.0" and r.sku is Sku.VCF
    )
    assert "ESX" in vcf_910.components()
    assert vcf_910.total_bytes > 0


def test_base_release_has_no_upgrade_bundles() -> None:
    catalog = asyncio.run(MockVcdtAdapter(speed=1000).fetch_catalog(["9.0.0"]))
    release = catalog.releases[0]
    assert all(b.bundle_type is BundleType.INSTALL for b in release.bundles)


def test_vvf_omits_vcf_only_components() -> None:
    catalog = asyncio.run(MockVcdtAdapter(speed=1000).fetch_catalog())
    vvf = next(r for r in catalog.releases if r.sku is Sku.VVF)
    assert "SDDC_MANAGER" not in vvf.components()
    assert "ESX" in vvf.components()


def test_unknown_version_returns_partial_not_empty() -> None:
    """Partial results beat an exception — a bad filter shouldn't lose the rest."""
    catalog = asyncio.run(
        MockVcdtAdapter(speed=1000).fetch_catalog(["9.0.2", "1.2.3"])
    )
    assert catalog.partial
    assert catalog.warnings
    assert catalog.releases


def _collect(adapter: MockVcdtAdapter, limit: int = 2):
    async def run():
        catalog = await adapter.fetch_catalog(["9.0.2"])
        bundles = catalog.releases[0].bundles[:limit]
        return [e async for e in adapter.download(bundles)]

    return asyncio.run(run())


def test_download_stream_completes() -> None:
    events = _collect(MockVcdtAdapter(speed=1000))
    assert events[0].kind is ProgressKind.STARTED
    assert events[-1].kind is ProgressKind.FINISHED
    assert any(e.kind is ProgressKind.FILE_DONE for e in events)
    assert all(0 <= e.percent <= 100 for e in events if e.percent is not None)


def test_download_without_measurable_progress_still_streams() -> None:
    """Risk R1's bad case: no percentages anywhere, but the run still works."""
    events = _collect(MockVcdtAdapter(speed=1000, emit_percent=False))
    assert events[-1].kind is ProgressKind.FINISHED
    progress = [e for e in events if e.kind is ProgressKind.PROGRESS]
    assert not progress
    assert any(e.kind is ProgressKind.LOG for e in events)


def test_auth_failure_reported_once_not_per_bundle() -> None:
    """Risk R5: one expired token must not become N identical red rows."""
    events = _collect(MockVcdtAdapter(speed=1000, fail_with=FailureKind.AUTH), limit=5)
    failures = [e for e in events if e.kind is ProgressKind.FAILED]
    assert len(failures) == 1
    assert failures[0].failure is FailureKind.AUTH


def test_mid_transfer_failure_stops_the_stream() -> None:
    events = _collect(
        MockVcdtAdapter(speed=1000, fail_with=FailureKind.DISK_FULL), limit=3
    )
    assert events[-1].kind is ProgressKind.FAILED
    assert events[-1].failure is FailureKind.DISK_FULL


def test_mock_failure_text_classifies_correctly() -> None:
    """Ties the two halves together: the mock's error strings must be
    classifiable by the real classifier, not just by the enum that made them."""
    for kind in (FailureKind.AUTH, FailureKind.DISK_FULL, FailureKind.NETWORK):
        events = _collect(MockVcdtAdapter(speed=1000, fail_with=kind), limit=3)
        failed = events[-1]
        assert classify_failure(failed.raw) is kind


# --------------------------------------------------------------------------
# Display helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "—"),
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (int(1.5 * 1024**3), "1.5 GB"),
        (int(2.25 * 1024**4), "2.2 TB"),
    ],
)
def test_human_bytes(value: int | None, expected: str) -> None:
    assert human_bytes(value) == expected
