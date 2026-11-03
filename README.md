# CleanBench

CleanBench provides a human-reviewed data-quality benchmark and a local
annotation workbench.

| Source | Tables | Cells | Error cells | Ambiguous cells |
|---|---:|---:|---:|---:|
| Relational (`pbi_500`) | 500 | 142,459 | 347 | 384 |
| Spreadsheet (`bing21_500`) | 500 | 222,345 | 1,062 | 458 |
| Total | 1,000 | 364,804 | 1,409 | 842 |

## Use the benchmark

The frozen labels, source tables, and cell scorer are in [`benchmark/`](benchmark/README.md).
See its README for schemas, row coordinates, accepted corrections, and scoring rules.
The scorer needs Python 3.10+ and uses the standard library.

```bash
python -m zipfile -e benchmark/sanitized_sources.zip benchmark/sanitized_sources
python benchmark/eval_cleanbench.py --predictions predictions.jsonl
python benchmark/eval_cleanbench.py --predictions predictions.jsonl --task end_to_end
```

## Run the workbench

The workbench requires Python 3.10+ and runs locally without model credentials.

```bash
git clone https://github.com/kckevinchen/CleanBench.git
cd CleanBench
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/run_server.sh start --workspace workspace --annotator your-name
```

Open **http://127.0.0.1:8000/**. The server runs in the background and writes
logs to `logs/workbench.log`. Use `./scripts/run_server.sh status`,
`./scripts/run_server.sh restart`, or `./scripts/run_server.sh stop` to manage it.
Pass the same workspace, annotator, and port options when restarting.

On Windows, activate `.venv\Scripts\activate` and run
`python -m src.labeling serve --workspace workspace --annotator your-name`.
Local API documentation is at `/api/docs`.

### Import and review

Import UTF-8 CSVs from the home page. Each file needs a header and at least one
data row; filenames must be unique within a run, and column names must remain
unique after trimming surrounding whitespace. Keep filenames, headers, and row
order fixed after labeling starts.

An optional candidate JSONL file limits review to selected cells:

```json
{"source":"people.csv","row":1,"column":"city","error_type":"typo","suggested_value":"Seattle"}
```

`source`, `row`, and `column` are required. Rows start at zero after the header.
`error_type`, `explanation`, and `suggested_value` are optional. Without a
candidate file, every cell enters the review queue. Imported suggestions remain
proposals until reviewed.

A small synthetic example is included:

```bash
python -m src.labeling import --workspace workspace --run-id demo \
  --csv examples/people.csv --candidates examples/candidates.jsonl
```

Open **Label**, inspect the source context, enter a correction where appropriate,
and save a verdict:

| Verdict | Meaning | Export |
|---|---|---|
| `tp` | Confirmed error | `error` |
| `partial` | Error with an edited scope or correction | `error` |
| `fp` | Valid value | `clean` |
| `unsure` | Insufficient evidence | `ambiguous` |
| `skip` | Outside the scoring task | Immunity record |

Click a source cell to add a missed error (`fn`). For inconsistencies, use the
column board to group values and confirm their accepted forms. Use exclusions
for whole files, rows, or columns that should not be scored.

Keyboard shortcuts: `j`/`k` navigate, `c` focuses the correction, and `n` focuses
the note. `Enter` saves and advances; it defaults to `fp` if no verdict is selected.

### Export and back up

Choose **Export → Eval bundle** to download `benchmark.jsonl`,
`benchmark.ignored.jsonl`, and `MANIFEST.txt`. Export source CSVs from the same
menu. Preserve `_ROW_MAP.json` when exclusions remove rows, so exported positions
can be mapped back to original label coordinates.

Runs are stored under `workspace/outputs/<run-id>/`. Back up the whole run,
including source CSVs and append-only decision histories. Clearing a decision
preserves its history. Workbench exports use `label` and human provenance fields;
the frozen benchmark uses `status`. Keep each export with its matching sources.

## Development

```bash
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
```

Node 18+ enables the optional JavaScript tests.

## License

Project code is [MIT licensed](LICENSE). This license does not relicense
third-party table content; see [data provenance](benchmark/README.md#provenance).
