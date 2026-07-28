"""VCDT integration layer — the only package that knows what VCFDT looks like."""

from .adapter import VcdtAdapter, classify_failure, parse_progress, strip_control
from .mock import MockVcdtAdapter
from .models import (
    Bundle,
    BundleType,
    Catalog,
    FailureKind,
    ProgressEvent,
    ProgressKind,
    Release,
    Sku,
    human_bytes,
)

__all__ = [
    "Bundle",
    "BundleType",
    "Catalog",
    "FailureKind",
    "MockVcdtAdapter",
    "ProgressEvent",
    "ProgressKind",
    "Release",
    "Sku",
    "VcdtAdapter",
    "classify_failure",
    "human_bytes",
    "parse_progress",
    "strip_control",
]
