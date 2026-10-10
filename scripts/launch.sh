#!/bin/bash
# Starts Beacon from the drive. Used by Beacon.app (no Terminal window) and by
# "Beacon (with Terminal).command" (shows the log, handy if something goes wrong).
#   launch.sh background   start in the background, open the browser, exit
#   launch.sh foreground   run in this window; closing the window stops Beacon
MODE="${1:-background}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"      # the Beacon folder on the drive
cd "$HERE" || exit 1
mkdir -p "$HERE/data/logs" "$HERE/data/run"

URL="http://127.0.0.1:8642"
if curl -s -m 2 "$URL/api/ping" >/dev/null 2>&1; then   # already running: just show it
  open "$URL"; exit 0
fi

# Files copied from the internet carry a quarantine flag that blocks the bundled programs.
xattr -dr com.apple.quarantine "$HERE/app" "$HERE/runtime" "$HERE/ollama" 2>/dev/null

ARCH="$(uname -m)"
[ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ] && ARCH="arm64"   # under Rosetta
PY="$HERE/runtime/python-$ARCH/bin/python3"
OLLAMA_BIN="$(find "$HERE/ollama/mac" -maxdepth 4 -type f -name ollama 2>/dev/null | head -1)"
MACOS_MAJOR="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"

fail() { echo "$1" >&2; exit 1; }
[ "${MACOS_MAJOR:-0}" -ge 14 ] || fail "Beacon needs macOS 14 Sonoma or newer. This Mac has macOS $(sw_vers -productVersion). The quick cards in library/manuals/cards still open in any app."
[ -x "$PY" ] || fail "Beacon's Python for $ARCH Macs is missing from the drive. Rebuild the drive."
[ -n "$OLLAMA_BIN" ] || fail "The AI engine is missing from the drive. Rebuild the drive."

export OLLAMA_HOST="127.0.0.1:11435"        # own port: never clashes with an installed Ollama
export OLLAMA_MODELS="$HERE/models"
export BEACON_OLLAMA_URL="http://$OLLAMA_HOST"
export BEACON_DATA_ROOT="$HERE"
export PYTHONPATH="$HERE/runtime/site-$ARCH:$HERE/app"
export PYTHONNOUSERSITE=1
export PYTHONPYCACHEPREFIX="$HOME/Library/Caches/Beacon/pycache"   # keep cache files off the drive

if ! curl -s -m 2 "$BEACON_OLLAMA_URL/api/version" >/dev/null 2>&1; then
  nohup "$OLLAMA_BIN" serve >"$HERE/data/logs/ollama.log" 2>&1 &
  echo $! >"$HERE/data/run/ollama.pid"
fi

wait_for() { for _ in $(seq 1 120); do curl -s -m 1 "$1" >/dev/null 2>&1 && return 0; sleep 0.5; done; return 1; }

if [ "$MODE" = "foreground" ]; then
  echo "Starting Beacon on $(sw_vers -productName) $(sw_vers -productVersion) ($ARCH)…"
  stop() { [ -f "$HERE/data/run/ollama.pid" ] && kill "$(cat "$HERE/data/run/ollama.pid")" 2>/dev/null; rm -f "$HERE/data/run/"*.pid; }
  trap stop EXIT INT TERM
  ( wait_for "$URL/api/ping" && open "$URL" ) &
  "$PY" -m beacon --no-browser
else
  nohup "$PY" -m beacon --no-browser >"$HERE/data/logs/beacon.log" 2>&1 &
  echo $! >"$HERE/data/run/beacon.pid"
  if wait_for "$URL/api/ping"; then
    open "$URL"
  else
    fail "Beacon didn't start. Details are in Beacon/data/logs/beacon.log on the drive. $(tail -3 "$HERE/data/logs/beacon.log" 2>/dev/null)"
  fi
fi
