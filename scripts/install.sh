#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!(major === 20 && minor >= 19 || major === 22 && minor >= 12 || major >= 24)) throw Error("Node 20.19+, 22.12+ or 24+ required")'
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
PIP_CACHE_DIR="${TMPDIR:-/tmp}/pce-pip-cache" .venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci --cache "${TMPDIR:-/tmp}/pce-npm-cache"
npm run build
