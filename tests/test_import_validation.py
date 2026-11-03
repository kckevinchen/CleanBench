"""Import contracts must match across the API, CLI and source-table loader."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from src.labeling.app import create_app
from src.labeling.import_service import import_run
from src.labeling.run_cache import RunCache
from src.labeling.runs import RunRegistry
from src.labeling.workspace import RunAlreadyExists


@pytest.mark.parametrize("text", ["Name, Name \nx,y\n", 'name\n"unterminated\n', "name\nx\0y\n"])
def test_invalid_csv_leaves_no_run(tmp_path, text):
    with pytest.raises(ValueError):
        import_run(tmp_path, "demo", {"x.csv": text})
    assert not (tmp_path / "outputs/demo").exists()


def test_headers_rows_and_source_bytes_remain_aligned(tmp_path):
    text = " Name ,city\r\n Alex ,Seattle\r\n"
    run = import_run(tmp_path, "demo", {"x.csv": text})
    context = RunCache(tmp_path / "outputs").get("demo")
    assert context.load_frame("x.csv").iloc[0]["Name"] == "Alex"
    cluster = context.cluster("import-000001")
    assert cluster["columns"] == ["Name"] and cluster["row_values"] == {"Name": "Alex"}
    assert (run / "sources/x.csv").read_bytes() == text.encode()


def test_concurrent_imports_never_replace_the_first_run(tmp_path):
    def attempt(index):
        try:
            import_run(tmp_path, "demo", {"x.csv": f"name\nreview-{index}\n"})
            return index
        except RunAlreadyExists:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        winners = [index for index in pool.map(attempt, range(8)) if index is not None]
    assert len(winners) == 1
    assert (tmp_path / "outputs/demo/sources/x.csv").read_text() == f"name\nreview-{winners[0]}\n"
    assert not list((tmp_path / "outputs").glob(".import-*"))


def test_staging_and_unrelated_directories_are_not_runs(tmp_path):
    import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})
    staging = tmp_path / "outputs/.import-incomplete"
    staging.mkdir()
    (staging / "summary.json").write_text("{}")
    (tmp_path / "outputs/unrelated").mkdir()
    assert [run.run_id for run in RunRegistry(tmp_path / "outputs").list()] == ["demo"]


def test_api_rejects_ambiguous_input_and_reports_conflict(tmp_path):
    with TestClient(create_app(tmp_path, annotator="reviewer")) as client:
        payload = {"run_id": "demo", "sources": {"x.csv": "name\nAlex\n"}}
        assert client.post("/api/import", json=payload).status_code == 201
        assert client.post("/api/import", json=payload).status_code == 409
        for row in [True, "0", -1]:
            invalid = {
                **payload,
                "run_id": "invalid",
                "candidates": [{"source": "x.csv", "row": row, "column": "name"}],
            }
            assert client.post("/api/import", json=invalid).status_code == 422


@pytest.mark.parametrize("kind", ["missing-source", "malformed-json", "invalid-candidate"])
def test_cli_errors_are_actionable_without_tracebacks(tmp_path, kind):
    source = tmp_path / "x.csv"
    if kind != "missing-source":
        source.write_text("name\nAlex\n")
    command = [
        sys.executable,
        "-m",
        "src.labeling",
        "import",
        "--workspace",
        str(tmp_path / "workspace"),
        "--run-id",
        "demo",
        "--csv",
        str(source),
    ]
    if kind != "missing-source":
        candidate = tmp_path / "candidates.jsonl"
        candidate.write_text(
            "{broken\n" if kind == "malformed-json" else json.dumps({"row": True}) + "\n"
        )
        command.extend(["--candidates", str(candidate)])
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr
    if kind != "missing-source":
        assert "line 1" in result.stderr
