"""Confine the original AutoGen code runner to one dirty table and its work files."""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


class IsolatedExecution:
    def __init__(self, dirty, work, limits, *, python=None):
        import sys

        self.dirty, self.work = Path(dirty).resolve(), Path(work).resolve()
        self.limits = limits
        self.python = python or Path(sys.executable)
        self.calls = 0
        # The outer inference container supplies the isolation boundary.
        Path("/input").mkdir(exist_ok=True)
        target = Path("/input/dirty.csv")
        if target.is_symlink():
            target.unlink()
        if target.exists():
            raise ValueError("Unexpected pre-existing /input/dirty.csv")
        target.symlink_to(self.dirty)

    def run(self, argv, *, cwd, capture_output, text):
        if Path(cwd).resolve() != self.work or not capture_output or not text:
            raise ValueError("Unexpected code-execution contract")
        self.calls += 1
        command = [
            "/usr/bin/prlimit",
            f"--as={self.limits['memory_limit_mb'] * 1024 * 1024}",
            f"--fsize={self.limits['file_limit_mb'] * 1024 * 1024}",
            f"--cpu={self.limits['code_timeout_seconds']}",
            "--",
            *map(str, argv),
        ]
        # API credentials are not inherited by generated Python programs.
        env = {
            "PATH": str(self.python.parent) + ":/usr/bin:/bin",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        return subprocess.run(
            command,
            cwd=self.work,
            capture_output=True,
            text=True,
            timeout=self.limits["code_timeout_seconds"],
            env=env,
        )

    def validate_filename(self, filename, work_dir):
        if Path(work_dir).resolve() != self.work:
            raise ValueError("Native code execution requested another working directory")
        if filename is not None:
            path = self.work / filename
            if path.is_symlink() or not path.resolve().is_relative_to(self.work):
                raise ValueError("Generated code filename escapes its code directory")

    @contextlib.contextmanager
    def install(self, autogen):
        """Replace process launch only; retain native parsing, file I/O and feedback."""
        from autogen import code_utils

        original_subprocess = code_utils.subprocess
        execution = self

        class UserProxy(autogen.UserProxyAgent):
            def run_code(self, code, **kwargs):
                filename = kwargs.get("filename")
                if filename is None:
                    lang = kwargs.get("lang", "python")
                    extension = "py" if lang.startswith("python") else lang
                    filename = f"tmp_code_{hashlib.md5(code.encode()).hexdigest()}.{extension}"
                execution.validate_filename(filename, kwargs.get("work_dir"))
                return super().run_code(code, **kwargs)

        code_utils.subprocess = SimpleNamespace(
            **{
                name: getattr(original_subprocess, name)
                for name in dir(original_subprocess)
                if not name.startswith("_") and name != "run"
            },
            run=self.run,
        )
        old_docker = os.environ.get("AUTOGEN_USE_DOCKER")
        # This assignment is executed at module scope by the original app.
        os.environ["AUTOGEN_USE_DOCKER"] = "False"
        try:
            yield UserProxy
        finally:
            code_utils.subprocess = original_subprocess
            if old_docker is None:
                os.environ.pop("AUTOGEN_USE_DOCKER", None)
            else:
                os.environ["AUTOGEN_USE_DOCKER"] = old_docker
