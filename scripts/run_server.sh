#!/usr/bin/env bash
# Use the project's Python environment; lifecycle logic lives in src/labeling.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  python_bin="$PROJECT_ROOT/.venv/bin/python"
elif [[ -x "$PROJECT_ROOT/venv/bin/python" ]]; then
  python_bin="$PROJECT_ROOT/venv/bin/python"
else
  python_bin="$(command -v python3 || command -v python)"
fi
command="${1:-start}"
case "$command" in
  start|stop|restart|status) if (( $# > 0 )); then shift; fi ;;
  -h|--help) exec "$python_bin" -m src.labeling.server_control --help ;;
  -*) command=start ;;
  *) echo "Unknown command: $command. Use --help for usage." >&2; exit 2 ;;
esac
exec "$python_bin" -m src.labeling.server_control --project-root "$PROJECT_ROOT" "$command" "$@"
