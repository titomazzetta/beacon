#!/bin/bash
# Build a Lantern USB drive. Run on a Mac that has internet; the result runs on any Mac offline.
#
#   ./scripts/build_usb.sh /Volumes/LANTERN                       # essential library + 2 models
#   ./scripts/build_usb.sh /Volumes/LANTERN --tier recommended
#   ./scripts/build_usb.sh /Volumes/LANTERN --tier full --models "qwen3:4b qwen3:14b qwen3.6:27b"
#
# Safe to re-run: finished downloads are skipped, partial ones resume.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-}"; shift || true
TIER="essential"
MODELS="qwen3:4b qwen3:14b"       # light model for 8 GB Macs + strong model for 16 GB+
EMBED_MODEL="nomic-embed-text"
PY_VER="3.12"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done

say()  { printf "\n\033[1;33m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[0;31m  ! %s\033[0m\n" "$*"; }
[ -n "$TARGET" ] && [ -d "$TARGET" ] || { echo "Usage: $0 /Volumes/YOUR_USB [--tier essential|recommended|full] [--models \"...\"]"; exit 1; }
[ "$(uname)" = "Darwin" ] || { echo "Run this on a Mac."; exit 1; }

L="$TARGET/Lantern"
mkdir -p "$L"/{app,runtime,ollama,models,library/zim,library/manuals,data}

# FAT32 can't hold files over 4 GB (models and big libraries are larger).
FS="$(diskutil info "$TARGET" 2>/dev/null | awk -F: '/File System Personality/{gsub(/^ +/,"",$2); print $2}')"
if echo "$FS" | grep -qi "FAT32"; then
  warn "This drive is FAT32, which can't store files over 4 GB."
  warn "Reformat it as exFAT (works on Mac + Windows) or APFS (Mac only) in Disk Utility, then re-run."
  exit 1
fi
echo "Drive: $TARGET (${FS:-unknown filesystem}), free: $(df -h "$TARGET" | awk 'NR==2{print $4}')"

fetch() { # url dest — resumable, skips if complete
  local url="$1" dest="$2" size have
  size="$(curl -sIL "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{gsub(/\r/,"",v); print v}')"
  have="$( [ -f "$dest" ] && stat -f%z "$dest" || echo 0)"
  if [ -n "$size" ] && [ "$have" = "$size" ]; then echo "  ✓ $(basename "$dest") (already downloaded)"; return 0; fi
  if [ -n "$size" ]; then
    local free; free="$(df -k "$(dirname "$dest")" | awk 'NR==2{print $4*1024}')"
    if [ "$((size - have))" -gt "$free" ]; then warn "Not enough space for $(basename "$dest") ($((size/1024/1024)) MB). Skipping."; return 1; fi
  fi
  echo "  ↓ $(basename "$dest") ${size:+($((size/1024/1024)) MB)}"
  curl -fL --retry 3 -C - -o "$dest" "$url" --progress-bar
}

# ---------------------------------------------------------------- app code
say "Copying the Lantern app"
rsync -a --delete --exclude .git --exclude data --exclude library --exclude config.json \
  --exclude __pycache__ --exclude tests "$REPO/" "$L/app/"
cp "$REPO/scripts/Lantern.command" "$L/Lantern.command"; chmod +x "$L/Lantern.command"
rsync -a "$REPO/library/manuals/" "$L/library/manuals/"

