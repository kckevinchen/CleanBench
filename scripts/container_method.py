"""Invoke one baseline container using the fresh-run command-plan contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ENV = [
    "CLEANBENCH_API_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_VERSION",
    "CLEANBENCH_API_TIMEOUT",
    "CLEANBENCH_MODEL_GPT41",
    "CLEANBENCH_MODEL_GPT52",
    "CLEANBENCH_MODEL_GPT55",
    "CLEANBENCH_MODEL_ASTRA",
    "CLEANBENCH_MODEL_WORKFLOWS",
]
AGENT_ENV = [
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "COPILOT_GITHUB_TOKEN",
    "CLEANBENCH_MODEL_CODEX",
    "CLEANBENCH_MODEL_COPILOT",
]
SECRET_NAMES = {"OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "CODEX_API_KEY", "COPILOT_GITHUB_TOKEN"}


def docker_command(
    spec,
    inputs,
    output,
    repetition,
    predictions="predictions.jsonl",
    execution="execution.json",
    check=False,
):
    command = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--init",
        "--security-opt=no-new-privileges",
        "--mount",
        f"type=bind,source={inputs.resolve()},target=/inputs,readonly",
        "--mount",
        f"type=bind,source={output.resolve()},target=/run/cleanbench",
    ]
    names = (
        API_ENV
        if spec["image"] in {"api", "cleanagent", "cocoon"}
        else AGENT_ENV
        if spec["image"] == "coding"
        else []
    )
    if spec["id"] == "codex":
        names = [name for name in names if "COPILOT" not in name]
    elif spec["id"] == "copilot":
        names = [
            name for name in names if name in {"COPILOT_GITHUB_TOKEN", "CLEANBENCH_MODEL_COPILOT"}
        ]
    if not names:
        command.extend(["--network", "none"])
    for name in names:
        if name in os.environ:
            command.extend(["--env", name])
        if name in SECRET_NAMES and os.environ.get(name + "_FILE"):
            path = Path(os.environ[name + "_FILE"]).resolve()
            if not path.is_file():
                raise ValueError("Missing credential file for " + name)
            target = "/run/secrets/" + name.lower()
            command.extend(
                [
                    "--mount",
                    f"type=bind,source={path},target={target},readonly",
                    "--env",
                    name + "_FILE=" + target,
                ]
            )
    if check:
        command.extend(["--entrypoint", "python"])
    command.append("cleanbench/" + spec["image"] + ":table3")
    if check:
        command.extend(
            ["-c", "from baselines.preflight import check; print(check(" + repr(spec["id"]) + "))"]
        )
    else:
        command.extend(
            [
                "--method",
                spec["id"],
                "--inputs",
                "/inputs",
                "--predictions",
                "/run/cleanbench/" + predictions,
                "--execution",
                "/run/cleanbench/" + execution,
                "--repetition",
                str(repetition),
            ]
        )
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", required=True)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--execution", required=True, type=Path)
    parser.add_argument("--repetition", required=True, type=int)
    args = parser.parse_args()
    specs = json.loads((ROOT / "docker/methods.json").read_text())
    output = args.predictions.resolve().parent
    if output != args.execution.resolve().parent:
        parser.error("Output files must share one run directory")
    output.mkdir(parents=True, exist_ok=True)
    spec = specs[args.method]
    image = "cleanbench/" + spec["image"] + ":table3"
    details = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[
        0
    ]
    (output / "container.json").write_text(
        json.dumps(
            {
                "image": image,
                "id": details["Id"],
                "digests": details.get("RepoDigests", []),
                "os": details["Os"],
                "architecture": details["Architecture"],
            },
            indent=2,
        )
        + "\n"
    )
    subprocess.run(
        docker_command(spec, args.inputs, output, args.repetition, check=True), check=True
    )
    subprocess.run(
        docker_command(
            spec, args.inputs, output, args.repetition, args.predictions.name, args.execution.name
        ),
        check=True,
    )


if __name__ == "__main__":
    main()
