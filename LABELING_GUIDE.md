# Label tables locally

The workbench supports manual review, local CSV/candidate import, and benchmark
export. It does not generate model proposals or call external services.

## 1. Import tables

Start the server as shown in the README. On the home page, choose a new run name
and one or more UTF-8 CSVs. Each CSV needs a header row, column names that remain
unique after trimming surrounding whitespace, and at least one data row.
Source filenames must be unique within a run.

You can provide a candidate JSONL file to limit the queue to selected cells:

```json
{"source":"people.csv","row":1,"column":"city","error_type":"typo","explanation":"Review the spelling.","suggested_value":"Seattle"}
```

Required fields are `source`, `row`, and `column`. Rows start at zero after the
header. `error_type`, `explanation`, and `suggested_value` are optional. A proposal
is an input to review, never an accepted label. Duplicate candidate cells are
rejected. Without a candidate file, the workbench queues every cell for review.

The importer copies source files into the run and rejects existing run names.
Do not rename source files, edit headers, or reorder rows after labeling starts.
Runs created with this importer use relative source paths, so you can move the
whole workspace without breaking the table views.

## 2. Inspect and label

Open **Label** for the run. Inspect the highlighted source cell and nearby rows.
Choose a verdict, enter a correction where appropriate, and save.

| Verdict | Meaning | Export |
|---|---|---|
| `tp` | A real error | `error` |
| `partial` | A real error, but the proposed scope or correction needs editing | `error` |
| `fp` | A valid value | `clean` |
| `unsure` | Insufficient evidence | `ambiguous` |
| `skip` | Intentionally outside the scoring task | Ignored/immunity record |

Use a short note when the decision depends on domain context. A correction
should preserve information. Do not treat an unfamiliar name or a rare value
as an error without evidence.

Keyboard shortcuts: `j`/`k` move through the queue; `1`–`5` choose the verdicts
above; `c` focuses the correction; `n` focuses the note; `/` searches; `Enter`
saves and advances. Select a verdict before pressing Enter: if none is selected,
the existing UI defaults to `fp`.

## 3. Add missed errors and review columns

Click a source cell to add a missed-error (`fn`) label. Provide its error type
and correction. It joins the same benchmark export as reviewed candidates.

For value inconsistencies, open the column board. You can group selected values,
choose a canonical value, or mark a single missed value. Confirm the canonical
value only when the column context supports that direction. Multiple accepted
forms can be represented as a list of corrections.

Column statuses are `labeled`, `no_inconsistency`, `dropped_overlapping`, and
`dropped_messy`. Dropped columns do not assert that all their values are clean.

## 4. Exclude data

Use the exclusion bar for an entire CSV, a row range, or named columns. Use
`skip` for an individual finding. Exclusions remove the matching slices from
source exports and add matching immunity records to the benchmark export.

Restoring an exclusion or clearing a verdict appends a new history record.
It does not delete previous human decisions.

## 5. Check and export

Resolve conflicting labels and inspect `partial`, `unsure`, and missed-error
records before sharing a benchmark. In the **Export** menu, choose **Eval bundle**
to download:

- `benchmark.jsonl`: materialized labels and human provenance;
- `benchmark.ignored.jsonl`: skipped cells and wildcard exclusion scopes;
- `MANIFEST.txt`: the scoring contract.

Export source CSVs from the same menu. When rows were removed, preserve the
included `_ROW_MAP.json`: exported row positions differ from original label
coordinates. Keep labels, exclusions, source files, and row mapping together.

The workbench export schema (`label`, cluster history, and annotator fields)
is richer than the frozen public benchmark schema (`status`, final cell labels).
They are separate artifacts. Do not replace published labels with a new run's
export or score predictions with a mismatched source version.

## Local files and API

Each run lives under `<workspace>/outputs/<run-id>/`. Back up this whole
directory, including `labels.jsonl`, `exclusions.jsonl`, any column-cluster
histories, and the copied source CSVs. The home page discovers runs automatically.

The interactive API documentation is at `/api/docs`. The default server binds
to `127.0.0.1` for use by one local reviewer or through an SSH port forward.
