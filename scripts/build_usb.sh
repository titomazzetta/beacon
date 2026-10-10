#!/bin/bash
# Build a Beacon USB drive. Run on a Mac with internet; the drive then runs offline on
# Macs (macOS 14 Sonoma or newer) and Windows 10/11 PCs.
#
#   ./scripts/build_usb.sh /Volumes/BEACON                      # asks a few questions
#   ./scripts/build_usb.sh /Volumes/BEACON --tier extended --region "Atlanta" --radius 300
#   ./scripts/build_usb.sh /Volumes/BEACON --tier core --models "qwen3:4b" --no-windows
#
# Safe to re-run any time: finished downloads are skipped, interrupted ones resume.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-}"; [ $# -gt 0 ] && shift
TIER=""; MODELS=""; REGION=""; RADIUS="300"; WINDOWS=1; MAPS=1
PY_VER="3.12"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --radius) RADIUS="$2"; shift 2 ;;
    --no-windows) WINDOWS=0; shift ;;
    --no-maps) MAPS=0; shift ;;
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done

say()  { printf "\n\033[1;33m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[0;31m  ! %s\033[0m\n" "$*"; }
[ -n "$TARGET" ] && [ -d "$TARGET" ] || { echo "Usage: $0 /Volumes/YOUR_USB [--tier core|extended|complete|everything] [--region CITY] [--models \"...\"] [--no-windows] [--no-maps]"; exit 1; }
[ "$(uname)" = "Darwin" ] || { echo "Run this on a Mac."; exit 1; }

# ---- a few questions if run without options
if [ -z "$TIER" ] && [ -t 0 ]; then
  echo; echo "Which library tier?"
  echo "  1) Core        essentials (64 GB drive)"
  echo "  2) Extended    + repair, off-grid, homesteading, reading shelf (128 GB)"
  echo "  3) Complete    + WikiHow and Wikipedia intros (256 GB)"
  echo "  4) Everything  + all of Wikipedia (512 GB+)"
  read -r -p "Choose 1-4 [1]: " n
  TIER=$(case "${n:-1}" in 2) echo extended;; 3) echo complete;; 4) echo everything;; *) echo core;; esac)
  read -r -p "Detailed map around which town or city? (Enter to skip): " REGION
fi
TIER="${TIER:-core}"
MODELS="${MODELS:-qwen3:4b qwen3:14b}"   # light brain for 8 GB machines + strong brain for 16 GB+

L="$TARGET/Beacon"
mkdir -p "$L"/{app,runtime,ollama,models,library/zim,library/manuals,library/books,maps,data}

FS="$(diskutil info "$TARGET" 2>/dev/null | awk -F: '/File System Personality/{gsub(/^ +/,"",$2); print $2}')"
if echo "$FS" | grep -qi "FAT32"; then
  warn "This drive is FAT32, which can't store files over 4 GB."
  warn "Reformat it as exFAT in Disk Utility (works on Mac and Windows), then re-run."
  exit 1
fi
echo "Drive: $TARGET (${FS:-unknown filesystem}) · free: $(df -h "$TARGET" | awk 'NR==2{print $4}') · tier: $TIER"

fetch() { # url dest: resumable, skips if complete
  local url="$1" dest="$2" size have
  size="$(curl -sIL "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{gsub(/\r/,"",v); print v}')"
  have="$( [ -f "$dest" ] && stat -f%z "$dest" || echo 0)"
  if [ -n "$size" ] && [ "$have" = "$size" ]; then echo "  ✓ $(basename "$dest") (already downloaded)"; return 0; fi
  echo "  ↓ $(basename "$dest") ${size:+($((size/1024/1024)) MB)}"
  curl -fL --retry 3 -C - -o "$dest" "$url" --progress-bar
}

gh_assets() { # repo -> list of download URLs for the latest release (no API rate limit)
  local repo="$1" tag
  tag="$(curl -sI "https://github.com/$repo/releases/latest" | awk 'tolower($1)=="location:"{print $2}' | sed 's#.*/tag/##' | tr -d '\r')"
  if [ -n "$tag" ]; then
    curl -sL "https://github.com/$repo/releases/expanded_assets/$tag" \
      | grep -oE "/$repo/releases/download/$tag/[^\"?#]+" | sort -u | sed 's#^#https://github.com#'
  else
    curl -fsSL "https://api.github.com/repos/$repo/releases/latest" | grep -o '"browser_download_url": *"[^"]*"' | sed 's/.*"\(http[^"]*\)"/\1/'
  fi
}

# ---------------------------------------------------------------- app
say "Copying the Beacon app"
rsync -a --delete --exclude .git --exclude data --exclude library --exclude config.json \
  --exclude __pycache__ --exclude tests --exclude .github --exclude docs "$REPO/" "$L/app/"
rsync -a "$REPO/library/manuals/" "$L/library/manuals/"
cp "$REPO/START-HERE.txt" "$TARGET/START-HERE.txt"; cp "$REPO/START-HERE.txt" "$L/START-HERE.txt"
cp "$REPO/scripts/Beacon.command" "$L/Beacon.command"; chmod +x "$L/Beacon.command"
cp "$REPO/scripts/Beacon.bat" "$L/Beacon.bat"

