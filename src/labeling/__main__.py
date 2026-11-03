"""Command line for the local CleanBench annotation workbench."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from .import_models import ImportCandidate
from .import_service import import_run


def read_candidates(path: Path) -> list[ImportCandidate]:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ImportCandidate.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(f"{path.name}, line {line_no}: invalid candidate ({exc})") from exc
    return records


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local annotation UI")
    serve.add_argument("--workspace", type=Path, default=Path("workspace"))
    serve.add_argument("--annotator", default=getpass.getuser())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=port_number, default=8000)
    imp = sub.add_parser("import", help="Import CSV files and optional candidate JSONL")
    imp.add_argument("--workspace", type=Path, default=Path("workspace"))
    imp.add_argument("--run-id", required=True)
    imp.add_argument("--csv", type=Path, nargs="+", required=True)
    imp.add_argument("--candidates", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import":
        names = [p.name for p in args.csv]
        if len(set(names)) != len(names):
            parser.error("CSV basenames must be unique.")
        try:
            candidates = read_candidates(args.candidates) if args.candidates else None
            target = import_run(
                args.workspace,
                args.run_id,
                {path.name: path.read_bytes().decode("utf-8") for path in args.csv},
                candidates,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(f"Imported {target}")
        return 0
    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(
            args.workspace,
            annotator=args.annotator,
            server_instance=os.environ.get("CLEANBENCH_SERVER_INSTANCE"),
        ),
        host=args.host,
        port=args.port,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
