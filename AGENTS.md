# CleanBench public repository

This repository contains the local annotation workbench and frozen benchmark.
Keep experiments, model-service integrations, RFT, raw model outputs, and user
workspaces out of the public release.

- Read `LABELING_GUIDE.md` before changing label or export behavior.
- Preserve append-only histories, tombstones, human provenance, and original
  `(source, row, column)` coordinates.
- Keep skipped/excluded immunity aligned with benchmark and source exports.
- Do not regenerate or relabel frozen artifacts during code maintenance.
- Put local imports and user work under ignored `workspace/`.
- Run focused tests, `python scripts/verify_benchmark.py`, and `git diff --check`.
- For UI changes, inspect the actual page and check keyboard use.
- Before a release, inspect tracked files and the contents of archives.
