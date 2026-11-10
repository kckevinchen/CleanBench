# Reproducing main results in the paper

We supply a reproducible script so that others can reproduce our main results in Table 3.
We provide two ways to reproduce below: (1) re-generate Table 3 
using saved intermediate results from a previous run, which is fast; and 
(2) re-run all methods from scratch again and re-generate
Table 3, which can be slow as all 20+ methods will need to be re-run.


## (1). Reproduce results from saved intermediate results (take a few seconds)
This is a fast way to reproduce Table 3 in the paper, using saved intermediate 
results from a previous run. This path needs Python 3.10+.

```bash
python scripts/reproduce_table3.py
```

The script verifies artifact checksums, scores every saved prediction again,
checks the per-table counts, computes each run's micro metrics, and reconstructs
both Table 3 views. It prints `MATCH` and exits successfully when every reported
number and repetition count agrees with the frozen table. The current bundle
was verified in a few seconds.

To aggregate the saved per-table counts directly:

```bash
python scripts/reproduce_table3.py --counts-only
```

This takes approximately 0.4 seconds. Both commands
write `table3_point.csv`, `table3_variability.csv`, `per_run.csv`, and
`verification.json` under `build/table3/`. Override the destination with
`--output PATH`.

The artifact layout is:

```text
reproducibility/table3/
  manifest.json
  reference.json
  source_hashes.json
  expected/
    table3_point.csv
    table3_variability.csv
  methods/<method>/run_<number>/
    predictions.jsonl
    table_counts.jsonl
    run.json
```

The `table3_point.csv` file reproduces the main result table. The `table3_variability.csv` 
file uses the retained independent repetitions and reports their mean and sample standard
deviation (`ddof=1`). Metrics are computed from summed TP/FP/FN within each run
and then averaged across runs.


## (2). Re-run all methods from scratch (can take a few hours)

This path re-runs all methods from scratch to fully reproduce
Table 3, using the following script.

```bash
python scripts/run_table3.py --plan method_commands.json --dry-run
python scripts/run_table3.py --plan method_commands.json --output outputs/table3_fresh
```

The `method_commands.json` specifies each method's native executable and environment.
The runner materializes the source CSVs, starts each method in
a new output directory, collects its predictions, and writes the resulting
table and its comparison with Table 3. Use `--method "METHOD"` to select a specific
method; omit it to execute all methods in Table 3.

In `method_commands.json`, a plan is a JSON object with `schema_version: 1`
and a `methods` mapping keyed by the method names in `reproducibility/table3/manifest.json`. 
Each method entry
contains an argv list named `command`, and optional `cwd` and `environment`
fields. For example, a configured native runner can be invoked with:

```json
{
  "schema_version": 1,
  "methods": {
    "SymSpell": {
      "command": [
        "python", "/path/to/native_runner.py",
        "--inputs", "{inputs}",
        "--predictions", "{predictions}",
        "--execution", "{execution}",
        "--repetition", "{run}"
      ]
    }
  }
}
```

Run a single-method plan with `--method SymSpell`. The available substitutions
are `{python}`, `{repo}`, `{inputs}`, `{run_dir}`, `{predictions}`, `{execution}`,
`{method}`, and `{run}`. Arguments are passed directly to the executable.

The native runner reads `{inputs}/<table-id>/dirty.csv` and its `_manifest.json`.
It writes JSONL predictions with `dataset`, zero-based `row`, zero-based `col`,
and literal `corrected_value` fields. It also writes an execution JSON object
mapping every table ID to `complete`, `failed`, or `unknown`. Per-run settings
and identities are retained in each saved run's `run.json`.

The outputs include `table3_point.csv`, `table3_variability.csv`, `per_run.csv`,
and `comparison.json`. Each run also retains its command, log, predictions,
execution record, and per-table score counts.

## Docker runners

The Docker package provides configured runners for all 19 noncommercial
end-to-end methods in Table 3. It installs the native dependencies and runs each
selected method three times. API credentials are supplied at runtime.

```bash
python scripts/docker_table3.py build --method SymSpell
python scripts/docker_table3.py run --method SymSpell --output outputs/symspell
```

See [Docker setup and credentials](docker/README.md) to run all methods or select
other baselines. The saved-results path can also run in Docker:

```bash
python scripts/docker_table3.py replay --output build/table3_docker_replay
```
