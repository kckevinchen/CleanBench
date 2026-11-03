"""Regression tests for durable history and independent store writers."""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.labeling.schema import Label, LabelStatus, LabelTarget
from src.labeling.store import LabelStore


def label(key, note=""):
    return Label(
        target=LabelTarget.CLUSTER,
        target_id=key,
        source="x.csv",
        row=0,
        column="name",
        status=LabelStatus.TP,
        annotator="reviewer",
        note=note,
    )


def write_process(path, number):
    store = LabelStore(path)
    for index in range(8):
        store.append(label(f"{number}-{index}", "evidence " * 2000))


def test_append_after_truncated_tail_survives_restart(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text('{"target_id":"interrupted')
    store = LabelStore(path)
    store.append(label("saved"))
    assert [r.target_id for r in LabelStore(path).all()] == ["saved"]
    assert path.read_text().startswith('{"target_id":"interrupted\n')


def test_append_after_valid_record_without_newline(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(label("first").model_dump_json())
    LabelStore(path).append(label("second"))
    assert [r.target_id for r in LabelStore(path).all()] == ["first", "second"]


def test_independent_stores_merge_before_their_own_append(tmp_path):
    path = tmp_path / "labels.jsonl"
    first, second = LabelStore(path), LabelStore(path)
    first.append(label("first"))
    second.append(label("second"))
    assert set(second.latest_by_target()) == {"first", "second"}
    first.append(label("third"))
    assert set(first.latest_by_target()) == {"first", "second", "third"}


def test_short_writes_are_completed(tmp_path, monkeypatch):
    original_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: original_write(fd, data[:17]))
    path = tmp_path / "labels.jsonl"
    LabelStore(path).append(label("complete", "a long review note" * 100))
    assert [r.target_id for r in LabelStore(path).all()] == ["complete"]


def test_failed_write_does_not_claim_a_saved_record(tmp_path, monkeypatch):
    original_write = os.write
    calls = 0

    def fail_mid_record(fd, data):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("simulated disk failure")
        return original_write(fd, data[:17])

    path = tmp_path / "labels.jsonl"
    store = LabelStore(path)
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", fail_mid_record)
        with pytest.raises(OSError):
            store.append(label("not-saved"))
    store.append(label("saved-later"))
    assert [r.target_id for r in LabelStore(path).all()] == ["saved-later"]


def test_threads_using_separate_instances_keep_full_history(tmp_path):
    path = tmp_path / "labels.jsonl"
    stores = [LabelStore(path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: stores[item % 4].append(label(str(item))), range(60)))
    assert len(LabelStore(path).all()) == 60


def test_process_writers_keep_large_records_intact(tmp_path):
    path = tmp_path / "labels.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=write_process, args=(path, index)) for index in range(3)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert len(LabelStore(path).all()) == 24
