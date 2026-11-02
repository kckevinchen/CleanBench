"""Discover annotation runs and maintain local folder metadata."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------


@dataclass
class RunInfo:
    """Thin summary of an on-disk run directory."""

    run_id: str  # directory name
    path: Path
    created: Optional[str]  # ISO timestamp (from mtime)
    model: Optional[str]
    mode: Optional[str]
    has_summary: bool
    has_clusters: bool
    has_report: bool
    has_labels: bool
    clusters: int = 0
    issues: int = 0
    dataset: Optional[str] = None  # short human label for the corpus
    n_sources: int = 0  # number of CSV files the run targeted
    normalize_input: bool = False  # ablation flag (text_normalize)
    # Run kind: "detection" (cleaning pipeline) | "relations" (schema
    # discovery). Inferred from artifacts on disk - run dirs predate
    # the "kind" concept so we don't rely on metadata.
    kind: str = "detection"
    # Relation-discovery runs only.
    has_relations: bool = False
    n_relations: int = 0
    n_passes: Optional[int] = None
    n_arms: Optional[int] = None
    n_saturated_arms: Optional[int] = None
    # Multi-table cross-sheet pass artifacts (only populated by
    # ``run_relation_discovery`` when --error-types includes
    # inter_table_inconsistency). Exposed so the runs list can show a
    # "Label MT" entry point.
    has_multi_table: bool = False
    n_multi_table_findings: int = 0
    # Web-verification artifacts (output of ``experiments.run_web_verify``).
    # Exposed so the runs list can flag which detection runs already
    # have web verifications and how many cells are covered.
    has_web_verifications: bool = False
    n_web_verifications: int = 0
    # Column-clusters (inconsistency error type) artifacts.
    # ``has_column_cluster_drafts``: did the LLM proposer
    # (``experiments.run_column_clustering``) write
    # ``column_cluster_drafts.jsonl``?  ``has_column_cluster_labels``:
    # did the labelling UI write any ``column_clusters.jsonl``
    # records? The runs dashboard shows a "Column board" link when
    # either is true; the counts let the UI render a badge.
    has_column_cluster_drafts: bool = False
    n_column_cluster_drafts: int = 0
    has_column_cluster_labels: bool = False
    n_column_cluster_labels: int = 0
    # Operator-editable sidecar metadata (``run_metadata.json``).
    # Empty defaults mean "no metadata written yet" - the runs
    # dashboard falls back to displaying just ``run_id`` and treats
    # the run as unstarred / unpinned. See ``_load_run_metadata``.
    display_name: str = ""
    starred: bool = False
    notes: str = ""
    # Virtual-folder membership. ``""`` means "unfiled" (the default).
    # Folders are purely an organisational grouping layer in the runs
    # dashboard - the run directory itself never moves on disk, so
    # run-id-keyed paths (labels, reports) stay valid. The set of folder
    # definitions lives in ``outputs/folders.json``; this field is the
    # per-run pointer into it (see ``_load_folders``).
    folder_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": str(self.path),
            "created": self.created,
            "model": self.model,
            "mode": self.mode,
            "has_summary": self.has_summary,
            "has_clusters": self.has_clusters,
            "has_report": self.has_report,
            "has_labels": self.has_labels,
            "clusters": self.clusters,
            "issues": self.issues,
            "dataset": self.dataset,
            "n_sources": self.n_sources,
            "normalize_input": self.normalize_input,
            "kind": self.kind,
            "has_relations": self.has_relations,
            "n_relations": self.n_relations,
            "n_passes": self.n_passes,
            "n_arms": self.n_arms,
            "n_saturated_arms": self.n_saturated_arms,
            "has_multi_table": self.has_multi_table,
            "n_multi_table_findings": self.n_multi_table_findings,
            "has_web_verifications": self.has_web_verifications,
            "n_web_verifications": self.n_web_verifications,
            "has_column_cluster_drafts": self.has_column_cluster_drafts,
            "n_column_cluster_drafts": self.n_column_cluster_drafts,
            "has_column_cluster_labels": self.has_column_cluster_labels,
            "n_column_cluster_labels": self.n_column_cluster_labels,
            "display_name": self.display_name,
            "starred": self.starred,
            "notes": self.notes,
            "folder_id": self.folder_id,
        }


# ---------------------------------------------------------------------------
# Operator-editable run metadata sidecar (``run_metadata.json``)
# ---------------------------------------------------------------------------
#
# Lives at ``outputs/<run_id>/run_metadata.json``. Holds fields the
# operator can edit from the runs dashboard so they can rename ("pin")
# runs without renaming the immutable timestamp-based directory and
# without losing the run-id used by labels.jsonl. Schema is
# deliberately tiny and forward-compatible: unknown keys are ignored
# on read so future fields don't break older readers, and missing
# files mean "no metadata" rather than an error.

_RUN_METADATA_FILE = "run_metadata.json"
_MAX_DISPLAY_NAME = 120
_MAX_NOTES = 2000
_MAX_FOLDER_ID = 64


def _load_run_metadata(run_dir: Path) -> Dict[str, Any]:
    """Read the sidecar; return empty dict for missing/corrupt files."""
    path = run_dir / _RUN_METADATA_FILE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("run_metadata.json parse fail for %s: %s", run_dir, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    dn = raw.get("display_name")
    if isinstance(dn, str):
        out["display_name"] = dn.strip()[:_MAX_DISPLAY_NAME]
    starred = raw.get("starred")
    if isinstance(starred, bool):
        out["starred"] = starred
    notes = raw.get("notes")
    if isinstance(notes, str):
        out["notes"] = notes[:_MAX_NOTES]
    folder_id = raw.get("folder_id")
    if isinstance(folder_id, str):
        out["folder_id"] = folder_id.strip()[:_MAX_FOLDER_ID]
    return out


def _save_run_metadata(run_dir: Path, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``meta`` into the sidecar and write atomically.

    Only known keys (``display_name``, ``starred``, ``notes``,
    ``folder_id``) are persisted. Returns the full post-merge metadata
    dict. Writes use a tmp-file + ``os.replace`` so a crashing server
    can't leave a half-written JSON behind.
    """
    current = _load_run_metadata(run_dir)
    merged: Dict[str, Any] = {
        "display_name": current.get("display_name", ""),
        "starred": bool(current.get("starred", False)),
        "notes": current.get("notes", ""),
        "folder_id": current.get("folder_id", ""),
    }
    if "display_name" in meta:
        dn = meta["display_name"] or ""
        if not isinstance(dn, str):
            raise ValueError("display_name must be a string")
        merged["display_name"] = dn.strip()[:_MAX_DISPLAY_NAME]
    if "starred" in meta:
        merged["starred"] = bool(meta["starred"])
    if "notes" in meta:
        nt = meta["notes"] or ""
        if not isinstance(nt, str):
            raise ValueError("notes must be a string")
        merged["notes"] = nt[:_MAX_NOTES]
    if "folder_id" in meta:
        fid = meta["folder_id"] or ""
        if not isinstance(fid, str):
            raise ValueError("folder_id must be a string")
        merged["folder_id"] = fid.strip()[:_MAX_FOLDER_ID]

    path = run_dir / _RUN_METADATA_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return merged


