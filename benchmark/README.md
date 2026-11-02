# Frozen CleanBench benchmark

The release includes 1,000 tables with 364,804 cells, **1,409 error cells**, and
**842 ambiguous cells**. Labels and accepted corrections are copied from the
frozen benchmark without relabeling or regeneration.

| File | Purpose |
|---|---|
| `benchmark_cell.json` | 2,251 cell-level JSONL records: 1,409 error and 842 ambiguous |
| `benchmark_row.json` | 46 additional row/relation/cross-table JSONL records: 25 error and 21 ambiguous |
| `ignored.jsonl` | 65 authoritative exclusion scopes |
| `neutral_cells.jsonl` | Legacy skip/exclusion annotations (empty-column skips are row-level) |
| `sanitized_sources.zip` | 1,000 source CSVs, source checksums, and original-row mapping |
| `release_manifest.json` | Artifact checksums, frozen provenance digest, and counts |
| `eval_cleanbench.py` | Standalone cell detection/correction scorer |

The row/relation annotations are supplementary; their counts are not added to
the 1,409 cell errors. The cell scorer does not evaluate row/relation tasks.
Files with `.json` in their name are JSONL, not JSON arrays.

## Cell schema

Each record identifies `(dataset, source, row, column)`:

- `dataset`: `pbi_500` (relational) or `bing21_500` (spreadsheet).
- `source`: the CSV basename, including `.csv`.
- `row`: original zero-based data-row number, excluding the header.
- `column`: column name; trim surrounding header whitespace when matching CSV headers.
- `original_value`: the observed cell value under the construction loader's whitespace handling.
- `status`: `error` or `ambiguous`.
- `error_types`: confirmed error categories; a cell can have several.
- `corrected_value`: a string, list of acceptable strings, or `null`.
- `explanation`: the frozen explanation associated with the reviewed decision.

Absence from the cell-label file means no labeled error under the exhaustive
review protocol, unless an immunity record applies. It is not an independent
per-cell certificate of cleanliness.

## Source tables and coordinates

Extract `sanitized_sources.zip` into `benchmark/sanitized_sources/`:

```bash
python -m zipfile -e benchmark/sanitized_sources.zip benchmark/sanitized_sources
```

The archive contains `pbi_500/` and `bing21_500/`, each with 500 CSVs,
`MANIFEST.json` with every source SHA-256 and shape, and `_ROW_MAP.json`.
For a mapped table, `exported_to_source[i]` is the original row for exported
data row `i`. Other tables use identity mapping. Keep these coordinates when
sharing predictions. Do not renumber frozen labels after extraction.

The source archive was assembled from the frozen source-table entries used by
the paper. It contains observed tables only: no model predictions, repaired
reference tables, training splits, or experiment results. Internal absolute
paths and experiment metadata are omitted.

## Cell scoring

```bash
python benchmark/eval_cleanbench.py --predictions predictions.jsonl
python benchmark/eval_cleanbench.py --predictions predictions.csv --task end_to_end
```

Predictions need `dataset`, `source`, `row`, and `column`. Correction scoring
also needs `corrected_value`; use `--corrected-col` for another field name.
Pass `--use-row-map` if prediction rows refer to exported CSV positions.
Use `--details-csv details.csv` for classifications by cell.

Detection counts a prediction on an error cell as TP, an unpredicted error as
FN, and a prediction on any other scored cell as FP. Ambiguous cells are
FP-immune. Exclusion scopes and per-cell skips are FP/FN-immune. A legacy skip
with an empty column denotes a row-level finding and does not mask an entire
row in cell scoring. `ignored.jsonl` is authoritative over legacy exclusion
projections in `neutral_cells.jsonl`.

For end-to-end correction, the predicted correction must match an accepted
value. A wrong correction on an error cell contributes both an FP and an FN.
The scorer strips surrounding whitespace and compares strings case-sensitively.
A prediction list matches when it contains an accepted correction. See its `--help` for input column options.

Report micro-F1 from summed TP, FP and FN. Report any supervised use of these
labels and keep evaluation labels separate from training data.

## Integrity and provenance

`release_manifest.json` records artifact SHA-256 checksums and release totals.
The source archive's `MANIFEST.json` records each CSV's checksum and shape;
`_ROW_MAP.json` preserves original row coordinates. Source rights and
construction notes are in [DATA_PROVENANCE.md](DATA_PROVENANCE.md).
