"""Check exact corrections, retained populations, and independent command execution."""

import importlib.util
import json
import statistics
import sys
import zipfile
from pathlib import Path

import pytest

from src.reproducibility.table3 import compare, inside, metrics, score_run, summarize, verify


def script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reference():
    return {
        "population": {"tables": 1, "targets": 2, "clean_cells": 2},
        "tables": {"t": {"rows": 1, "columns": 5, "clean_cells": 2}},
        "targets": [
            {"dataset": "t", "row": 0, "col": 0, "accepted": [""]},
            {"dataset": "t", "row": 0, "col": 1, "accepted": ["City", "CITY"]},
        ],
        "immune": [["t", 0, 2]],
        "types": {
            "typo-spelling": [["t", 0, 0]],
            "typo-formatting": [["t", 0, 1]],
            "inconsistency": [["t", 0, 1]],
        },
    }


def prediction(col, value):
    return {"dataset": "t", "row": 0, "col": col, "corrected_value": value}


def test_exact_values_empty_strings_and_wrong_replacements(reference):
    counts = score_run(
        [
            prediction(0, ""),
            prediction(1, "city"),
            prediction(2, "immune"),
            prediction(3, "edit"),
            prediction(4, None),
        ],
        reference,
        {"t": "complete"},
    )
    assert (counts["t"]["tp"], counts["t"]["fp"], counts["t"]["fn"]) == (1, 2, 1)
    assert counts["t"]["fp_clean"] == 1
    values, totals = metrics(counts)
    assert values["f1"] == 40
    assert values["fpr"] == 50
    assert totals["targets"] == 2
    assert values["recall_inconsistency"] == 0


def test_failed_empty_table_preserves_false_negatives(reference):
    tables = score_run([], reference, {"t": "failed"})
    assert metrics(tables)[1]["fn"] == 2
    with pytest.raises(ValueError, match="every benchmark table"):
        score_run([], reference, {})


def test_duplicate_or_outside_coordinates_are_rejected(reference):
    with pytest.raises(ValueError, match="Duplicate"):
        score_run([prediction(0, ""), prediction(0, "")], reference, {"t": "complete"})
    with pytest.raises(ValueError, match="outside"):
        score_run([prediction(5, "")], reference, {"t": "complete"})


def test_run_means_and_sample_sd_are_not_pooled():
    from src.reproducibility.table3 import METRICS

    manifest = {
        "methods": [{"method": "m", "category": "c"}],
        "runs": [{"method": "m", "identity": str(i), "point_view": i == 1} for i in (1, 2, 3)],
    }
    observations = {
        str(i): dict.fromkeys(METRICS, value) for i, value in [(1, 10), (2, 40), (3, 100)]
    }
    row = summarize(manifest, observations, "variability")[0]
    assert row["f1"] == 50
    assert row["sd_f1"] == pytest.approx(statistics.stdev([10, 40, 100]))
    assert summarize(manifest, observations, "point")[0]["f1"] == 10


def test_artifact_paths_and_checksums_are_enforced(tmp_path):
    with pytest.raises(ValueError, match="inside"):
        inside(tmp_path, "../outside")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "sha256": {"a.json": "changed"}, "runs": []})
    )
    (tmp_path / "a.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        verify(tmp_path)


def test_dirty_inputs_follow_original_row_and_header_order(tmp_path):
    module = script("run_table3.py")
    archive = tmp_path / "sources.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("pool/input.csv", "other,value\nx,BAD\ny,GOOD\n")
        bundle.writestr(
            "_ROW_MAP.json",
            json.dumps({"sources": [{"source": "input.csv", "exported_to_source": [2, 5]}]}),
        )
    reference = {
        "tables": {
            "t": {
                "rows": 1,
                "columns": 1,
                "headers": ["value"],
                "source": "input.csv",
                "original_rows": [5],
            }
        }
    }
    output = tmp_path / "inputs"
    module.prepare_inputs(reference, archive, output)
    assert (output / "t/dirty.csv").read_text() == "value\nGOOD\n"
    assert {p.name for p in output.rglob("*") if p.is_file()} == {"dirty.csv", "_manifest.json"}


def test_full_runner_executes_a_fresh_command_and_rejects_reusing_trial(tmp_path, reference):
    module = script("run_table3.py")
    program = tmp_path / "cleaner.py"
    program.write_text(
        "import json, pathlib, sys\ninputs, predictions, execution = map(pathlib.Path, sys.argv[1:])\nassert inputs.is_dir()\npredictions.write_text(json.dumps({'dataset':'t','row':0,'col':0,'corrected_value':''})+'\\n')\nexecution.write_text(json.dumps({'t':'complete'}))\n"
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    plan = {
        "schema_version": 1,
        "methods": {
            "m": {
                "command": [
                    sys.executable,
                    str(program),
                    "{inputs}",
                    "{predictions}",
                    "{execution}",
                ]
            }
        },
    }
    manifest = {
        "methods": [{"method": "m", "category": "c"}],
        "runs": [{"identity": "m/run_01", "method": "m", "run": 1, "point_view": True}],
    }
    output = tmp_path / "fresh"
    result = module.run_plan(plan, manifest, reference, output, inputs)
    assert result["summaries"]["point"][0]["f1"] == pytest.approx(200 / 3)
    assert (
        json.loads((output / "methods/m/run_01/run_receipt.json").read_text())["status"]
        == "complete"
    )
    with pytest.raises(ValueError, match="already contains"):
        module.run_plan(plan, manifest, reference, output, inputs)


def test_comparison_reports_changed_values_and_population(tmp_path):
    from src.reproducibility.table3 import METRICS, write_csv

    row = {"method": "m", "repetitions": 1, **dict.fromkeys(METRICS, 50)}
    expected = tmp_path / "expected.csv"
    write_csv(expected, [row])
    assert compare([row], expected) == []
    different = {**row, "f1": 40}
    assert compare([different], expected)[0]["metric"] == "f1"