# ---------------------------------------------------------------- portable Python (both chip types)
say "Portable Python $PY_VER for Apple Silicon and Intel"
API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
URLS="$(curl -fsSL "$API" | grep -o '"browser_download_url": *"[^"]*"' | sed 's/.*"\(http[^"]*\)"/\1/' \
       | grep -E "cpython-${PY_VER//./\\.}\.[0-9]+\+[0-9]+-(aarch64|x86_64)-apple-darwin-install_only\.tar\.gz$" || true)"
for pair in "arm64:aarch64" "x86_64:x86_64"; do
  arch="${pair%%:*}"; triple="${pair##*:}"
  if [ -x "$L/runtime/python-$arch/bin/python3" ]; then echo "  ✓ python-$arch"; continue; fi
  url="$(echo "$URLS" | grep "$triple-apple" | head -1)"
  [ -n "$url" ] || { warn "Couldn't find a Python download for $arch"; exit 1; }
  fetch "$url" "$L/runtime/py-$arch.tar.gz"
  mkdir -p "$L/runtime/python-$arch"
  tar -xzf "$L/runtime/py-$arch.tar.gz" -C "$L/runtime/python-$arch" --strip-components 1
  rm -f "$L/runtime/py-$arch.tar.gz"
done

HOST_ARCH="$(uname -m)"; [ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ] && HOST_ARCH="arm64"
HPY="$L/runtime/python-$HOST_ARCH/bin/python3"

say "Installing Python packages for both chip types"
for pair in "arm64:macosx_11_0_arm64" "x86_64:macosx_10_15_x86_64"; do
  arch="${pair%%:*}"; plat="${pair##*:}"
  common=(--target "$L/runtime/site-$arch" --upgrade --only-binary=:all: --python-version "$PY_VER"
          --implementation cp --platform "$plat" --platform macosx_11_0_universal2 -q)
  "$HPY" -m pip install "${common[@]}" flask requests numpy pypdf
  "$HPY" -m pip install "${common[@]}" libzim || warn "libzim unavailable for $arch — Kiwix search disabled on that chip."
  echo "  ✓ site-$arch"
done

# ---------------------------------------------------------------- Ollama
say "Ollama (runs the AI models)"
if [ -z "$(find "$L/ollama" -type f -name ollama 2>/dev/null | head -1)" ]; then
  fetch "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz" "$L/ollama/ollama-darwin.tgz"
  tar -xzf "$L/ollama/ollama-darwin.tgz" -C "$L/ollama"
  rm -f "$L/ollama/ollama-darwin.tgz"
fi
OLLAMA_BIN="$(find "$L/ollama" -type f -name ollama | head -1)"
chmod +x "$OLLAMA_BIN"; xattr -dr com.apple.quarantine "$L/ollama" 2>/dev/null || true
echo "  ✓ $("$OLLAMA_BIN" --version 2>/dev/null | tail -1)"

export OLLAMA_HOST="127.0.0.1:11435" OLLAMA_MODELS="$L/models"
"$OLLAMA_BIN" serve >"$L/data/ollama-build.log" 2>&1 &
OPID=$!; trap 'kill $OPID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -s "http://$OLLAMA_HOST/api/version" >/dev/null && break; sleep 0.5; done

say "Downloading AI models to the drive: $MODELS $EMBED_MODEL"
for m in $EMBED_MODEL $MODELS; do
  "$OLLAMA_BIN" pull "$m" || warn "Couldn't pull $m"
done

# ---------------------------------------------------------------- reference library
say "Reference library (tier: $TIER)"
"$HPY" - "$REPO/catalog.json" "$TIER" >"$L/data/download-plan.tsv" <<'PY'
import json, sys
cat, tier = json.load(open(sys.argv[1])), sys.argv[2]
order = {"essential": 0, "recommended": 1, "full": 2}
want = lambda t: order[t] <= order[tier]
for z in cat["zim"]:
    if want(z["tier"]): print("zim", z["dir"], z["prefix"], z["what"], sep="\t")
for p in cat["pdf"]:
    if want(p["tier"]): print("pdf", p["url"], p["file"], p["what"], sep="\t")
PY

while IFS=$'\t' read -r kind a b what; do
  if [ "$kind" = "zim" ]; then
    listing="$(curl -fsSL "https://download.kiwix.org/zim/$a/" || true)"
    file="$(echo "$listing" | grep -oE "${b//./\\.}_[0-9]{4}-[0-9]{2}\.zim" | sort -u | tail -1)"
    if [ -z "$file" ]; then warn "Not found on Kiwix: $b ($what) — skipped"; continue; fi
    # remove older editions of the same book
    find "$L/library/zim" -name "${b}_*.zim" ! -name "$file" -delete 2>/dev/null || true
    echo "  $what"
    fetch "https://download.kiwix.org/zim/$a/$file" "$L/library/zim/$file" || warn "Download failed: $file"
  else
    echo "  $what"
    fetch "$a" "$L/library/manuals/$b" || warn "Download failed: $b"
  fi
done <"$L/data/download-plan.tsv"

# ---------------------------------------------------------------- index manuals
say "Indexing manuals so they're searchable"
LANTERN_OLLAMA_URL="http://$OLLAMA_HOST" LANTERN_DATA_ROOT="$L" PYTHONNOUSERSITE=1 \
  PYTHONPATH="$L/runtime/site-$HOST_ARCH:$L/app" "$HPY" -m lantern.ingest_cli || warn "Indexing failed; use the button in the app."

dot_clean -m "$L" 2>/dev/null || true
say "Done. Free space left: $(df -h "$TARGET" | awk 'NR==2{print $4}')"
cat <<EOF

  On any Mac: open the drive → Lantern → right-click Lantern.command → Open.
  Not downloaded automatically (add PDFs to Lantern/library/manuals, then click "Index manuals"):
EOF
"$HPY" -c "import json;[print('   •',m['what'],('— '+m['url']) if m['url'] else '') for m in json.load(open('$REPO/catalog.json'))['manual_downloads']]"
