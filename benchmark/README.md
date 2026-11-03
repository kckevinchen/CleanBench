# CleanBench benchmark

The benchmark contains 1,000 tables with 364,804 cells, including 1,409 error
cells and 842 ambiguous cells. Dataset IDs are `pbi_500` for relational tables
and `bing21_500` for spreadsheets; each contains 500 tables.

## Files

| File | Contents |
|---|---|
| `benchmark_cell.json` | 2,251 cell labels: 1,409 error and 842 ambiguous |
| `benchmark_row.json` | 46 supplementary row/relation labels: 25 error and 21 ambiguous |
| `ignored.jsonl` | 65 authoritative exclusion scopes |
| `neutral_cells.jsonl` | Legacy skip and exclusion annotations |
| `sanitized_sources.zip` | Source CSVs, checksums, and original-row mappings |
| `release_manifest.json` | Artifact SHA-256 checksums and release counts |
| `eval_cleanbench.py` | Cell detection and correction scorer |

The two label files are **JSONL**, one object per line, despite their `.json`
extension. `release_manifest.json` is a regular JSON object. Supplementary
row/relation labels are separate from the 1,409 cell errors and are not evaluated
by the cell scorer.

## Cell labels

Each record identifies `(dataset, source, row, column)`.

| Field | Meaning |
|---|---|
| `dataset` | `pbi_500` or `bing21_500` |
| `source` | CSV basename, including `.csv` |
| `row` | Original zero-based data-row index, excluding the header |
| `column` | Column name; trim surrounding header whitespace when matching |
| `original_value` | Observed value under the construction loader's whitespace handling |
| `status` | `error` or `ambiguous` |
| `error_types` | Confirmed error categories |
| `corrected_value` | Accepted string, list of accepted strings, or `null` |
| `explanation` | Frozen explanation associated with the reviewed decision |

A cell absent from the label file has no labeled error under the review
protocol, subject to the immunity records below.

## Sources and row coordinates

From the repository root:

```bash
python -m zipfile -e benchmark/sanitized_sources.zip benchmark/sanitized_sources
```

The archive has `pbi_500/` and `bing21_500/` directories, a `MANIFEST.json` with
source checksums and table shapes, and `_ROW_MAP.json`. For mapped tables,
`exported_to_source[i]` gives the original row for exported row `i`; all other
tables use identity mapping. Frozen labels always use original row coordinates.

## Scoring

The scorer accepts JSONL or CSV predictions with `dataset`, `source`, `row`, and
`column`. Correction scoring also requires `corrected_value`.

```bash
python benchmark/eval_cleanbench.py --predictions predictions.jsonl
python benchmark/eval_cleanbench.py --predictions predictions.csv --task end_to_end
```

Use `--use-row-map` when prediction rows refer to extracted CSV positions.
`--corrected-col` selects another correction field, and `--details-csv details.csv`
writes classifications by cell. Run `--help` for all input options.

Detection counts predicted error cells as TP, missed error cells as FN, and
other scored predictions as FP. Ambiguous cells are FP-immune. Exclusion scopes
and per-cell skips are FP/FN-immune. `ignored.jsonl` takes precedence over legacy
exclusion projections in `neutral_cells.jsonl`; a legacy skip with an empty
column refers to a row-level finding and does not mask that row in cell scoring.

Correction scoring additionally requires an accepted correction. A wrong
correction on an error cell contributes both an FP and an FN. String comparison
is case-sensitive after trimming surrounding whitespace; a prediction list
matches if it contains an accepted value. Report micro-F1 from summed TP, FP,
and FN, and disclose any supervised use of benchmark labels.

## Provenance

The labels, accepted corrections, exclusions, and source CSVs are preserved from
the frozen construction artifacts. Source identifiers and original-row mappings
remain intact. Artifact hashes are recorded in `release_manifest.json`, and
individual CSV hashes are in the archive's `MANIFEST.json`.

Tables were collected from public sources. The project's [MIT license](../LICENSE)
covers project-authored code and does not grant new rights in third-party table
content. Preserve source identifiers and any existing table notices when
redistributing the data.
