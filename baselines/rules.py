"""Load the experiment rules from an explicitly supplied local file."""

import os
from pathlib import Path

from baselines.common import read_json, sha

EXPECTED_SHA256 = "687c520d4d866fe2f88e87ff11f1c11c4e541ba09d3a32487a8628d0eef4dbd8"


def load():
    filename = os.environ.get("CLEANBENCH_RULES_FILE")
    if not filename or not Path(filename).is_file():
        raise ValueError(
            "Constraint rules are not bundled; set CLEANBENCH_RULES_FILE to a local rules file"
        )
    path = Path(filename)
    if sha(path) != EXPECTED_SHA256:
        raise ValueError("Constraint rules do not match the Table 3 experiment")
    return read_json(path)
