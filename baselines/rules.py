"""Load the bundled experiment rules, with an optional local-file override."""

import os
from pathlib import Path

from baselines.common import read_json, sha

EXPECTED_SHA256 = "687c520d4d866fe2f88e87ff11f1c11c4e541ba09d3a32487a8628d0eef4dbd8"


DEFAULT_RULES_FILE = Path(__file__).resolve().parent / "config/constraint_rules.json"


def load():
    filename = os.environ.get("CLEANBENCH_RULES_FILE")
    path = Path(filename) if filename else DEFAULT_RULES_FILE
    if not path.is_file():
        raise ValueError("Missing constraint rules file: " + str(path))
    if sha(path) != EXPECTED_SHA256:
        raise ValueError("Constraint rules do not match the Table 3 experiment")
    return read_json(path)
