"""Guards for the shell scripts.

These caught a real bug: probe-unifi.sh embedded a Python f-string containing
escaped double quotes, which is a SyntaxError before Python 3.12. It parsed
fine on the machine it was written on and would have failed on Debian 12 or
Ubuntu 22.04, in the one step the operator runs first.
"""

from __future__ import annotations

import ast
import re
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
