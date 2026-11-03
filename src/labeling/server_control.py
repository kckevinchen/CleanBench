"""Manage one local background server with serialized lifecycle operations."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from filelock import FileLock, Timeout

from .__main__ import build_parser
from .file_io import atomic_write_text


class ServerControlError(RuntimeError):
    pass


class ServerController:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.logs = self.root / "logs"
        self.pid_file = self.logs / "workbench.pid"
        self.log_file = self.logs / "workbench.log"

    @staticmethod
    def process_identity(pid: int) -> str | None:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        identity = result.stdout.strip()
        fields = identity.split(None, 5)
        expected = f"{sys.executable} -m src.labeling serve"
        return (
            identity
            if result.returncode == 0
            and len(fields) == 6
            and (fields[5] == expected or fields[5].startswith(expected + " "))
            else None
        )

    def read_state(self) -> dict | None:
        try:
            value = json.loads(self.pid_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError as exc:
            raise ServerControlError(f"Cannot read server state: {self.pid_file}") from exc
        if type(value) is int and value > 0:
            # Allow stopping a server started by the previous shell launcher.
            return {"pid": value, "identity": self.process_identity(value)}
        if not isinstance(value, dict) or type(value.get("pid")) is not int or value["pid"] <= 0:
            raise ServerControlError(f"Invalid server state: {self.pid_file}")
        return value

    def running(self, state: dict | None) -> bool:
        return bool(
            state
            and state.get("identity")
            and self.process_identity(state["pid"]) == state["identity"]
        )

    def stop(self) -> None:
        state = self.read_state()
        if self.running(state):
            print(f"Stopping server (pid {state['pid']}).")
            try:
                os.kill(state["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 10
            while self.running(state):
                if time.monotonic() >= deadline:
                    raise ServerControlError(f"Server has not stopped yet; see {self.log_file}")
                time.sleep(0.1)
        else:
            print("Server is not running.")
        self.pid_file.unlink(missing_ok=True)

    def status(self) -> None:
        state = self.read_state()
        if self.running(state):
            print(f"Running (pid {state['pid']}). Log: {self.log_file}")
        else:
            print("Server is not running.")

    def start(self, options: list[str], parsed: argparse.Namespace) -> None:
        state = self.read_state()
        if self.running(state):
            raise ServerControlError(
                f"Server is already running (pid {state['pid']}); use restart or stop."
            )
        instance = uuid.uuid4().hex
        environment = {**os.environ, "CLEANBENCH_SERVER_INSTANCE": instance}
        command = [sys.executable, "-m", "src.labeling", "serve", *options]
        with self.log_file.open("ab", buffering=0) as log:
            process = subprocess.Popen(
                command,
                cwd=self.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(parsed.host, parsed.host)
        address = f"[{host}]" if ":" in host else host
        url = f"http://{address}:{parsed.port}/api/health"
        try:
            atomic_write_text(
                self.pid_file,
                json.dumps(
                    {
                        "pid": process.pid,
                        "identity": self.process_identity(process.pid),
                        "instance": instance,
                    }
                )
                + "\n",
            )
            deadline = time.monotonic() + 15
            # Local readiness probes must not be routed through an HTTP proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(url, timeout=0.5) as response:
                        ready = response.headers.get("X-CleanBench-Instance") == instance
                    if ready and process.poll() is None:
                        identity = self.process_identity(process.pid)
                        if identity is None:
                            continue
                        atomic_write_text(
                            self.pid_file,
                            json.dumps(
                                {
                                    "pid": process.pid,
                                    "identity": identity,
                                    "instance": instance,
                                }
                            )
                            + "\n",
                        )
                        print(
                            f"Started server (pid {process.pid}). Open http://{address}:{parsed.port}/"
                        )
                        print(f"Log: {self.log_file}")
                        return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.1)
            raise ServerControlError(f"Server failed its readiness check; see {self.log_file}")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            self.pid_file.unlink(missing_ok=True)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Start/restart accept --workspace, --annotator, --host and --port.",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("command", choices=["start", "stop", "restart", "status"])
    args, options = parser.parse_known_args(argv)
    if os.name == "nt":
        parser.error("Use python -m src.labeling serve on Windows.")
    parsed = (
        build_parser().parse_args(["serve", *options])
        if args.command in {"start", "restart"}
        else None
    )
    if parsed is None and options:
        parser.error("Server options apply only to start or restart.")
    controller = ServerController(args.project_root)
    try:
        controller.logs.mkdir(parents=True, exist_ok=True)
        with FileLock(str(controller.logs / "workbench.control.lock"), timeout=20):
            if args.command in {"stop", "restart"}:
                controller.stop()
            if args.command in {"start", "restart"}:
                controller.start(options, parsed)
            if args.command == "status":
                controller.status()
    except (ServerControlError, OSError, Timeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
