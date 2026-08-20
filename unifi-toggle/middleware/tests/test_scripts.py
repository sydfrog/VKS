"""Guards for the shell scripts.

These caught a real bug: probe-unifi.sh embedded a Python f-string containing
escaped double quotes, which is a SyntaxError before Python 3.12. It parsed
fine on the machine it was written on and would have failed on Debian 12 or
Ubuntu 22.04, in the one step the operator runs first.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts").glob("*.sh"))
assert SCRIPTS, "no scripts found to check"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_shell_syntax_is_valid(script: Path):
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"{script.name}: {result.stderr}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_is_executable(script: Path):
    assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_embedded_python_parses(script: Path):
    """Any python3 -c '...' block has to be valid on the oldest supported Python.

    The repository targets 3.11, so this test running under 3.11 is the check.
    """
    text = script.read_text()
    blocks = re.findall(r"python3 -c '(.*?)'\n", text, re.S)
    for block in blocks:
        try:
            ast.parse(block)
        except SyntaxError as exc:
            pytest.fail(f"{script.name} embeds python that will not parse: {exc}")


def test_probe_script_has_no_fstring_backslash():
    """Directly pin the specific mistake, so it cannot come back unnoticed."""
    text = (Path(__file__).resolve().parents[1] / "scripts" / "probe-unifi.sh").read_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("print(f", "f\"")) or 'f"' in stripped:
            assert "\\" not in stripped, f"f-string with a backslash: {stripped}"


UNIT_FILE = Path(__file__).resolve().parents[1] / "systemd" / "unifi-toggle.service"


def _systemd_analyze() -> str | None:
    return shutil.which("systemd-analyze")


@pytest.mark.skipif(_systemd_analyze() is None, reason="systemd-analyze not installed")
def test_systemd_unit_has_no_unknown_keys():
    """systemd ignores misplaced keys with only a warning, so treat it as an error.

    This caught StartLimitIntervalSec sitting in [Service], where systemd drops
    it and quietly applies the default give up limit of 5 starts per 10 seconds.
    The unit looked correct and behaved differently.
    """
    result = subprocess.run(
        [_systemd_analyze(), "verify", str(UNIT_FILE)],
        capture_output=True,
        text=True,
    )
    noise = result.stdout + result.stderr
    problems = [
        line
        for line in noise.splitlines()
        if line.strip()
        # Only present when the unit is checked off a real install.
        and "Unit configuration has fatal error" not in line
    ]
    assert not problems, "systemd-analyze verify reported:\n" + "\n".join(problems)


def _unit_sections(text: str) -> dict[str, list[str]]:
    """Split a unit file into sections, keeping only real directives.

    Comments are dropped. Splitting on the bare string "[Service]" would also
    match the word inside a comment, which is how the first version of this
    test managed to fail against a correct file.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def test_restart_limit_is_disabled_in_the_unit_section():
    """Pin the placement, so it cannot drift back into [Service]."""
    sections = _unit_sections(UNIT_FILE.read_text())
    unit = sections["[Unit]"]
    service = sections["[Service]"]
    assert "StartLimitIntervalSec=0" in unit
    assert not [d for d in service if d.startswith("StartLimit")], (
        "StartLimit keys in [Service] are silently ignored by systemd"
    )


def test_unit_parser_ignores_comments():
    """Guard the helper above, since its first version was fooled by a comment."""
    sample = "[Unit]\n# mentions [Service] in a comment\nStartLimitIntervalSec=0\n\n[Service]\nType=simple\n"
    sections = _unit_sections(sample)
    assert sections["[Unit]"] == ["StartLimitIntervalSec=0"]
    assert sections["[Service]"] == ["Type=simple"]


