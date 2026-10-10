#!/bin/bash
# Lantern launcher — double-click on any Mac (Apple Silicon or Intel).
# First time only: right-click this file → Open → Open (macOS asks once).

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
mkdir -p "$HERE/data"

# Files copied from a download carry a quarantine flag that blocks the bundled programs.
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null

ARCH="$(uname -m)"
[ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ] && ARCH="arm64"   # running under Rosetta
PY="$HERE/runtime/python-$ARCH/bin/python3"
OLLAMA_BIN="$(find "$HERE/ollama" -maxdepth 3 -type f -name ollama -perm -u+x 2>/dev/null | head -1)"

if [ ! -x "$PY" ]; then echo "Missing Python runtime for $ARCH. Re-run the USB build script."; read -r; exit 1; fi
if [ -z "$OLLAMA_BIN" ]; then echo "Missing Ollama. Re-run the USB build script."; read -r; exit 1; fi

# Own port, so it never clashes with an Ollama the Mac may already have installed.
export OLLAMA_HOST="127.0.0.1:11435"
export OLLAMA_MODELS="$HERE/models"
export LANTERN_OLLAMA_URL="http://$OLLAMA_HOST"
export LANTERN_DATA_ROOT="$HERE"
export PYTHONPATH="$HERE/runtime/site-$ARCH:$HERE/app"
export PYTHONNOUSERSITE=1

echo "Starting Lantern on $(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null) ($ARCH)…"

OPID=""
if ! curl -s "$LANTERN_OLLAMA_URL/api/version" >/dev/null 2>&1; then
  "$OLLAMA_BIN" serve >"$HERE/data/ollama.log" 2>&1 &
  OPID=$!
  for _ in $(seq 1 60); do
    curl -s "$LANTERN_OLLAMA_URL/api/version" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
cleanup() { [ -n "$OPID" ] && kill "$OPID" 2>/dev/null; }
trap cleanup EXIT INT TERM

"$PY" -m lantern