# ---------------------------------------------------------------- portable Python
say "Portable Python $PY_VER (Mac Apple Silicon, Mac Intel$( [ $WINDOWS = 1 ] && echo ", Windows"))"
PYURLS="$(gh_assets astral-sh/python-build-standalone | grep -E "cpython-${PY_VER//./\\.}\.[0-9]+\+[0-9]+-[a-z0-9_]+-[a-z0-9_-]+-install_only\.tar\.gz$" || true)"
TRIPLES="arm64:aarch64-apple-darwin x86_64:x86_64-apple-darwin"
[ $WINDOWS = 1 ] && TRIPLES="$TRIPLES windows:x86_64-pc-windows-msvc"
for pair in $TRIPLES; do
  name="${pair%%:*}"; triple="${pair##*:}"
  if [ -e "$L/runtime/python-$name/bin/python3" ] || [ -e "$L/runtime/python-$name/python.exe" ]; then echo "  ✓ python-$name"; continue; fi
  url="$(echo "$PYURLS" | grep -- "-$triple-install_only" | head -1)"
  [ -n "$url" ] || { warn "Couldn't find a Python download for $name"; exit 1; }
  fetch "$url" "$L/runtime/py-$name.tar.gz"
  mkdir -p "$L/runtime/python-$name"
  tar -xzf "$L/runtime/py-$name.tar.gz" -C "$L/runtime/python-$name" --strip-components 1
  rm -f "$L/runtime/py-$name.tar.gz"
done

HOST_ARCH="$(uname -m)"; [ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ] && HOST_ARCH="arm64"
HPY="$L/runtime/python-$HOST_ARCH/bin/python3"

say "Python packages"
PLATS="arm64:macosx_14_0_arm64 x86_64:macosx_14_0_x86_64"
[ $WINDOWS = 1 ] && PLATS="$PLATS windows:win_amd64"
for pair in $PLATS; do
  name="${pair%%:*}"; plat="${pair##*:}"
  "$HPY" -m pip install --target "$L/runtime/site-$name" --upgrade --only-binary=:all: \
     --python-version "$PY_VER" --implementation cp --platform "$plat" -q \
     -r "$REPO/requirements.txt" && echo "  ✓ site-$name" || warn "Package install failed for $name"
done

# ---------------------------------------------------------------- Ollama (the AI engine)
say "AI engine (Ollama)"
if [ -z "$(find "$L/ollama/mac" -type f -name ollama 2>/dev/null | head -1)" ]; then
  mkdir -p "$L/ollama/mac"
  fetch "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz" "$L/ollama/ollama-darwin.tgz"
  tar -xzf "$L/ollama/ollama-darwin.tgz" -C "$L/ollama/mac"; rm -f "$L/ollama/ollama-darwin.tgz"
fi
if [ $WINDOWS = 1 ] && [ ! -f "$L/ollama/windows/ollama.exe" ]; then
  mkdir -p "$L/ollama/windows"
  fetch "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip" "$L/ollama/ollama-windows.zip"
  ditto -x -k "$L/ollama/ollama-windows.zip" "$L/ollama/windows"; rm -f "$L/ollama/ollama-windows.zip"
fi
OLLAMA_BIN="$(find "$L/ollama/mac" -type f -name ollama | head -1)"
chmod +x "$OLLAMA_BIN"; xattr -dr com.apple.quarantine "$L/ollama" 2>/dev/null || true
echo "  ✓ $("$OLLAMA_BIN" --version 2>/dev/null | tail -1)"

export OLLAMA_HOST="127.0.0.1:11435" OLLAMA_MODELS="$L/models"
"$OLLAMA_BIN" serve >"$L/data/ollama-build.log" 2>&1 &
OPID=$!; trap 'kill $OPID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -s "http://$OLLAMA_HOST/api/version" >/dev/null && break; sleep 0.5; done

export BEACON_OLLAMA_URL="http://$OLLAMA_HOST" BEACON_DATA_ROOT="$L" PYTHONNOUSERSITE=1
export PYTHONPATH="$L/runtime/site-$HOST_ARCH:$L/app"
INSTALL=("$HPY" -m beacon.installer)

say "AI brains: $MODELS"
"${INSTALL[@]}" --models "$MODELS" || warn "Some models didn't download; add them later in the Library tab."

say "Library: $TIER tier"
"${INSTALL[@]}" --tier "$TIER" || warn "Some items failed; retry later in the Library tab."

if [ $MAPS = 1 ]; then
  say "Maps"
  if [ -n "$REGION" ]; then
    "${INSTALL[@]}" --maps places,world --region "$REGION" --radius "$RADIUS" || warn "Map step had problems; retry in the Library tab."
  else
    "${INSTALL[@]}" --maps places,world || warn "Map step had problems; retry in the Library tab."
  fi
fi

say "Indexing manuals so the AI can search them"
"$HPY" -m beacon.ingest_cli || warn "Indexing failed; use 'Index manuals folder' in the app."

dot_clean -m "$L" 2>/dev/null || true
say "Done. Free space left: $(df -h "$TARGET" | awk 'NR==2{print $4}')"
cat <<EOF

  Mac:     open the drive > Beacon > right-click Beacon.command > Open (first time only).
  Windows: open the drive > Beacon > double-click Beacon.bat.
  Read START-HERE.txt on the drive for everything else.
EOF
