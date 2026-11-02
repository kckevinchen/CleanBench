"""Import, save, restart and export through the public API without cloud SDKs."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from src.labeling.app import create_app
from src.labeling.importing import import_run


def test_import_label_restart_and_export(tmp_path):
    sources = {"people.csv": "name,city\nAlex,Seattle\nSam,Seatle\n"}
    candidates = [
        {
            "source": "people.csv",
            "row": 1,
            "column": "city",
            "error_type": "typo",
            "suggested_value": "Seattle",
        }
    ]
    with TestClient(create_app(tmp_path, annotator="reviewer")) as client:
        response = client.post(
            "/api/import", json={"run_id": "demo", "sources": sources, "candidates": candidates}
        )
        assert response.status_code == 201
        detail = client.get("/api/runs/demo/clusters/import-000001").json()
        assert detail["cluster"]["row_values"]["city"] == "Seatle"
        assert detail["cluster"]["detections"][0]["corrected_value"] == {"city": "Seattle"}
        assert not (tmp_path / "outputs/demo/labels.jsonl").exists()
        response = client.post(
            "/api/runs/demo/labels",
            json={
                "target": "cluster",
                "target_id": "import-000001",
                "source": "people.csv",
                "row": 1,
                "column": "city",
                "status": "tp",
                "corrected_value": "Seattle",
            },
        )
        assert response.status_code == 200, response.text
    # Relative source paths make a workspace portable across directories.
    import shutil

    moved = tmp_path / "moved"
    shutil.copytree(tmp_path / "outputs", moved / "outputs")
    with TestClient(create_app(moved, annotator="reviewer2")) as client:
        response = client.get("/api/runs/demo/export/benchmark")
        assert response.status_code == 200
        records = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert len(records) == 1
        assert records[0]["corrected_value"] == "Seattle"
        assert records[0]["original_value"] == "Seatle"
        assert records[0]["annotators"] == ["reviewer"]
        bundle = client.get("/api/runs/demo/export/bundle")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert {"benchmark.jsonl", "benchmark.ignored.jsonl", "MANIFEST.txt"} <= set(
                archive.namelist()
            )


@pytest.mark.parametrize(
    "run_id,source,candidates",
    [
        ("../escape", "x.csv", None),
        ("demo", "../x.csv", None),
        ("demo", "x.csv", [{"source": "x.csv", "row": -1, "column": "name"}]),
        ("demo", "x.csv", [{"source": "x.csv", "row": True, "column": "name"}]),
        ("demo", "x.csv", [{"source": "x.csv", "row": 0, "column": "missing"}]),
    ],
)
def test_invalid_import_is_atomic(tmp_path, run_id, source, candidates):
    with pytest.raises(ValueError):
        import_run(tmp_path, run_id, {source: "name\nAlex\n"}, candidates)
    assert not (tmp_path / "outputs" / "demo").exists()


def test_import_never_overwrites_review(tmp_path):
    target = import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})
    (target / "labels.jsonl").write_text("existing history\n")
    with pytest.raises(ValueError, match="already exists"):
        import_run(tmp_path, "demo", {"x.csv": "name\nSam\n"})
    assert (target / "labels.jsonl").read_text() == "existing history\n"


def test_public_app_has_no_model_or_experiment_routes(tmp_path):
    app = create_app(tmp_path, annotator="reviewer")
    paths = set(app.openapi()["paths"])
    assert not any(
        "launcher" in p or "correction-jobs" in p or "suggest-corrections" in p for p in paths
    )
    path = "/api/runs/{run_id}/clusters/{cluster_id}/web-verification"
    assert "post" not in app.openapi()["paths"].get(path, {})
