# CleanBench

CleanBench provides human-reviewed data-quality labels for **1,000 real tables**
and a local annotation workbench for building new benchmarks.

| Source | Tables | Cells | Error cells | Ambiguous cells |
|---|---:|---:|---:|---:|
| Relational (`pbi_500`) | 500 | 142,459 | 347 | 384 |
| Spreadsheet (`bing21_500`) | 500 | 222,345 | 1,062 | 458 |
| Total | 1,000 | 364,804 | 1,409 | 842 |

This release contains the final benchmark, its source tables, a cell scorer,
and the manual labeling system. It does not contain experiment predictions,
model response caches, baseline runs, training data, RFT code, or manuscript files.

## Use the benchmark

The [benchmark guide](benchmark/README.md) describes the labels, accepted
corrections, exclusions, coordinate mapping, and scoring rules. The frozen
files are under `benchmark/`; the `*.json` label files are **JSONL**, one object
per line.

Benchmark scoring uses Python 3.10 or newer and the standard library.

Extract the source tables if needed:

```bash
python -m zipfile -e benchmark/sanitized_sources.zip benchmark/sanitized_sources
```

Score cell predictions in JSONL or CSV format:

```bash
python benchmark/eval_cleanbench.py --predictions /path/to/predictions.jsonl
python benchmark/eval_cleanbench.py --predictions /path/to/predictions.jsonl --task end_to_end
```

Prediction fields are `dataset`, `source`, `row`, and `column`, plus
`corrected_value` for correction scoring. `row` is the original zero-based
data-row index. Use `--use-row-map` for predictions indexed by exported rows.

## Run the annotation workbench

The workbench runs locally with Python 3.10 or newer. It requires no Azure,
OpenAI, or other model credentials.

```bash
git clone https://github.com/kckevinchen/CleanBench.git
cd CleanBench
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/run_server.sh start --workspace workspace --annotator your-name
```

Open **http://127.0.0.1:8000/**. The startup script uses `.venv` automatically
and runs the server in the background, writing logs to `logs/workbench.log`.

To check, restart, or stop the server:

```bash
./scripts/run_server.sh status
./scripts/run_server.sh restart --workspace workspace --annotator your-name
./scripts/run_server.sh stop
```

On Windows, activate the environment with `.venv\Scripts\activate` and start
the server with `python -m src.labeling serve --workspace workspace --annotator your-name`.

In the browser, import UTF-8 CSVs and an optional candidate JSONL file.
Without candidates, every cell enters the review queue.

To try the small, synthetic example from the command line:

```bash
python -m src.labeling import --workspace workspace --run-id demo \
  --csv examples/people.csv --candidates examples/candidates.jsonl
```

The [labeling guide](LABELING_GUIDE.md) covers decisions, corrections, missed
errors, the column board, exclusions, and export. Labels are append-only JSONL
histories in `workspace/outputs/<run-id>/`; the published benchmark is never
edited by the workbench. Use a separate workspace for your annotations.

## Repository layout

```text
benchmark/           Frozen labels, source archive, checksum manifest, cell scorer
src/labeling/        Local import, annotation API, stores, and export
src/core/            Shared CSV and header utilities
frontend/labeling/   Table grid, review queue, and column board
examples/            Synthetic CSV and candidate file for a first run
scripts/             Start, stop, restart, and check the annotation server
tests/               Store, API, export, import, and scoring checks
```

The HTTP app composes routers with import/export services and a bounded run
cache. Stores preserve append-only human histories; per-run file locks coordinate
read/write operations and export snapshots. Each download streams its own copy,
so another export cannot overwrite a response in progress.

After installing `requirements.txt`, run the local checks:

```bash
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
```

Tests cover history recovery, independent writers, input validation, concurrent
exports, and server lifecycle operations. Node 18+ enables the optional JavaScript
checks; Python-only installations skip those checks.

## License

Project code is available under the [MIT license](LICENSE). The benchmark
contains tables collected from public sources; the code license does not
relicense third-party table content. See [data provenance](benchmark/DATA_PROVENANCE.md).
