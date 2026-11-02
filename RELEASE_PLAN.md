# Initial public release plan

Target: `https://github.com/kckevinchen/CleanBench`, starting from its empty
`main` branch. Build in an independent checkout; do not import the research
repository's Git history or change its working tree.

## Scope

Include:

1. The local labeling backend, source-table UI, column board, append-only
   human decision stores, missed-error capture, exclusions, and exports.
2. Local CSV/candidate import from both the browser and command line.
3. The final frozen cell and row/relation annotations, authoritative
   exclusions and per-cell immunity records, and the matching 1,000 source tables.
4. A standalone cell scorer, checksums, an offline integrity verifier,
   focused tests, installation instructions, and a synthetic first-run example.
5. The MIT license for project code, with separate source-data provenance notes.

Exclude:

- RFT code, training/validation splits, checkpoints, and cloud job state.
- Experiment runners, baseline wrappers/results, predictions, raw model
  response caches, intermediate detection runs, and internal annotation logs.
- Credentials, configured service endpoints, user-specific paths, local
  environments, manuscript sources, generated paper figures, and old Git history.

The author selected manual annotation, import and export for this release.
Model candidate generation, model-assisted correction, web verification jobs,
and the research experiment launcher are omitted. Imported proposals remain
unaccepted until a human reviews them.

## Assembly and validation

1. Verify read/write access and clone the empty target repository.
2. Copy only an explicit source allowlist and the final benchmark artifacts.
3. Remove model-service and experiment-launcher dependencies; add local import.
4. Package observed source CSVs from the frozen manifest, preserving their
   hashes and row maps. Do not use the older, mismatched source ZIP.
5. Validate all label coordinates, original values, counts, and checksums.
6. Install in an isolated environment; run offline store/API/export/scoring
   tests and inspect the browser's import → label → export workflow.
7. Audit the tracked file list and archives against the inclusion/exclusion
   scope, commit the curated release, and push `main`.
8. Fetch a fresh checkout and repeat the release checks against the published
   commit. Record validation in `RELEASE_VALIDATION.md`.