# ---------------------------------------------------------------------------
# Virtual folders registry (``outputs/folders.json``)
# ---------------------------------------------------------------------------
#
# Folders are an organisational grouping layer for the runs dashboard.
# They do NOT move run directories on disk - membership is a ``folder_id``
# string stored in each run's ``run_metadata.json`` sidecar (see above),
# and the folder *definitions* (id -> name + collapse state) live in a
# single ``outputs/folders.json`` registry. A run whose ``folder_id``
# doesn't match any live folder is treated as unfiled, so deleting a
# folder definition is enough to orphan its members back to "Unfiled".
# Schema is deliberately small and forward-compatible: unknown keys are
# dropped on read, a missing/corrupt file means "no folders".

_FOLDERS_FILE = "folders.json"
_MAX_FOLDER_NAME = 120

# Serialises the load->mutate->save of the (single, shared) folders.json
# registry. Sync FastAPI handlers run in a threadpool, so two folder
# mutations can overlap; without this lock the second writer's full-list
# overwrite would drop the first's change (lost update). Mirrors the
# JobManager's threading.Lock convention for shared on-disk state.
_FOLDERS_LOCK = threading.Lock()


def _normalise_folder(raw: Any) -> Optional[Dict[str, Any]]:
    """Coerce one stored folder record into a clean dict, or ``None``."""
    if not isinstance(raw, dict):
        return None
    fid = raw.get("id")
    if not isinstance(fid, str) or not fid.strip():
        return None
    name = raw.get("name")
    name = name.strip()[:_MAX_FOLDER_NAME] if isinstance(name, str) else ""
    created = raw.get("created")
    return {
        "id": fid.strip()[:_MAX_FOLDER_ID],
        "name": name,
        "created": created if isinstance(created, str) else None,
        "collapsed": bool(raw.get("collapsed", False)),
    }


