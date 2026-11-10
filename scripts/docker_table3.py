"""Build baseline images, check configurations, or run Table 3 through Docker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.container_method import docker_command


def plan(specs):
    return {
        "schema_version": 1,
        "methods": {
            name: {
                "command": [
                    "{python}",
                    "{repo}/scripts/container_method.py",
                    "--method",
                    name,
                    "--inputs",
                    "{inputs}",
                    "--predictions",
                    "{predictions}",
                    "--execution",
                    "{execution}",
                    "--repetition",
                    "{run}",
                ]
            }
            for name in specs
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "build", "check", "run", "plan", "replay"])
    parser.add_argument(
        "--method", action="append", help="Table 3 method name; repeat to select several"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/table3_docker")
    parser.add_argument("--counts-only", action="store_true")
    args = parser.parse_args()
    specs = json.loads((ROOT / "docker/methods.json").read_text())
    if args.method:
        missing = set(args.method) - specs.keys()
        if missing:
            parser.error("Unknown container method: " + ", ".join(sorted(missing)))
        specs = {m: specs[m] for m in args.method}
    if args.action == "list":
        for name, spec in specs.items():
            print(name + "\t" + spec["image"])
        return
    if args.action == "plan":
        print(json.dumps(plan(specs), indent=2))
        return
    subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, check=True)
    if args.action == "build":
        for target in sorted({s["image"] for s in specs.values()}):
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--target",
                    target,
                    "-f",
                    str(ROOT / "docker/Dockerfile"),
                    "-t",
                    "cleanbench/" + target + ":table3",
                    str(ROOT),
                ],
                check=True,
            )
        return
    if args.action == "replay":
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--target",
                "replay",
                "-f",
                str(ROOT / "docker/Dockerfile"),
                "-t",
                "cleanbench/replay:table3",
                str(ROOT),
            ],
            check=True,
        )
        args.output.mkdir(parents=True, exist_ok=True)
        command = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--mount",
            f"type=bind,source={args.output.resolve()},target=/results",
            "cleanbench/replay:table3",
            "--output",
            "/results",
        ]
        if args.counts_only:
            command.append("--counts-only")
        subprocess.run(command, check=True)
        return
    if args.action == "check":
        with tempfile.TemporaryDirectory(prefix="cleanbench-check-") as folder:
            for name, spec in specs.items():
                print(name, flush=True)
                subprocess.run(
                    docker_command(spec, Path(folder), Path(folder), 1, check=True), check=True
                )
        return
    # Plan contains only commands and paths, never API credentials.
    with tempfile.TemporaryDirectory(prefix="cleanbench-plan-") as folder:
        path = Path(folder) / "methods.json"
        path.write_text(json.dumps(plan(specs), indent=2) + "\n")
        command = [
            sys.executable,
            str(ROOT / "scripts/run_table3.py"),
            "--plan",
            str(path),
            "--output",
            str(args.output.resolve()),
        ]
        for name in specs:
            command.extend(["--method", name])
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
