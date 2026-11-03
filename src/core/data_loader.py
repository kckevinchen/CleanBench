"""Read annotation CSVs with consistent header and whitespace normalization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def _drop_duplicate_columns(
    columns: Sequence[str],
) -> Tuple[List[str], List[int], List[str]]:
    """Collapse duplicate column names by keeping only the FIRST occurrence.

    Returns ``(unique_names, keep_indices, dropped_names)``:

    * ``unique_names``: deduplicated list, preserving first-occurrence order.
    * ``keep_indices``: positions in the input list to keep (one per name in
      ``unique_names``); callers use this to project the matching DataFrame.
    * ``dropped_names``: distinct duplicate labels that were collapsed,
      sorted alphabetically (for logging).

    Rationale: after whitespace-stripping headers, two columns that looked
    distinct in the raw file (e.g. ``"Total"`` and ``"Total "``) can
    collide. Suffixing them as ``Total`` / ``Total.1`` keeps both but
    leaves the downstream pipeline guessing which is canonical. We prefer
    to drop the later occurrence(s) outright so callers always see a
    single, unambiguous column per name.
    """
    seen: set[str] = set()
    unique_names: List[str] = []
    keep_indices: List[int] = []
    dropped: set[str] = set()
    for i, c in enumerate(columns):
        if c in seen:
            dropped.add(c)
            continue
        seen.add(c)
        unique_names.append(c)
        keep_indices.append(i)
    return unique_names, keep_indices, sorted(dropped)


def load_csv(path: Path | str, **read_csv_kwargs) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    logger.info("Loading CSV: %s", path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, **read_csv_kwargs)
    stripped = [c.strip() for c in df.columns]
    unique_names, keep_indices, dropped = _drop_duplicate_columns(stripped)
    if dropped:
        logger.warning(
            "Duplicate column header(s) %s in %s; keeping first occurrence "
            "and dropping later duplicates.",
            dropped,
            path,
        )
        df = df.iloc[:, keep_indices].copy()
    df.columns = unique_names

    # Strip leading/trailing whitespace from every cell as a CSV
    # preprocessing step. Rationale: leading/trailing whitespace is
    # treated as a padding artefact of the CSV format, not a per-cell
    # defect, so we normalise it once at load time rather than asking
    # every downstream detector to handle it. Internal whitespace
    # (REPEATED INTERNAL SPACES, embedded newlines/tabs) is PRESERVED
    # verbatim, so detectors that DO care about it - `typo:whitespace`
    # for "James   Smith", `inconsistency` for embedded line breaks -
    # still see the signal.
    stripped_df = df.map(lambda s: s.strip() if isinstance(s, str) else s)
    n_trimmed = int(df.ne(stripped_df).to_numpy().sum())
    if n_trimmed:
        logger.info(
            "Stripped leading/trailing whitespace from %d cell(s) in %s",
            n_trimmed,
            path,
        )
    return stripped_df
