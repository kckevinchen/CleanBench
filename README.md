<div align="center">

# CleanBench

### A Real-World Benchmark for Unsupervised Data Cleaning

**Naturally occurring errors. Real-world tables. Human-verified labels.**

[![Tables: 1,000](https://img.shields.io/badge/tables-1%2C000-2563eb)](#benchmark-at-a-glance)
[![Cells: 364,804](https://img.shields.io/badge/cells-364%2C804-0f766e)](#benchmark-at-a-glance)
[![Real errors: 1,409](https://img.shields.io/badge/real_errors-1%2C409-b45309)](#benchmark-at-a-glance)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white)](#use-the-benchmark)
[![Code license: MIT](https://img.shields.io/badge/code_license-MIT-64748b)](LICENSE)

[**Dataset & scorer**](benchmark/README.md) |
[**Construction**](#how-cleanbench-is-built) |
[**Results**](#experimental-results) |
[**Annotation workbench**](#run-the-workbench) |
[**Citation**](#citation)

</div>

## Introduction

Detecting errors in real tables is a **needle-in-a-haystack problem**: most cells
are correct, and unfamiliar names, abbreviations, and domain-specific values can
look like errors. A method must find genuine mistakes without "fixing" valid data.

CleanBench evaluates this challenge using **1,000 real-world tables with naturally
occurring errors**, rather than synthetically injected mistakes. It contains
**1,409 human-verified error cells among 364,804 cells**, spanning relational
tables and spreadsheets. Repeated LLM queries surface candidates for human
verification; an independent cell-by-cell audit checks label quality and coverage.

This repository releases the **frozen benchmark, source tables, cell-level
scorer, and local annotation workbench** used to support reproducible evaluation
and further data-cleaning research.

<p align="center">
  <img src="docs/assets/construction.png" alt="CleanBench construction: source selection, repeated LLM candidate generation, human verification, independent quality audit, and the final benchmark." width="100%">
</p>

## Benchmark at a glance

| Source | Tables | Cells | Error cells | Ambiguous cells |
|---|---:|---:|---:|---:|
| Relational (`pbi_500`) | 500 | 142,459 | 347 | 384 |
| Spreadsheet (`bing21_500`) | 500 | 222,345 | 1,062 | 458 |
| **Total** | **1,000** | **364,804** | **1,409** | **842** |

- **Real errors, not injected noise.** Tables are sampled from public Business
  Intelligence models (`.pbix`) and spreadsheet workbooks (`.xlsx`), using the
  first 100 rows of each selected table.
- **Clean tables matter too.** Errors occur in only **168 of 1,000 tables**.
  The remaining tables help test whether methods leave valid data unchanged.
- **Uncertainty is explicit.** Suspicious values without sufficient evidence are
  labeled **ambiguous**, not forced into clean/error decisions. Error cells can
  have multiple accepted repairs.
- **Exact cell-level evaluation.** Measure error detection and end-to-end
  correction, rather than downstream model utility.

### What kinds of errors?

| Error type | What it captures | Example from the paper |
|---|---|---|
| **Spelling** | Missing, replaced, or transposed letters | `Acupunture` → `Acupuncture` |
| **Formatting** | Incorrect punctuation or whitespace | `202-403- 5292` → `202-403-5292` |
| **Inconsistency** | Values that conflict with single-column, cross-column, or cross-table context | `July` among three-letter month abbreviations |

<p align="center">
  <img src="docs/assets/spelling-errors.png" alt="Three real spelling errors: Acupunture, Wednusday, and Smooth Sliky Salty, alongside their accepted corrections." width="49%">
  <img src="docs/assets/formatting-errors.png" alt="Three real formatting errors involving a trailing comma, phone-number spacing, and a missing apostrophe." width="49%">
</p>

<p align="center">
  <img src="docs/assets/error-distributions.png" alt="Distributions of errors across tables and error types: 456 relational and 376 spreadsheet tables contain no errors; spelling dominates relational errors, while inconsistency dominates spreadsheet errors." width="100%">
</p>

Error types can overlap, so their counts need not sum to the number of erroneous
cells. The low overall error rate (**about 0.39%**) makes avoiding false positives
as important as finding errors.

## How CleanBench is built

1. **Select diverse sources.** Sample 500 relational tables and 500 spreadsheet
   tables, deduplicate similar tables, and preserve source relationships for
   cross-table checks.
2. **Generate candidates for recall.** Repeated LLM queries target spelling,
   formatting, and inconsistency separately. Good–Turing and Chao1 estimates
   guide adaptive stopping, reducing 364,804 cells to **28,745 candidate cells**
   for review. Budget-exhausted cases receive exhaustive manual review.
3. **Verify for precision.** Four reviewers participate in labeling, using table
   context and external evidence to distinguish **error**, **clean**, and
   **ambiguous** cells and record acceptable repairs.
4. **Audit independently.** Two reviewers inspect **20,990 cells across 50
   sampled tables**, without LLM assistance. Both agree with the existing labels
   in **380 of 383 error/ambiguous cases (99.22%)**.

The stopping diagnostics concern candidates discoverable by the LLM, not a proof
that every true error is found. The independent audit checks this limitation
empirically; one additional cell was flagged as an error by one auditor and
considered clean by the other.

## Experimental results

The accompanying manuscript evaluates **21 methods** spanning constraint-based
and knowledge-based systems, spelling correction, LLM-based methods, coding
agents, and commercial spreadsheet tools.

**Real-world cleaning remains challenging.** The strongest reported method,
GPT-6-Astra with a feedback-optimized prompt, reaches **72.69% end-to-end F1**.
Microsoft Excel Clean Data has the highest reported precision (**76.16%**) but
lower recall (**25.43%**), illustrating the precision–coverage tradeoff.
Higher-quality LLM results also come at a cost: GPT-6-Astra costs **$47.70 per
1,000 tables**, with a mean runtime of **24.5 seconds per table** in the paper.

<p align="center">
  <img src="docs/assets/quality-cost.png" alt="Paper results comparing end-to-end F1 against monetary cost and runtime, with logarithmic cost and runtime axes." width="620">
</p>

<details>
<summary><strong>All reported end-to-end correction results</strong></summary>

Values below are percentages from Table 3 of the accompanying manuscript, not
results regenerated by this repository. Higher precision, recall, and F1 are
better; lower clean-cell false-positive rate (FPR) is better.

| Method | Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|
| **Constraint-based** | | | | |
| BigDansing | 0.20 | 0.73 | 0.31 | 1.1002 |
| Holistic | 0.09 | 0.27 | 0.14 | 0.8968 |
| DaisyP | 0.00 | 0.00 | 0.00 | 0.0039 |
| Horizon | 0.06 | 0.09 | 0.07 | 0.4790 |
| Relative Trust | 0.00 | 0.00 | 0.00 | 0.9377 |
| NADEEF | 0.43 | 0.46 | 0.44 | 0.3220 |
| LLUNATIC | 0.05 | 0.18 | 0.08 | 1.1223 |
| UniClean | 0.06 | 0.09 | 0.07 | 0.4724 |
| **Knowledge-based** | | | | |
| KATARA (KB) | 0.00 | 0.00 | 0.00 | 3.1096 |
| **Spelling correction** | | | | |
| SymSpell | 2.65 | 31.47 | 4.89 | 3.4474 |
| NeuSpell | 0.99 | 30.74 | 1.91 | 9.1602 |
| **LLM-prompt cleaning** | | | | |
| CleanAgent | 0.15 | 4.67 | 0.29 | 9.2990 |
| Cocoon | 5.91 | 36.78 | 10.19 | 1.7284 |
| **LLM-agent optimized with feedback** | | | | |
| GPT-4.1 | 22.37 | 36.41 | 27.65 | 0.3768 |
| GPT-5.2 | 12.48 | 56.21 | 20.41 | 1.1835 |
| GPT-5.5 | 55.90 | 60.72 | 58.15 | 0.1332 |
| GPT-6-Astra | 72.27 | 73.16 | **72.69** | 0.0704 |
| **Coding agents** | | | | |
| GPT-6-Astra (Codex) | 57.49 | 75.48 | 65.27 | 0.1531 |
| GPT-6-Astra (Copilot) | 57.59 | 76.03 | 65.54 | 0.1540 |
| **Commercial systems** | | | | |
| Microsoft Excel Clean Data | **76.16** | 25.43 | 38.13 | 0.0221 |
| Google Sheets Smart Cleanup | 0.00 | 0.00 | 0.00 | 3.0373 |

The paper reports feedback-optimized LLM results averaged over three runs, using
a 200-table development set for prompt optimization. A correct end-to-end
prediction must both locate the error and supply an accepted repair; ambiguous
cells are excluded from the reported metrics.

</details>

## Use the benchmark

The frozen labels, source tables, and cell scorer are in [`benchmark/`](benchmark/README.md).
See its README for schemas, row coordinates, accepted corrections, and scoring rules.
The scorer needs **Python 3.10+** and uses only the standard library.

```bash
git clone https://github.com/kckevinchen/CleanBench.git
cd CleanBench
python -m zipfile -e benchmark/sanitized_sources.zip benchmark/sanitized_sources

# Detect erroneous cells.
python benchmark/eval_cleanbench.py --predictions predictions.jsonl

# Detect errors and supply accepted corrections.
python benchmark/eval_cleanbench.py --predictions predictions.jsonl --task end_to_end
```

Supply your method's predictions as JSONL or CSV:

| Field | Required for | Meaning |
|---|---|---|
| `dataset` | Both tasks | `pbi_500` or `bing21_500` |
| `source` | Both tasks | CSV basename, including `.csv` |
| `row` | Both tasks | Original zero-based data-row index, excluding the header |
| `column` | Both tasks | Column name, with surrounding whitespace trimmed |
| `corrected_value` | End-to-end correction | Proposed replacement value |

Use `--use-row-map` if your predictions use extracted CSV row positions. The
frozen label files use original row coordinates; retain `_ROW_MAP.json`.

**Scoring:** report micro-precision, recall, and F1 from summed cell-level counts.
A wrong repair on an error cell contributes both an FP and an FN. Ambiguous
cells are FP-immune; exclusions and per-cell skips are FP/FN-immune. The released
scorer supports **detection** and **end-to-end correction**; the paper also
discusses repair-only diagnostics. Disclose any supervised use of benchmark labels.

### Released artifacts

| Artifact | Contents |
|---|---|
| [`benchmark_cell.json`](benchmark/benchmark_cell.json) | 1,409 error and 842 ambiguous cell labels, with accepted repairs |
| [`benchmark_row.json`](benchmark/benchmark_row.json) | 46 supplementary row/relation labels, separate from cell scoring |
| [`sanitized_sources.zip`](benchmark/sanitized_sources.zip) | Source CSVs, checksums, and original-row mappings |
| [`ignored.jsonl`](benchmark/ignored.jsonl) | Authoritative exclusion scopes |
| [`neutral_cells.jsonl`](benchmark/neutral_cells.jsonl) | Legacy skip and exclusion annotations |
| [`eval_cleanbench.py`](benchmark/eval_cleanbench.py) | Standard-library cell detection and correction scorer |
| [`release_manifest.json`](benchmark/release_manifest.json) | Release counts and SHA-256 checksums |

Both label files ending in `.json` are **JSONL** (one object per line).

## Run the workbench

The local annotation workbench lets you inspect candidate errors in table context,
record verdicts and repairs, review column inconsistencies, and export evaluation
bundles. It requires **Python 3.10+** and runs **without model credentials**.

<p align="center">
  <img src="docs/assets/human-verification.png" alt="The paper's annotation interface showing table context, an error explanation and suggested repair, web verification, and human verdict controls." width="480">
  <br>
  <em>Human-verification interface shown in the accompanying manuscript.</em>
</p>

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

<details>
<summary><strong>Import, review, export, and back up your annotations</strong></summary>

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

</details>

## Development

```bash
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
```

Node 18+ enables the optional JavaScript tests.

## Citation

If you use CleanBench, please cite the accompanying manuscript:

```bibtex
@misc{chen2026cleanbench,
  title={CleanBench: A Real-World Benchmark for Unsupervised Data Cleaning},
  author={Chen, Kaiwen and He, Yeye and Kariv, Tal and Ariav, Itay and
          Helman, Yair and Chaudhuri, Surajit},
  year={2026},
  note={Manuscript},
  url={https://github.com/kckevinchen/CleanBench}
}
```

## License

Project code is [MIT licensed](LICENSE). This license does not relicense
third-party table content; see [data provenance](benchmark/README.md#provenance).

The six figures in [`docs/assets/`](docs/assets/) are reproduced from the
accompanying CleanBench manuscript by Kaiwen Chen, Yeye He, Tal Kariv, Itay Ariav,
Yair Helman, and Surajit Chaudhuri (Figures 2, 3, 4, 7, 9, and 11).
They retain the manuscript's
[CC BY-NC-ND 4.0 license](https://creativecommons.org/licenses/by-nc-nd/4.0/),
not the code's MIT license. Figures were extracted without changing their content.
