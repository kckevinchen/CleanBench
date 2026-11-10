"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

UPSTREAM = Path(__file__).resolve().parent / "adr_repo"


SOURCE = UPSTREAM / "horizon/horizon.py"


def load_horizon():
    """Load unchanged declarations, excluding the release's unconditional CLI driver."""
    import pandas as pd

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    declarations = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
    ]
    module = SimpleNamespace(__name__="cleanbench_native_horizon")
    exec(compile(ast.Module(body=declarations, type_ignores=[]), str(SOURCE), "exec"), vars(module))

    class StringCSV:
        def __getattr__(self, key):
            return getattr(pd, key)

        @staticmethod
        def read_csv(path, *args, **kwargs):
            return pd.read_csv(path, *args, **{**kwargs, "dtype": str, "keep_default_na": False})

    module.pd = StringCSV()
    return module