def _load_folders(outputs_dir: Path) -> List[Dict[str, Any]]:
    """Read the folder registry; ``[]`` for a missing/corrupt file.

    Accepts either ``{"folders": [...]}`` or a bare ``[...]`` on disk so
    a hand-edited file in the older shape still loads. Order is preserved
    (newest folders are stored first by :func:`_add_folder`).
    """
    path = Path(outputs_dir) / _FOLDERS_FILE
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("folders.json parse fail for %s: %s", outputs_dir, exc)
        return []
    items = raw.get("folders") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for it in items:
        folder = _normalise_folder(it)
        if folder is None or folder["id"] in seen:
            continue
        seen.add(folder["id"])
        out.append(folder)
    return out


def _save_folders(outputs_dir: Path, folders: List[Dict[str, Any]]) -> None:
    """Atomically persist the folder registry (tmp-file + ``os.replace``)."""
    path = Path(outputs_dir) / _FOLDERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = [f for f in (_normalise_folder(it) for it in folders) if f]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"folders": cleaned}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _add_folder(outputs_dir: Path, name: str) -> Dict[str, Any]:
    """Create a new folder (newest-first) and return its record."""
    with _FOLDERS_LOCK:
        folders = _load_folders(outputs_dir)
        existing = {f["id"] for f in folders}
        fid = uuid.uuid4().hex[:12]
        while fid in existing:
            fid = uuid.uuid4().hex[:12]
        folder = {
            "id": fid,
            "name": (name or "").strip()[:_MAX_FOLDER_NAME],
            "created": datetime.now(timezone.utc).isoformat(),
            "collapsed": False,
        }
        folders.insert(0, folder)
        _save_folders(outputs_dir, folders)
        return folder


