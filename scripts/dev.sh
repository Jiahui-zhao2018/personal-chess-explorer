#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || [ ! -d frontend/node_modules ]; then
  echo 'Run bash scripts/install.sh first.' >&2
  exit 1
fi
backend_pid=''
frontend_pid=''
cleanup() {
  trap - EXIT
  trap '' INT TERM
  for pid in $backend_pid $frontend_pid; do
    kill "$pid" 2>/dev/null || true
  done
  # Give both services time to stop, but do not hang on a stuck child.
  attempts=0
  while [ "$attempts" -lt 5 ]; do
    alive=false
    for pid in $backend_pid $frontend_pid; do
      if kill -0 "$pid" 2>/dev/null; then alive=true; fi
    done
    if [ "$alive" = false ]; then break; fi
    attempts=$((attempts + 1))
    sleep 1
  done
  for pid in $backend_pid $frontend_pid; do
    if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Frontend is reachable by the cloud preview proxy; backend remains loopback-only.
# One backend worker is required for the local synchronization locks and OAuth state.
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log &
backend_pid=$!
(cd frontend && exec node node_modules/vite/bin/vite.js --port 5173 --strictPort --clearScreen false) &
frontend_pid=$!

# Bash 3.2 has no wait -n. Poll our two direct children, then reap the one that
# exited to preserve its actual status. Even a clean exit is unexpected here.
while :; do
  for service in backend frontend; do
    case "$service" in
      backend) pid=$backend_pid ;;
      frontend) pid=$frontend_pid ;;
    esac
    if ! kill -0 "$pid" 2>/dev/null; then
      if wait "$pid"; then status=0; else status=$?; fi
      echo "$service exited unexpectedly (status $status); stopping both services." >&2
      if [ "$status" -eq 0 ]; then status=1; fi
      exit "$status"
    fi
  done
  sleep 1
done
