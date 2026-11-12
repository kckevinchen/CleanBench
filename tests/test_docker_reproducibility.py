"""Contracts that prevent accidental scoring changes or credential/label exposure."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from baselines import api
from baselines.common import validate_changes
from scripts.container_method import AGENT_ENV, API_ENV, docker_command
from scripts.docker_table3 import plan
from scripts.run_table3 import validate_plan

ROOT = Path(__file__).resolve().parents[1]


def test_all_noncommercial_methods_have_concrete_commands():
    specs = json.loads((ROOT / "docker/methods.json").read_text())
    manifest = json.loads((ROOT / "reproducibility/table3/manifest.json").read_text())
    expected = {m["method"] for m in manifest["methods"]} - {"Excel", "Google Sheets"}
    assert set(specs) == expected and len(specs) == 19
    runs = validate_plan(plan(specs), manifest, list(specs))
    assert len(runs) == 57
    assert all(
        spec["command"][1] == "{repo}/scripts/container_method.py"
        for spec in plan(specs)["methods"].values()
    )


def test_container_receives_only_dirty_input_and_own_output(tmp_path, monkeypatch):
    for name in set(API_ENV + AGENT_ENV):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name + "_FILE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    cmd = docker_command(
        {"id": "gpt41", "image": "api"}, tmp_path / "inputs", tmp_path / "output", 1
    )
    assert "test-not-a-real-key" not in " ".join(cmd)
    assert "OPENAI_API_KEY" in cmd
    mounts = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--mount"]
    assert len(mounts) == 2 and mounts[0].endswith("target=/inputs,readonly")
    assert not any("benchmark" in m or "reproducibility" in m for m in mounts)


def test_file_secret_is_mounted_readonly_without_embedding_contents(tmp_path, monkeypatch):
    for name in set(API_ENV + AGENT_ENV):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name + "_FILE", raising=False)
    p = tmp_path / "key"
    p.write_text("test-not-a-real-key")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(p))
    cmd = docker_command({"id": "gpt41", "image": "api"}, tmp_path, tmp_path, 1)
    assert "test-not-a-real-key" not in " ".join(cmd)
    assert f"type=bind,source={p},target=/run/secrets/openai_api_key,readonly" in cmd
    assert "OPENAI_API_KEY_FILE=/run/secrets/openai_api_key" in cmd


def test_literal_strings_and_null_survive_adapter():
    rows = [["  A", "B"]]
    headers = ["first", "second"]
    issues = {
        "issues": [
            dict(row=0, column="first", observed="  A", corrected_value=""),
            dict(row=0, column="second", observed="B", corrected_value=None),
        ]
    }
    for issue in issues["issues"]:
        issue.update(error_type="typo", explanation="Test replacement", confidence="high")
    assert api.issues_to_changes(issues, headers, rows) == [
        dict(row=0, col=0, corrected_value=""),
        dict(row=0, col=1, corrected_value=None),
    ]
    issues["issues"][0]["observed"] = "A"
    with pytest.raises(ValueError, match="Observed"):
        api.issues_to_changes(issues, headers, rows)
    with pytest.raises(ValueError, match="Duplicate"):
        validate_changes([dict(row=0, col=0, corrected_value="x")] * 2, headers, rows)
    issues["issues"][0]["observed"] = "  A"
    issues["issues"][0]["error_type"] = "made_up_type"
    with pytest.raises(ValueError, match="Invalid error type"):
        api.issues_to_changes(issues, headers, rows)


@pytest.mark.parametrize("method,effort", [("gpt52", "none"), ("gpt55", "none"), ("astra", "low")])
def test_direct_models_preserve_responses_api_and_effort(tmp_path, monkeypatch, method, effort):
    dirty = tmp_path / "dirty.csv"
    dirty.write_text("Name\nhello\n")
    calls = []

    def create(**request):
        calls.append(request)
        return SimpleNamespace(
            status="completed",
            output_text='{"issues": []}',
            model_dump=lambda: {"status": "completed"},
        )

    monkeypatch.setattr(
        api, "client", lambda: SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    assert api.direct(method, dirty, tmp_path, 1) == {"changes": []}
    assert calls[0]["reasoning"] == {"effort": effort, "summary": "detailed"}
    assert json.loads(calls[0]["input"])["rows"] == [{"row": 0, "values": ["hello"]}]
    assert calls[0]["instructions"] == (ROOT / "baselines/prompts/api_run_01.txt").read_text()


def test_gpt41_omits_reasoning_parameter(tmp_path, monkeypatch):
    dirty = tmp_path / "dirty.csv"
    dirty.write_text("Name\nhello\n")
    calls = []

    def create(**request):
        calls.append(request)
        return SimpleNamespace(
            model_dump=lambda: {
                "choices": [{"finish_reason": "stop", "message": {"content": '{"issues": []}'}}]
            }
        )

    monkeypatch.setattr(
        api,
        "client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    assert api.direct("gpt41", dirty, tmp_path, 1) == {"changes": []}
    assert set(calls[0]) == {"model", "messages"}


def test_fixed_method_inputs_and_bridge_provenance_match():
    inputs = json.loads((ROOT / "baselines/config/input_hashes.json").read_text())
    for relative, expected in inputs.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for entry in json.loads((ROOT / "baselines/provenance.json").read_text()):
        assert (
            hashlib.sha256((ROOT / entry["destination"]).read_bytes()).hexdigest()
            == entry["destination_sha256"]
        ), entry["destination"]


def test_coding_agents_receive_only_their_own_credentials(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "COPILOT_GITHUB_TOKEN"):
        monkeypatch.setenv(name, "offline-test")
        monkeypatch.delenv(name + "_FILE", raising=False)
    codex = docker_command({"id": "codex", "image": "coding"}, tmp_path, tmp_path, 1)
    copilot = docker_command({"id": "copilot", "image": "coding"}, tmp_path, tmp_path, 1)
    assert "COPILOT_GITHUB_TOKEN" not in codex
    assert "OPENAI_API_KEY" not in copilot and "CODEX_API_KEY" not in copilot


def test_api_retry_keeps_both_attempts_and_stops_on_auth_failure(tmp_path, monkeypatch):
    calls = []

    def attempt(method, dirty, directory, repetition):
        calls.append(directory.name)
        if len(calls) == 1:
            raise ValueError("Malformed reply")
        return {"changes": []}

    monkeypatch.setattr(api, "direct_attempt", attempt)
    assert api.direct("gpt41", tmp_path / "dirty.csv", tmp_path, 1) == {"changes": []}
    assert calls == ["attempt_01", "attempt_02"]
    assert json.loads((tmp_path / "attempt_01/error.json").read_text())["kind"] == "ValueError"

    class AuthError(Exception):
        status_code = 401

    def rejected(*args):
        raise AuthError()

    monkeypatch.setattr(api, "direct_attempt", rejected)
    failed = tmp_path / "auth"
    failed.mkdir()
    with pytest.raises(AuthError):
        api.direct("gpt41", failed / "dirty.csv", failed, 1)
    assert not (failed / "attempt_02").exists()


def test_constraint_file_override_is_optional_and_mounted_readonly(tmp_path, monkeypatch):
    monkeypatch.delenv("CLEANBENCH_RULES_FILE", raising=False)
    spec = {"id": "nadeef", "image": "classical"}
    command = docker_command(spec, tmp_path, tmp_path, 1)
    assert not any(
        "constraint_rules" in part or "CLEANBENCH_RULES_FILE" in part for part in command
    )
    path = tmp_path / "local-rules.json"
    path.write_text('{"tables": {}}')
    monkeypatch.setenv("CLEANBENCH_RULES_FILE", str(path))
    command = docker_command(spec, tmp_path, tmp_path, 1)
    assert (
        f"type=bind,source={path},target=/run/cleanbench-inputs/constraint_rules.json,readonly"
        in command
    )
    assert "CLEANBENCH_RULES_FILE=/run/cleanbench-inputs/constraint_rules.json" in command
    assert path.read_text() not in " ".join(command)
    other = docker_command({"id": "symspell", "image": "spelling"}, tmp_path, tmp_path, 1)
    assert not any("constraint_rules" in part for part in other)


def test_rule_loader_checks_the_external_file_checksum(tmp_path, monkeypatch):
    from baselines import rules

    monkeypatch.delenv("CLEANBENCH_RULES_FILE", raising=False)
    bank = rules.load()
    assert len(bank["tables"]) == len(bank["input_rows_sha256"]) == 1000
    from baselines.runner import CONSTRAINTS

    assert all(set(table) == CONSTRAINTS for table in bank["tables"].values())
    path = tmp_path / "local-rules.json"
    path.write_text('{"tables": {}}')
    monkeypatch.setenv("CLEANBENCH_RULES_FILE", str(path))
    with pytest.raises(ValueError, match="do not match"):
        rules.load()
    monkeypatch.setattr(rules, "EXPECTED_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    assert rules.load() == {"tables": {}}
    path.write_text('{"tables": {"changed": {}}}')
    with pytest.raises(ValueError, match="do not match"):
        rules.load()


def test_missing_rule_override_does_not_silently_use_bundled_rules(tmp_path, monkeypatch):
    from baselines import rules

    monkeypatch.setenv("CLEANBENCH_RULES_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="Missing constraint rules"):
        rules.load()
    with pytest.raises(ValueError, match="CLEANBENCH_RULES_FILE"):
        docker_command({"id": "nadeef", "image": "classical"}, tmp_path, tmp_path, 1)