def _update_folder(
    outputs_dir: Path,
    folder_id: str,
    *,
    name: Optional[str] = None,
    collapsed: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Rename and/or set the collapse flag of one folder.

    Returns the updated record, or ``None`` if no folder matched.
    """
    with _FOLDERS_LOCK:
        folders = _load_folders(outputs_dir)
        target: Optional[Dict[str, Any]] = None
        for f in folders:
            if f["id"] == folder_id:
                target = f
                break
        if target is None:
            return None
        if name is not None:
            target["name"] = name.strip()[:_MAX_FOLDER_NAME]
        if collapsed is not None:
            target["collapsed"] = bool(collapsed)
        _save_folders(outputs_dir, folders)
        return target


def _remove_folder(outputs_dir: Path, folder_id: str) -> bool:
    """Drop a folder definition. Returns ``True`` if one was removed.

    Member runs are NOT touched here; an orphaned ``folder_id`` is
    treated as unfiled on read. Callers that want member rows to fall
    back into "Unfiled" cleanly should also clear each member's
    ``folder_id`` sidecar (the API layer does this).
    """
    with _FOLDERS_LOCK:
        folders = _load_folders(outputs_dir)
        kept = [f for f in folders if f["id"] != folder_id]
        if len(kept) == len(folders):
            return False
        _save_folders(outputs_dir, kept)
        return True


def dataset_label_from_config(cfg: Dict[str, Any]) -> Optional[str]:
    """Derive a short dataset/corpus label from a run's ``config`` block.

    Prefers the directory shared by *all* CSV paths since that's the
    corpus name (e.g. ``curated_pbi_500_dedup``); falls back to the
    basename for single-file runs. Returns ``None`` when the config
    carries no CSV path. Shared by the runs-list parser and the
    run-detail endpoint so both surfaces show the same label.
    """
    paths = cfg.get("csv_paths") or []
    # Directory-mode runs record the corpus directory directly.
    explicit_dir = cfg.get("csv_path")
    if explicit_dir:
        return Path(explicit_dir).name
    if not paths:
        return None
    if len(paths) > 1:
        # Multi-file runs: label by the directory common to *all* CSVs.
        # ``paths[0].parent`` is wrong for nested corpora that keep each
        # table in its own sub-dir (curated_pbi_500_dedup/<table>/<table>.csv
        # -> we want "curated_pbi_500_dedup", not the per-table "<table>").
        try:
            return Path(os.path.commonpath([str(p) for p in paths])).name
        except ValueError:
            # Mixed drives / relative paths -- fall back to first parent.
            return Path(paths[0]).parent.name
    return Path(paths[0]).name


def _parse_run_dir(path: Path) -> RunInfo:
    summary_path = path / "summary.json"
    clusters_path = path / "clusters.json"
    relations_path = path / "relations.jsonl"
    is_relations = relations_path.exists() or (path / "discovery_reports.json").exists()
    model: Optional[str] = None
    mode: Optional[str] = None
    clusters = 0
    issues = 0
    dataset: Optional[str] = None
    n_sources = 0
    normalize_input = False
    n_relations = 0
    n_passes: Optional[int] = None
    n_arms: Optional[int] = None
    n_saturated_arms: Optional[int] = None
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            cfg = data.get("config") or {}
            model = data.get("model") or cfg.get("model")
            mode = data.get("mode") or cfg.get("mode")
            issues = int(data.get("total_issues") or 0)
            # Authoritative cluster count from the pipeline summary. Using
            # it avoids json.loads-ing the (often multi-MB) clusters.json
            # array on every runs-list request -- that array parse was the
            # entire cost of a slow /api/runs (1.3 GB across ~150 runs).
            clusters = int(data.get("clusters_total") or 0)
            # Discovery summaries store top-level mode/model (single_pass /
            # adaptive) and per-pass / per-arm aggregates.
            if is_relations:
                n_relations = int(data.get("n_relations") or 0)
                n_sources = int(data.get("n_sources") or 0)
                n_passes = data.get("n_passes")
                n_arms = data.get("n_arms")
                n_saturated_arms = data.get("n_saturated_arms")
            # Derive a short dataset label from the run config. Prefer the
            # parent directory of the CSV path(s) since that's the corpus
            # name (e.g. "curated_bing21_grouped"); fall back to the basename.
            paths = cfg.get("csv_paths") or []
            dataset = dataset_label_from_config(cfg)
            if not is_relations:
                n_sources = int(cfg.get("source_count") or len(paths) or 0)
            ni = cfg.get("normalize_input")
            if isinstance(ni, dict):
                normalize_input = bool(ni.get("enabled"))
            else:
                normalize_input = bool(ni)
        except Exception as exc:  # noqa: BLE001
            logger.debug("summary.json parse fail for %s: %s", path, exc)
    # Fallback cluster count when summary.json lacked ``clusters_total``
    # (older runs / relation runs). Prefer a cheap line count of the
    # line-delimited clusters.jsonl; only parse the clusters.json array as
    # a last resort, since that array can be tens of MB.
    if not clusters:
        clusters_jsonl = path / "clusters.jsonl"
        if clusters_jsonl.exists():
            try:
                with clusters_jsonl.open("r", encoding="utf-8") as fh:
                    clusters = sum(1 for line in fh if line.strip())
            except OSError:
                pass
        if not clusters and clusters_path.exists():
            try:
                raw = json.loads(clusters_path.read_text(encoding="utf-8"))
                clusters = len(raw) if isinstance(raw, list) else 0
            except Exception:  # noqa: BLE001
                pass
    if is_relations and not n_relations and relations_path.exists():
        # Fallback: count lines in relations.jsonl when summary is absent.
        try:
            with relations_path.open("r", encoding="utf-8") as fh:
                n_relations = sum(1 for line in fh if line.strip())
        except OSError:
            pass
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        created = mtime.isoformat()
    except OSError:
        created = None

    # Multi-table cross-sheet artifacts. ``multi_table_violations.jsonl``
    # is one line per (sheet, row) per finding; many findings span 2+
    # rows, so we count UNIQUE violation_ids for the headline figure
    # (= number of distinct findings the user has to review).
    mt_path = path / "multi_table_violations.jsonl"
    has_multi_table = mt_path.exists()
    n_multi_table_findings = 0
    if has_multi_table:
        try:
            seen_vids: set = set()
            with mt_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    vid = rec.get("violation_id")
                    if vid:
                        seen_vids.add(vid)
            n_multi_table_findings = len(seen_vids)
        except OSError:
            pass

    # Web-verification artifact (``experiments.run_web_verify`` output).
    # JSON array of one record per gate-eligible cluster; we count the
    # length so the runs list can render a "verified N/M" badge.
    wv_path = path / "web_verifications.json"
    has_web_verifications = wv_path.exists()
    n_web_verifications = 0
    if has_web_verifications:
        try:
            wv_raw = json.loads(wv_path.read_text(encoding="utf-8"))
            if isinstance(wv_raw, list):
                n_web_verifications = len(wv_raw)
        except (OSError, ValueError):
            pass

    # Column-cluster labelling artifacts (inconsistency error type).
    # Drafts are written by ``experiments.run_column_clustering``;
    # labels are written by the labelling-UI POST endpoint. Both are
    # append-only JSONL where the latest record per (source, column)
    # wins, so the headline counts come from the de-duplicated set.
    ccd_path = path / "column_cluster_drafts.jsonl"
    has_column_cluster_drafts = ccd_path.exists()
    n_column_cluster_drafts = 0
    if has_column_cluster_drafts:
        try:
            seen: set = set()
            with ccd_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    src = rec.get("source")
                    col = rec.get("column")
                    if src is not None and col is not None:
                        seen.add((src, col))
            n_column_cluster_drafts = len(seen)
        except OSError:
            pass
    ccl_path = path / "column_clusters.jsonl"
    has_column_cluster_labels = ccl_path.exists()
    n_column_cluster_labels = 0
    if has_column_cluster_labels:
        try:
            seen2: set = set()
            with ccl_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    src = rec.get("source")
                    col = rec.get("column")
                    if src is not None and col is not None:
                        seen2.add((src, col))
            n_column_cluster_labels = len(seen2)
        except OSError:
            pass

    meta = _load_run_metadata(path)

    return RunInfo(
        run_id=path.name,
        path=path,
        created=created,
        model=model,
        mode=mode,
        has_summary=summary_path.exists(),
        has_clusters=clusters_path.exists(),
        has_report=(path / "report.html").exists(),
        has_labels=(path / "labels.jsonl").exists(),
        clusters=clusters,
        issues=issues,
        dataset=dataset,
        n_sources=n_sources,
        normalize_input=normalize_input,
        kind="relations" if is_relations else "detection",
        has_relations=is_relations,
        n_relations=n_relations,
        n_passes=n_passes,
        n_arms=n_arms,
        n_saturated_arms=n_saturated_arms,
        has_multi_table=has_multi_table,
        n_multi_table_findings=n_multi_table_findings,
        has_web_verifications=has_web_verifications,
        n_web_verifications=n_web_verifications,
        has_column_cluster_drafts=has_column_cluster_drafts,
        n_column_cluster_drafts=n_column_cluster_drafts,
        has_column_cluster_labels=has_column_cluster_labels,
        n_column_cluster_labels=n_column_cluster_labels,
        display_name=meta.get("display_name", ""),
        starred=bool(meta.get("starred", False)),
        notes=meta.get("notes", ""),
        folder_id=meta.get("folder_id", ""),
    )


class RunRegistry:
    """Lists detection-run directories under ``outputs/``."""

    def __init__(self, outputs_dir: Path) -> None:
        self.outputs_dir = Path(outputs_dir)

    def list(self) -> List[RunInfo]:
        if not self.outputs_dir.is_dir():
            return []
        runs: List[RunInfo] = []
        for child in sorted(self.outputs_dir.iterdir(), reverse=True):
            if not child.is_dir():
                continue
            # Heuristic: real runs have at least summary.json OR
            # clusters.json OR (for relation-discovery runs) relations.jsonl.
            if (
                not (child / "summary.json").exists()
                and not (child / "clusters.json").exists()
                and not (child / "relations.jsonl").exists()
            ):
                # Still include it if a job is currently writing - surface
                # the dir but mark artifacts absent.
                pass
            runs.append(_parse_run_dir(child))
        return runs

    def get(self, run_id: str) -> Optional[RunInfo]:
        path = self.outputs_dir / run_id
        if not path.is_dir():
            return None
        return _parse_run_dir(path)
