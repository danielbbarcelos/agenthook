#!/usr/bin/env bash
# Upgrade an installed agenthook in place, from the source clone.
#
# Pulls the latest source, rebuilds the wheel (with the web panel baked in) and
# reinstalls it; optionally rebuilds the Docker images; then restarts the systemd
# service. Idempotent — safe to re-run.
#
# YOUR DATA IS SAFE: all runtime state (config.yaml, instances/, jobs.db, repos/)
# lives under AGENTHOOK_HOME (~/.agenthook by default), which this script NEVER
# touches. Upgrading only replaces installed code.
#
# Prereqs on the host: git, python + `build` (`pip install build`), and pipx
# (falls back to `pip`); npm for the panel; docker for --images.
#
# Usage (run from the source clone, as the agenthook user):
#   deploy/upgrade.sh [--ref <git-ref>] [--images] [--skip-web] [--no-restart]
set -euo pipefail

REF=""
WITH_IMAGES=0
SKIP_WEB=0
NO_RESTART=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)        REF="${2:-}"; shift 2 ;;
    --images)     WITH_IMAGES=1; shift ;;
    --skip-web)   SKIP_WEB=1; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *)            echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."   # repo root
say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# Resolve a Python interpreter (some hosts ship only `python3`, no `python`).
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "error: no python interpreter found (need python3 or python) — install Python 3" >&2
  exit 1
fi

say "Updating source"
git fetch --tags origin
if [ -n "$REF" ]; then
  git checkout "$REF"
else
  git pull --ff-only
fi
echo "now at: $(git describe --tags --always)"

if [ "$SKIP_WEB" -eq 0 ]; then
  if command -v npm >/dev/null 2>&1; then
    say "Rebuilding web panel"
    ( cd web && npm ci && npm run build )   # -> agenthook/static/panel/
  else
    echo "npm not found — skipping panel rebuild (pass --skip-web to silence)"
  fi
fi

say "Building & installing the wheel"
if ! "$PY" -c "import build" >/dev/null 2>&1; then
  echo "error: the 'build' package is missing — install it with: $PY -m pip install build" >&2
  exit 1
fi
rm -rf dist
"$PY" -m build
WHEEL="$(ls -t dist/agenthook-*.whl | head -1)"
if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$WHEEL"
else
  "$PY" -m pip install --force-reinstall "$WHEEL"
fi
echo "installed: $(basename "$WHEEL")"

if [ "$WITH_IMAGES" -eq 1 ]; then
  say "Rebuilding Docker images"
  docker build -t agenthook/runner:latest agenthook/docker
  docker build -t agenthook/egress:latest agenthook/egress
fi

if [ "$NO_RESTART" -eq 0 ]; then
  say "Restarting service"
  if systemctl --user restart agenthook 2>/dev/null; then
    systemctl --user --no-pager status agenthook | head -5 || true
  else
    echo "systemd --user service 'agenthook' not found — restart it manually"
  fi
fi

say "Done — config & instances in ${AGENTHOOK_HOME:-$HOME/.agenthook} were untouched"
