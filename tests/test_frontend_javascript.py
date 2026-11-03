"""Use Node's built-in parser/test runner without an npm dependency tree."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is optional for Python-only users")


def test_javascript_modules_parse():
    for source in (ROOT / "frontend").rglob("*.js"):
        result = subprocess.run(
            [NODE, "--input-type=module", "--check"],
            input=source.read_text(),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{source}: {result.stderr}"


def test_shared_http_and_escaping_utilities():
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests/frontend_utils.test.mjs")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
