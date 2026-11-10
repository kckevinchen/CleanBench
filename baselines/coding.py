"""Run the pinned coding-agent CLIs on one isolated dirty-table work directory."""

from __future__ import annotations

import os
import shutil
import subprocess

import yaml

from baselines.api import issues_to_changes, secret
from baselines.common import ROOT, ConfigurationError, atomic_json, read_table, sha


def execute(agent, dirty, work):
    run_dir = work / "agent"
    run_dir.mkdir()
    shutil.copyfile(dirty, run_dir / "input.csv")
    shutil.copyfile(ROOT / "prompts/coding_error_types.txt", run_dir / "error_types.txt")
    task = yaml.safe_load((ROOT / "prompts/coding_agent_end_to_end.yaml").read_text())["task"]
    task = task.replace("/work/", str(run_dir) + "/")
    model = os.environ.get("CLEANBENCH_MODEL_" + agent.upper(), "gpt-6-astra")
    env = os.environ.copy()
    if agent == "codex":
        key = secret("CODEX_API_KEY") or secret("OPENAI_API_KEY")
        if not key:
            raise ValueError("Set CODEX_API_KEY or OPENAI_API_KEY")
        env["CODEX_API_KEY"] = key
        command = [
            "codex",
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "danger-full-access",
            "-m",
            model,
            "-c",
            'model_reasoning_effort="low"',
            "-c",
            'web_search="disabled"',
            "--disable",
            "multi_agent",
            "--json",
            task,
        ]
    else:
        token = secret("COPILOT_GITHUB_TOKEN")
        if not token:
            raise ValueError("Set COPILOT_GITHUB_TOKEN or COPILOT_GITHUB_TOKEN_FILE")
        env["COPILOT_GITHUB_TOKEN"] = token
        command = [
            "copilot",
            "--no-auto-update",
            "--model",
            model,
            "--reasoning-effort",
            "low",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-custom-instructions",
            "--disable-builtin-mcps",
            "--excluded-tools",
            "task",
            "--output-format",
            "json",
            "--no-color",
            "--usage-output-file",
            str(run_dir / "usage.json"),
            "-p",
            task,
        ]
    atomic_json(
        work / "cli.json",
        dict(
            agent=agent,
            model=model,
            effort="low",
            version=subprocess.check_output([agent, "--version"], text=True).strip(),
        ),
    )
    before = sha(run_dir / "input.csv")
    with (work / "events.jsonl").open("w") as log:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
    if completed.returncode:
        message = (work / "events.jsonl").read_text().lower()
        configuration_failures = (
            "invalid_api_key",
            "authentication failed",
            "not authenticated",
            "requires authentication",
            "model_not_found",
            "unknown model",
            "model is not supported",
            "not supported for this account",
            "could not authenticate",
            "no valid github token",
            "insufficient_quota",
        )
        if completed.returncode == 2 or any(x in message for x in configuration_failures):
            raise ConfigurationError("Check CLI credentials/model; see events.jsonl")
        raise RuntimeError(f"{agent} exited with {completed.returncode}; see events.jsonl")
    if sha(run_dir / "input.csv") != before:
        raise ValueError("Agent modified input.csv")
    headers, rows = read_table(dirty)
    return {"changes": issues_to_changes((run_dir / "predictions.json").read_text(), headers, rows)}
