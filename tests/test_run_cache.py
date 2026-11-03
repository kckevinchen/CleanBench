"""Run caches must observe replacements and respect workspace boundaries."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from src.labeling.app import create_app
from src.labeling.import_service import import_run
from src.labeling.run_cache import RunCache
from src.labeling.workspace import InvalidRunId


def test_replaced_artifact_invalidates_even_with_older_timestamp(tmp_path):
    directory = import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})
    cache = RunCache(tmp_path / "outputs")
    first = cache.get("demo")
    replacement = directory / "replacement.json"
    replacement.write_text("[]")
    os.utime(replacement, (1, 1))
    replacement.replace(directory / "clusters.json")
    assert cache.get("demo") is not first
    assert cache.get("demo").clusters == []


def test_cache_is_bounded_and_initializes_once(tmp_path):
    for name in ["one", "two", "three"]:
        import_run(tmp_path, name, {"x.csv": "name\nAlex\n"})
    cache = RunCache(tmp_path / "outputs", max_entries=2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        contexts = list(pool.map(cache.get, ["one"] * 8))
    assert all(context is contexts[0] for context in contexts)
    cache.get("two")
    cache.get("three")
    assert cache.get("one") is not contexts[0]


def test_corrupt_artifacts_are_visible_errors(tmp_path):
    directory = import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})
    (directory / "clusters.json").write_text("{broken")
    with TestClient(create_app(tmp_path, annotator="reviewer")) as client:
        response = client.get("/api/runs/demo/clusters")
        assert response.status_code == 409
        assert "clusters.json" in response.json()["detail"]
        assert client.get("/api/runs/missing/clusters").status_code == 404
        assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("identity", ["..", "../outside", "a/b", "a\\b", "a\0b"])
def test_invalid_run_ids_cannot_escape_outputs(tmp_path, identity):
    with pytest.raises(InvalidRunId):
        RunCache(tmp_path / "outputs").get(identity)
