"""Recompute and verify Table 3 offline from the retained method outputs."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reproducibility.table3 import reproduce  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "reproducibility/table3")
    parser.add_argument("--output", type=Path, default=ROOT / "build/table3")
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Aggregate saved per-table counts instead of rescoring predictions",
    )
    args = parser.parse_args()
    started = time.monotonic()
    result = reproduce(args.artifacts.resolve(), args.output.resolve(), args.counts_only)
    print(
        f"Table 3: {result['methods']} methods, {result['runs']} runs, {time.monotonic() - started:.2f}s"
    )
    print("MATCH" if result["matched"] else "DIFFERENCES: see verification.json")
    return 0 if result["matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
