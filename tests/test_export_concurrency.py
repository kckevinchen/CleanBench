"""Downloads remain self-consistent while subsequent exports overwrite canonical files."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from src.labeling.app import create_app
from src.labeling.export_service import download_transaction
from src.labeling.file_io import atomic_path
from src.labeling.import_service import import_run
from src.labeling.run_cache import RunCache


def test_atomic_file_failure_keeps_existing_content(tmp_path):
    target = tmp_path / "benchmark.jsonl"
    target.write_text("complete")
    with pytest.raises(OSError):
        with atomic_path(target) as temporary:
            temporary.write_text("partial")
            raise OSError("simulated failure")
    assert target.read_text() == "complete"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.anyio
async def test_delayed_download_keeps_its_own_version(tmp_path):
    directory = import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})

    @download_transaction(RunCache(tmp_path / "outputs"))
    def export(run_id: str, content: str):
        path = directory / "export.jsonl"
        path.write_text(content)
        return FileResponse(path, filename="benchmark.jsonl")

    first, second = export("demo", "first"), export("demo", "second")
    assert first.path.read_text() == "first"
    assert second.path.read_text() == "second"
    await first.background()
    await second.background()
    assert not list(directory.glob(".download-*"))


def test_concurrent_api_downloads_are_complete_and_cleaned_up(tmp_path):
    directory = import_run(tmp_path, "demo", {"x.csv": "name\nAlex\n"})
    with TestClient(create_app(tmp_path, annotator="reviewer")) as client:
        response = client.post(
            "/api/runs/demo/labels",
            json={
                "target": "cluster",
                "target_id": "import-000001",
                "source": "x.csv",
                "row": 0,
                "column": "name",
                "status": "tp",
                "corrected_value": "Alexander",
            },
        )
        assert response.status_code == 200

        def download(index):
            kind = ["benchmark", "bundle", "sources", "benchmark-by-type"][index % 4]
            response = client.get(f"/api/runs/demo/export/{kind}")
            assert response.status_code == 200, response.text
            if kind == "benchmark":
                assert json.loads(response.text)["corrected_value"] == "Alexander"
            else:
                import zipfile

                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    assert archive.testzip() is None

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download, range(16)))
    assert not list(directory.rglob("*.tmp"))
    assert not list(directory.glob(".download-*"))
