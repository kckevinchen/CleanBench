# Table 3 inference adapters

These adapters execute the end-to-end configurations used in Table 3. The
container entry point is `runner.py`; the host evaluates its predictions using
the existing reproduction scripts. See [Docker setup](../docker/README.md).

`native/` contains project-authored bridges extracted from the experiment
harness. `provenance.json` records their source files and hashes. Upstream
implementations are downloaded at pinned commits during image builds; their
licenses remain those of their respective projects. They are not vendored here.

The portable adapters replace machine-specific environment paths and service
authentication. CleanAgent executes generated code inside its container with
process resource limits. Its annotation, programming, execution, and output
validation workflow is unchanged. The direct API clients preserve the prompt,
API type, and reasoning settings used by each model. CLI versions are pinned in
the coding-agent image.

The eight constraint baselines use the fixed LLM-inferred rules in
`config/constraint_rules.json`, included in the Docker images. The loader
verifies the file checksum, and table IDs and input-row checksums bind rules
to source tables. `CLEANBENCH_RULES_FILE` optionally selects a local copy of
the same experiment rules.
Column aliases `C0`, `C1`, etc. refer to the original column positions.
No benchmark labels are passed into inference. `prompts/` contains the three
selected API prompts, the coding-agent task and error definitions, and the
CleanAgent prompts.

Outputs use zero-based row and column coordinates and preserve literal cell
strings. Native failures are recorded as failed executions. An authentication
or unavailable-model error stops an API run so that its configuration can be
corrected before submitting the remaining tables.
