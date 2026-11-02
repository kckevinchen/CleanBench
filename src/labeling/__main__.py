"""Command line for the local CleanBench annotation workbench."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from .importing import import_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local annotation UI")
    serve.add_argument("--workspace", type=Path, default=Path("workspace"))
    serve.add_argument("--annotator", default=getpass.getuser())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    imp = sub.add_parser("import", help="Import CSV files and optional candidate JSONL")
    imp.add_argument("--workspace", type=Path, default=Path("workspace"))
    imp.add_argument("--run-id", required=True)
    imp.add_argument("--csv", type=Path, nargs="+", required=True)
    imp.add_argument("--candidates", type=Path)
    args = parser.parse_args()
    if args.command == "import":
        names = [p.name for p in args.csv]
        if len(set(names)) != len(names):
            parser.error("CSV basenames must be unique.")
        candidates = None
        if args.candidates:
            candidates = [
                json.loads(line)
                for line in args.candidates.read_text().splitlines()
                if line.strip()
            ]
        try:
            target = import_run(
                args.workspace,
                args.run_id,
                {p.name: p.read_text(encoding="utf-8-sig") for p in args.csv},
                candidates,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Imported {target}")
        return
    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(args.workspace, annotator=args.annotator), host=args.host, port=args.port
    )


if __name__ == "__main__":
    main()
