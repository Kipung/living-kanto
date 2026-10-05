#!/usr/bin/env bash
# Living Kanto direct local service launcher.
#
# Serves the API + same-origin static roots on loopback:8877:
#   /            -> <client-root>/index.html (explicit 404 JSON if missing)
#   /client/...  -> frontend bundle (read-only)
#   /content/... -> original content tree (read-only)
#   /runs, /ws   -> existing run API (unchanged)
#
# Overrides (environment):
#   LK_HOST (default 127.0.0.1), LK_PORT (default 8877)
#   LK_DATA_DIR    (default <repo>/data/local)   one SQLite file per run
#   LK_CONTENT_ROOT (default <repo>/content)     original content tree
#   LK_CLIENT_ROOT (default <repo>/client)       frontend bundle
#   LK_VENV_PY     (default project venv python)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LK_VENV_PY="${LK_VENV_PY:-$REPO_ROOT/.venv/bin/python3}"
LK_HOST="${LK_HOST:-127.0.0.1}"
LK_PORT="${LK_PORT:-8877}"
LK_DATA_DIR="${LK_DATA_DIR:-$REPO_ROOT/data/local}"
LK_CONTENT_ROOT="${LK_CONTENT_ROOT:-$REPO_ROOT/content}"
LK_CLIENT_ROOT="${LK_CLIENT_ROOT:-$REPO_ROOT/client}"

cd "$REPO_ROOT/server"
exec "$LK_VENV_PY" -m living_kanto.api.app \
  --host "$LK_HOST" \
  --port "$LK_PORT" \
  --data-dir "$LK_DATA_DIR" \
  --content-root "$LK_CONTENT_ROOT" \
  --client-root "$LK_CLIENT_ROOT"
