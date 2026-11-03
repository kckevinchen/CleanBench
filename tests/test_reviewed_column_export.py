"""Human column-board decisions must reach the unified benchmark and immunity sidecar."""

import json

import pytest
from fastapi.testclient import TestClient

from src.labeling.app import create_app
from src.labeling.import_service import import_run
from src.labeling.run_cache import RunCache
from src.labeling.schema import Label, LabelTarget, column_cluster_target_id


@pytest.mark.parametrize("override", [None, "fp", "partial", "unlabeled", "skip"])
def test_column_decisions_and_explicit_overrides(tmp_path, override):
    directory = import_run(tmp_path, "board", {"states.csv": "state\nWA\nWash.\n"}, [])
    with TestClient(create_app(tmp_path, annotator="column-reviewer")) as client:
        saved = client.post(
            "/api/runs/board/columns/states.csv/state/clusters",
            json={
                "source": "states.csv",
                "column": "state",
                "status": "labeled",
                "note": "",
                "drop_reason": "",
                "clusters": [
                    {
                        "cluster_id": "c1",
                        "kind": "text",
                        "canonical_value": "WA",
                        "values": [{"value": "WA", "count": 1}, {"value": "Wash.", "count": 1}],
                    }
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        assert not (directory / "labels.jsonl").exists()
        if override is not None:
            RunCache(tmp_path / "outputs").get("board").store.append(
                Label(
                    target=LabelTarget.COLUMN_CLUSTER,
                    target_id=column_cluster_target_id("states.csv", "state", "c1"),
                    source="states.csv",
                    column="state",
                    status=override,
                    annotator="cluster-reviewer",
                    value_corrections={"Wash.": "WA"} if override == "partial" else {},
                )
            )
        response = client.get("/api/runs/board/export/benchmark")
        assert response.status_code == 200, response.text
        records = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        if override in {None, "partial"}:
            assert len(records) == 1
            assert records[0]["row"] == 1 and records[0]["corrected_value"] == "WA"
            assert records[0]["annotators"] == [
                "column-reviewer" if override is None else "cluster-reviewer"
            ]
        else:
            assert records == []
        ignored = client.get("/api/runs/board/export/ignored")
        immunity = [json.loads(line) for line in ignored.text.splitlines() if line.strip()]
        assert len(immunity) == (2 if override == "skip" else 0)