def test_unit_restarts_on_failure():
    text = UNIT_FILE.read_text()
    assert "Restart=on-failure" in text
    assert "WantedBy=multi-user.target" in text


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_make_cert_reuses_ca_across_reissue(tmp_path):
    """Reissuing the server cert must not change the CA.

    A fresh CA on every run silently invalidates the certificate pinned in the
    Android app, which showed up as a trust anchor error on every widget tap.
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "make-cert.sh"
    out = tmp_path / "tls"

    def ca_fingerprint() -> str:
        result = subprocess.run(
            ["openssl", "x509", "-in", str(out / "ca.crt"), "-noout",
             "-fingerprint", "-sha256"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def server_san() -> str:
        result = subprocess.run(
            ["openssl", "x509", "-in", str(out / "server.crt"), "-noout",
             "-ext", "subjectAltName"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    subprocess.run(["bash", str(script), "192.168.0.5", str(out)],
                   capture_output=True, text=True, check=True)
    first_ca = ca_fingerprint()
    assert "192.168.0.5" in server_san()

    # Reissue for a different address in the same directory.
    subprocess.run(["bash", str(script), "192.168.0.99", str(out)],
                   capture_output=True, text=True, check=True)
    assert ca_fingerprint() == first_ca, "reissuing the server cert changed the CA"
    assert "192.168.0.99" in server_san(), "server SAN was not updated"

    # The reissued server cert still chains to the unchanged CA.
    verify = subprocess.run(
        ["openssl", "verify", "-CAfile", str(out / "ca.crt"), str(out / "server.crt")],
        capture_output=True, text=True,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_make_cert_force_new_ca_rotates(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "make-cert.sh"
    out = tmp_path / "tls"

    def ca_fingerprint() -> str:
        return subprocess.run(
            ["openssl", "x509", "-in", str(out / "ca.crt"), "-noout",
             "-fingerprint", "-sha256"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    subprocess.run(["bash", str(script), "192.168.0.5", str(out)],
                   capture_output=True, text=True, check=True)
    before = ca_fingerprint()
    subprocess.run(["bash", str(script), "192.168.0.5", str(out)],
                   capture_output=True, text=True, check=True,
                   env={**os.environ, "FORCE_NEW_CA": "1"})
    assert ca_fingerprint() != before, "FORCE_NEW_CA=1 did not rotate the CA"


# App widgets may only use a fixed set of view classes. A bare <View> or other
# unsupported tag makes Android fail to inflate the widget with "Couldn't add
# widget", which cannot be caught by an XML well-formedness check. This guard
# scans the widget layouts for anything outside the allowed set.
ANDROID_RES = (
    Path(__file__).resolve().parents[2]
    / "android" / "app" / "src" / "main" / "res"
)

# The classic RemoteViews-supported classes, which are safe on every supported
# Android version. Deliberately conservative.
ALLOWED_WIDGET_VIEWS = {
    "FrameLayout", "LinearLayout", "RelativeLayout", "GridLayout",
    "AnalogClock", "Button", "Chronometer", "ImageButton", "ImageView",
    "ProgressBar", "TextView", "ViewFlipper", "ListView", "GridView",
    "StackView", "AdapterViewFlipper",
}


def _widget_layout_files() -> list[Path]:
    xml_dir = ANDROID_RES / "xml"
    layout_dir = ANDROID_RES / "layout"
    if not xml_dir.is_dir():
        return []
    layouts: set[Path] = set()
    for info in xml_dir.glob("*widget_info.xml"):
        m = re.search(r'initialLayout="@layout/(\w+)"', info.read_text())
        if m:
            layouts.add(layout_dir / f"{m.group(1)}.xml")
    return sorted(p for p in layouts if p.is_file())


@pytest.mark.skipif(not ANDROID_RES.is_dir(), reason="android resources not present")
def test_widget_layouts_use_only_supported_views():
    import xml.etree.ElementTree as ET

    files = _widget_layout_files()
    assert files, "no widget layouts discovered from *widget_info.xml"
    problems: list[str] = []
    for f in files:
        root = ET.parse(f).getroot()
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1] if "}" in el.tag else el.tag
            # Fully qualified custom views contain a dot; none are allowed here.
            if tag not in ALLOWED_WIDGET_VIEWS:
                problems.append(f"{f.name}: <{tag}> is not an app-widget-safe view")
    assert not problems, "unsupported views in widget layouts:\n" + "\n".join(problems)
