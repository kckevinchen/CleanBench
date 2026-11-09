# Reproducing Table 3

There are two execution paths: run the methods again, or recompute the table
from the retained method outputs. Both paths use the same Table 3 population,
exact replacement matching, error-type projection, and aggregation code.

## 1. Run the methods from fresh inputs

```bash
python scripts/run_table3.py --plan method_commands.json --dry-run
python scripts/run_table3.py --plan method_commands.json --output outputs/table3_fresh
```

The command plan specifies each method's native executable and environment.
The runner materializes the source CSVs, starts each method and repetition in
a new output directory, collects its predictions, and writes the resulting
table and its comparison with Table 3. Use `--method "METHOD"` to select a
method; omit it to execute the complete Table 3 roster.

A plan is a JSON object with `schema_version: 1` and a `methods` mapping keyed
by the method names in `reproducibility/table3/manifest.json`. Each method entry
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

## 2. Reproduce from saved results

This path needs Python 3.10+ and the standard library. It does not call a model
or run a cleaning method.

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

This takes approximately 0.4 seconds on the preparation machine. Both commands
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

The point view reproduces the main table. The variability view uses the
retained independent repetitions and reports their mean and sample standard
deviation (`ddof=1`). Metrics are computed from summed TP/FP/FN within each run
and then averaged across runs. Error-type targets are coordinate unions.
All numeric values are percentages; single-run standard deviations are undefined.
