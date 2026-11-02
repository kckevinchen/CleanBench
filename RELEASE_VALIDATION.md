# Initial release validation

Validated on 2026-11-02 with Python 3.12 in a new virtual environment installed
from `requirements-dev.txt`.

| Check | Result |
|---|---|
| Offline tests | 342 passed |
| Dependency consistency (`pip check`) | Passed |
| Python compilation | Passed for annotation, verification, and scorer modules |
| Ruff (`F`, `I`) | Passed for source, scripts, and new public-workflow tests |
| JavaScript parsing | All 7 modules passed |
| Artifact and source SHA-256 checks | Passed |
| Source corpus | 500 relational + 500 spreadsheet tables; 364,804 cells |
| Cell labels | 1,409 error + 842 ambiguous; all original values and coordinates verified |
| Supplementary row/relation labels | 46 records, unchanged |
| Scorer consistency | Accepted gold predictions: TP=1,409, FP=0, FN=0 |
| Browser workflow | CSV/candidate import, proposal display, keyboard labeling, and bundle download passed |
| Export provenance | Original value, accepted correction, and annotator preserved after restart and workspace relocation |
| Desktop/mobile browser checks | 1440×1000 and 390×844; no script errors or horizontal page overflow |
| External service use | No model SDKs installed; no external requests during browser validation |
| Publication contents | Explicit source allowlist; final annotations and observed source tables only |

The source archive contains exactly 1,000 CSVs plus `MANIFEST.json` and
`_ROW_MAP.json`. Source CSV hashes match the frozen manifest. The cell labels,
row/relation labels, exclusions, and legacy immunity annotations are copied
byte-for-byte from their final artifacts. The public source manifest omits
internal absolute paths.

The release excludes RFT, experiment runners/results, predictions, repaired
reference tables, raw model-response caches, internal annotation histories,
credentials, cloud configuration, local environments, and manuscript files.
Only the synthetic first-run example and synthetic test fixtures accompany the
published benchmark. Local validation logs, screenshots, and temporary
predictions remain in ignored `build/` directories.

One development dependency warning remains: Starlette's test client reports
that its `httpx` integration is deprecated. All tests pass; the local server
and browser workflow do not use that test client.
