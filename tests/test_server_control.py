"""Exercise the real background-server lifecycle without touching a user's server."""

import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

import pytest

from src.labeling.server_control import ServerController

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Background helper is for Bash platforms")


def test_stale_state_never_signals_an_unrelated_process(tmp_path, monkeypatch):
    controller = ServerController(tmp_path)
    controller.logs.mkdir()
    controller.pid_file.write_text(json.dumps({"pid": os.getpid(), "identity": "another process"}))

    def forbidden_kill(*args):
        pytest.fail("Unrelated process must not be signaled")

    monkeypatch.setattr(os, "kill", forbidden_kill)
    controller.stop()
    assert not controller.pid_file.exists()


def test_serialized_lifecycle_and_real_readiness(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    for name in ["src", "frontend"]:
        (project / name).symlink_to(ROOT / name, target_is_directory=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = [sys.executable, "-m", "src.labeling.server_control", "--project-root", str(project)]
    options = [
        "--workspace",
        "review workspace",
        "--annotator",
        "lifecycle-test",
        "--port",
        str(port),
    ]

    def command(action, *extra):
        return subprocess.run(
            [*base, action, *extra],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "COLUMNS": "40"},
        )

    def healthy():
        with urlopen(f"http://127.0.0.1:{port}/api/runs", timeout=2) as response:
            payload = json.load(response)
        assert payload["project_root"] == str(project / "review workspace")
        assert payload["annotator"] == "lifecycle-test"

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            attempts = list(pool.map(lambda _: command("start", *options), range(3)))
        assert sum(result.returncode == 0 for result in attempts) == 1, attempts
        healthy()
        state = json.loads((project / "logs/workbench.pid").read_text())
        assert "Running" in command("status").stdout
        invalid = command("restart", "--port", "invalid")
        assert invalid.returncode == 2 and "Traceback" not in invalid.stderr
        assert json.loads((project / "logs/workbench.pid").read_text()) == state
        healthy()
        restarted = command("restart", *options)
        assert restarted.returncode == 0, restarted.stderr
        healthy()
        assert json.loads((project / "logs/workbench.pid").read_text())["pid"] != state["pid"]
        stopped = command("stop")
        assert stopped.returncode == 0, stopped.stderr
        assert not (project / "logs/workbench.pid").exists()
        assert "not running" in command("status").stdout
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy_port = occupied.getsockname()[1]
            failed = command("start", *options[:-1], str(busy_port))
            assert failed.returncode != 0
            assert not (project / "logs/workbench.pid").exists()
    finally:
        command("stop")
