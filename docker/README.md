# Run Table 3 baselines with Docker

Use Docker Engine with BuildKit (or Docker Desktop) and Python 3.10+ on the host.
The images target Linux x86-64 and install each method's pinned dependencies and
upstream source. Builds download the required models and knowledge base; no API
credentials are needed during the build.

## Quick start

Start with SymSpell, which needs no credentials:

```bash
python scripts/docker_table3.py build --method SymSpell
python scripts/docker_table3.py check --method SymSpell
python scripts/docker_table3.py run --method SymSpell --output outputs/symspell
```

This executes three independent runs on all 1,000 tables, scores the new
predictions, and writes `table3_point.csv`, `table3_variability.csv`, `per_run.csv`,
and `comparison.json`. An empty comparison means the results match the published
table. Use a new output directory for each experiment.

## Credentials and models

For API methods, copy the configuration template and fill in your credentials
and model or deployment names:

```bash
cp docker/runtime.env.example .env
# Edit .env locally.
set -a
. ./.env
set +a
```

`OPENAI_API_KEY` is used for OpenAI-compatible endpoints. For Azure OpenAI, set
`CLEANBENCH_API_PROVIDER=azure`, `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_API_KEY`, and the model variables to your deployment names.
`OPENAI_BASE_URL` selects an alternative OpenAI-compatible endpoint.

Codex uses `CODEX_API_KEY` (falling back to `OPENAI_API_KEY`). Copilot CLI uses
`COPILOT_GITHUB_TOKEN` from a GitHub account with Copilot access. Configure the
coding-agent model names separately with `CLEANBENCH_MODEL_CODEX` and
`CLEANBENCH_MODEL_COPILOT`.

Keys can instead be supplied through `OPENAI_API_KEY_FILE`,
`AZURE_OPENAI_API_KEY_FILE`, `CODEX_API_KEY_FILE`, or
`COPILOT_GITHUB_TOKEN_FILE`. Each variable points to a local text file that is
mounted read-only into the relevant container. Keys are passed only at runtime;
they are not written into command plans or images. `.env` is ignored by Git.

## Build and run methods

The eight constraint methods require a local rules file; the experiment rules
are currently not distributed. Set `CLEANBENCH_RULES_FILE` to its absolute path
before running those methods. The file is checked against the experiment
checksum and mounted read-only, without being copied into an image.
Other methods and saved-results reproduction do not require this file.

```bash
python scripts/docker_table3.py list
python scripts/docker_table3.py build
python scripts/docker_table3.py check
python scripts/docker_table3.py run --output outputs/table3_docker
```

`check` verifies installed components and credential configuration without
calling a paid API. `run` invokes the configured services and incurs their normal
usage charges. To select methods, repeat `--method` on each command, for example:

```bash
python scripts/docker_table3.py run \
  --method BigDansing --method NADEEF --output outputs/constraints
```

The package runs the 19 noncommercial end-to-end methods from Table 3:

| Image | Methods |
| --- | --- |
| `classical` | BigDansing, Holistic, DaisyP, Horizon, Relative Trust, NADEEF, LLUNATIC |
| `uniclean` | UniClean |
| `katara` | KATARA (KB) |
| `spelling` | SymSpell |
| `neuspell` | NeuSpell |
| `cleanagent` | CleanAgent |
| `cocoon` | Cocoon |
| `api` | The four prompt-tuned API models |
| `coding` | Codex and Copilot |

Excel and Google Sheets remain available through the saved-results reproduction
below. Their interactive applications are not launched by this Docker runner.

Each method receives only the dirty input CSVs and its own output directory.
Evaluation runs separately on the host using the published Table 3 scorer.
The fixed prompts used in the experiments are included under `baselines/`;
constraint methods load their rules from `CLEANBENCH_RULES_FILE`. Fresh runs
execute inference again rather than reusing saved predictions.
Each run saves predictions, execution status, logs, per-table
counts, and its comparison with Table 3. Model responses and generated code are
saved under the corresponding table directory.

The native methods have different memory and disk requirements; build individual
images with `--method` when you only need a subset. The Java/Spark and neural
spelling images include their own runtimes. Upstream source commits and package
versions are recorded in `setup_upstream.py` and `requirements/`.

## Reproduce the saved results

```bash
python scripts/docker_table3.py replay --output build/table3_docker_replay
```

This builds the small replay image, re-scores all saved predictions, and checks
all 21 published methods and 59 runs without API credentials. It prints `MATCH`
when the reconstructed table agrees with the published results. Add
`--counts-only` to aggregate the saved per-table counts directly.

The existing command-plan interface remains available:

```bash
python scripts/docker_table3.py plan --method SymSpell > method_commands.json
python scripts/run_table3.py --plan method_commands.json --method SymSpell --dry-run
```
