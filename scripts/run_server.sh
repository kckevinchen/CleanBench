#!/usr/bin/env bash
# Start the local annotation server and manage its background process.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/workbench.pid"
LOG_FILE="$PROJECT_ROOT/logs/workbench.log"
cd "$PROJECT_ROOT"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  server_pid="$(cat "$PID_FILE")"
  [[ "$server_pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$server_pid" 2>/dev/null || return 1
  # A stale PID file must not identify a different process as our server.
  [[ "$(ps -p "$server_pid" -o args= 2>/dev/null)" == *"-m src.labeling serve"* ]]
}

stop_server() {
  if is_running; then
    echo "Stopping server (pid $server_pid)."
    kill -TERM "$server_pid"
    for ((attempt = 0; attempt < 100; attempt++)); do
      if ! is_running; then
        rm -f "$PID_FILE"
        return
      fi
      sleep 0.1
    done
    echo "Server has not stopped yet; check $LOG_FILE" >&2
    return 1
  fi
  rm -f "$PID_FILE"
  echo "Server is not running."
}

case "${1:-start}" in
  -h|--help|help)
    cat <<'USAGE'
Usage: ./scripts/run_server.sh [start|stop|restart|status] [server options]

  start     Start in the background (default).
  stop      Stop the server.
  restart   Stop, then start with the supplied options.
  status    Show the process status and recent log lines.

Server options: --workspace PATH --annotator NAME --host HOST --port PORT
Defaults: workspace=workspace, host=127.0.0.1, port=8000.
USAGE
    exit 0
    ;;
  stop)
    stop_server
    exit 0
    ;;
  status)
    if is_running; then
      echo "Running (pid $server_pid)."
      tail -n 5 "$LOG_FILE" 2>/dev/null || true
    else
      echo "Server is not running."
    fi
    exit 0
    ;;
  restart)
    shift
    stop_server
    ;;
  start)
    if (( $# > 0 )); then shift; fi
    ;;
  -*) ;; # Allow server options without an explicit 'start'.
  *) echo "Unknown command: $1. Use --help for usage." >&2; exit 2 ;;
esac

if is_running; then
  echo "Server is already running (pid $server_pid). Use restart or stop." >&2
  exit 1
fi

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  python_bin="$PROJECT_ROOT/.venv/bin/python"
elif [[ -x "$PROJECT_ROOT/venv/bin/python" ]]; then
  python_bin="$PROJECT_ROOT/venv/bin/python"
else
  python_bin="$(command -v python3 || command -v python)"
fi

mkdir -p "$PROJECT_ROOT/logs"
if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$python_bin" -m src.labeling serve "$@" >>"$LOG_FILE" 2>&1 < /dev/null &
else
  nohup "$python_bin" -m src.labeling serve "$@" >>"$LOG_FILE" 2>&1 < /dev/null &
fi
echo "$!" > "$PID_FILE"
sleep 2
if ! is_running; then
  rm -f "$PID_FILE"
  echo "Server failed to start. Recent log output:" >&2
  tail -n 15 "$LOG_FILE" >&2 || true
  exit 1
fi
echo "Started server (pid $server_pid). Log: $LOG_FILE"
tail -n 5 "$LOG_FILE" 2>/dev/null || true
