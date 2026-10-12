#!/bin/bash
# Build a Beacon drive. Run on a Mac with internet; the drive then runs offline on any Mac
# with macOS 14 Sonoma or newer (Apple Silicon, or Intel Macs from about 2018 on).
#
#   ./scripts/build_usb.sh /Volumes/BEACON                    # asks a few questions
#   ./scripts/build_usb.sh /Volumes/BEACON --tier extended --region "Denver" --radius 300
#   ./scripts/build_usb.sh /Volumes/BEACON --models "qwen3:4b qwen3:14b qwen3.6:27b"
#   ./scripts/build_usb.sh /Volumes/BEACON --ollama-version v0.40.2   # pin a tested engine
#   ./scripts/build_usb.sh /Volumes/BEACON --no-mesh                  # skip the Meshtastic radio add-on
#
# Safe to re-run any time: finished downloads are skipped, interrupted ones resume.
# Every program it downloads is checked against a published or pinned SHA-256 hash first.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-}"; [ $# -gt 0 ] && shift
TIER=""; MODELS=""; REGION=""; RADIUS="300"; MAPS=1; OLLAMA_VERSION="latest"; MESH=1; VERIFY=1
PY_VER="3.12"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --radius) RADIUS="$2"; shift 2 ;;
    --ollama-version) OLLAMA_VERSION="$2"; shift 2 ;;
    --no-maps) MAPS=0; shift ;;
    --no-mesh) MESH=0; shift ;;
    --no-verify) VERIFY=0; shift ;;     # only if a publisher stops posting checksums
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done

say()  { printf "\n\033[1;33m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[0;31m  ! %s\033[0m\n" "$*"; }
[ -n "$TARGET" ] && [ -d "$TARGET" ] || { echo "Usage: $0 /Volumes/YOUR_DRIVE [--tier core|extended|complete|everything] [--region CITY] [--models \"...\"]"; exit 1; }
[ "$(uname)" = "Darwin" ] || { echo "Run this on a Mac."; exit 1; }

# ---- the drive's format
FS="$(diskutil info "$TARGET" 2>/dev/null | awk -F: '/File System Personality/{gsub(/^ +/,"",$2); print $2}' || true)"
case "$FS" in
  *FAT32*|*MS-DOS*)
    warn "This drive is FAT32, which can't hold files over 4 GB."
    warn "In Disk Utility, erase it as APFS (best for Macs) and run this again."
    exit 1 ;;
  *ExFAT*|*exFAT*)
    COPY=(rsync -rLt)       # exFAT has no symlinks or Unix permissions: copy real files
    echo "Note: this drive is exFAT. That works, but APFS is faster and more reliable on Macs." ;;
  *)
    COPY=(rsync -a) ;;
esac

# ---- encryption: the household info and your notes live on this drive
ENC="$(diskutil info "$TARGET" 2>/dev/null | awk -F: '/FileVault|Encrypted/{gsub(/^ +/,"",$2); print $2; exit}' || true)"
case "$ENC" in
  Yes*) echo "Drive encryption: on." ;;
  *) warn "This drive isn't encrypted. Anyone who finds it could read your household info."
     warn "To lock it with a password (APFS drives): in Finder, Control-click the drive and choose Encrypt." ;;
esac

# ---- a few questions if run without options
if [ -z "$TIER" ] && [ -t 0 ]; then
  echo; echo "Which library tier?"
  echo "  1) Core        the essentials (64 GB drive)"
  echo "  2) Extended    + repair, off-grid, homesteading, reading shelf (128 GB)"
  echo "  3) Complete    + WikiHow, Wikipedia intros, learning (256 GB)"
  echo "  4) Everything  + all of Wikipedia (512 GB or more)"
  read -r -p "Choose 1-4 [1]: " n
  case "${n:-1}" in 2) TIER=extended ;; 3) TIER=complete ;; 4) TIER=everything ;; *) TIER=core ;; esac
  read -r -p "Detailed map around which town or city? (Enter to skip): " REGION
fi
TIER="${TIER:-core}"
MODELS="${MODELS:-qwen3:4b qwen3:14b}"   # light brain for 8 GB Macs + strong brain for 16 GB+

L="$TARGET/Beacon"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/beacon-build.XXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$L"/{app,runtime,ollama/mac,models,library/zim,library/manuals,library/books,maps,data}
touch "$TARGET/.metadata_never_index"     # keep Spotlight from crawling gigabytes of archives
echo "Drive: $TARGET (${FS:-unknown format}), $(df -h "$TARGET" | awk 'NR==2{print $4}') free, $TIER tier"

fetch() { # url dest: resumable, skips if complete
  local url="$1" dest="$2" size have
  size="$(curl -sIL "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{gsub(/\r/,"",v); print v}' || true)"
  have="$( [ -f "$dest" ] && stat -f%z "$dest" || echo 0)"
  if [ -n "$size" ] && [ "$have" = "$size" ]; then echo "  ✓ $(basename "$dest") (already downloaded)"; return 0; fi
  echo "  ↓ $(basename "$dest") ${size:+($((size/1024/1024)) MB)}"
  curl -fL --retry 3 -C - -o "$dest" "$url" --progress-bar
}

verify() { # file sums_file: the file's SHA-256 must match its line in the publisher's checksum list
  local file="$1" sums="$2" want got
  [ $VERIFY = 1 ] || { warn "Skipping checksum check for $(basename "$file") (--no-verify)"; return 0; }
  want="$(grep -E "[ */]$(basename "$file" | sed 's/[.+]/\\&/g')\$" "$sums" | awk '{print $1}' | head -1 || true)"
  [ -n "$want" ] || { warn "No published checksum for $(basename "$file"). Stopping to be safe (or rerun with --no-verify)."; exit 1; }
  got="$(shasum -a 256 "$file" | awk '{print $1}')"
  if [ "$want" != "$got" ]; then
    rm -f "$file"
    warn "$(basename "$file") didn't match its published checksum, so it was deleted. Run this again."
    exit 1
  fi
  echo "  ✓ checksum verified: $(basename "$file")"
}

record() { # name file sha256: a download, kept on the drive so the software list survives re-runs
  { grep -v "^$1 " "$L/data/downloads.txt" 2>/dev/null || true; echo "$1 $2 $3"; } > "$WORK/downloads.txt"
  mv "$WORK/downloads.txt" "$L/data/downloads.txt"
}

# ---------------------------------------------------------------- the app
say "Copying Beacon"
rsync -rt --delete --exclude .git --exclude data --exclude library --exclude config.json --exclude __pycache__ \
  --exclude tests --exclude .github --exclude docs --exclude platforms "$REPO/" "$L/app/"
chmod +x "$L/app/scripts/launch.sh" 2>/dev/null || true
rsync -rt "$REPO/library/manuals/" "$L/library/manuals/"
cp "$REPO/START-HERE.txt" "$TARGET/START-HERE.txt"; cp "$REPO/START-HERE.txt" "$L/START-HERE.txt"
cp "$REPO/scripts/Beacon (with Terminal).command" "$L/"; chmod +x "$L/Beacon (with Terminal).command" 2>/dev/null || true

say "Building Beacon.app"
osacompile -o "$WORK/Beacon.app" "$REPO/scripts/Beacon.applescript"
cp "$REPO/scripts/Beacon.icns" "$WORK/Beacon.app/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Beacon" "$WORK/Beacon.app/Contents/Info.plist" 2>/dev/null || true
rm -rf "$L/Beacon.app"; "${COPY[@]}" "$WORK/Beacon.app" "$L/"
echo "  ✓ Beacon.app"

# ---------------------------------------------------------------- portable Python
say "Portable Python $PY_VER (Apple Silicon and Intel)"
PBS="https://github.com/astral-sh/python-build-standalone/releases"
py_sums() { # the latest release's checksum list, which also names every file in the release
  [ -s "$WORK/py-SHA256SUMS" ] && return 0
  PY_TAG="$(curl -sI "$PBS/latest" | awk 'tolower($1)=="location:"{print $2}' | sed 's#.*/tag/##' | tr -d '\r' || true)"
  [ -n "$PY_TAG" ] || { warn "Couldn't reach GitHub for Python. Check the internet connection and run this again."; exit 1; }
  curl -fsSL "$PBS/download/$PY_TAG/SHA256SUMS" -o "$WORK/py-SHA256SUMS" \
    || { warn "Couldn't download Python's checksum list (release $PY_TAG). Run this again."; exit 1; }
}
for pair in "arm64:aarch64" "x86_64:x86_64"; do
  name="${pair%%:*}"; triple="${pair##*:}"
  if [ -e "$L/runtime/python-$name/bin/python3" ]; then echo "  ✓ python-$name"; continue; fi
  py_sums
  fname="$(awk '{print $2}' "$WORK/py-SHA256SUMS" | grep -E "^cpython-${PY_VER//./\\.}\.[0-9]+\+[0-9]+-$triple-apple-darwin-install_only\.tar\.gz\$" | head -1 || true)"
  [ -n "$fname" ] || { warn "Couldn't find Python $PY_VER for $name Macs in release $PY_TAG"; exit 1; }
  fetch "$PBS/download/$PY_TAG/${fname//+/%2B}" "$WORK/$fname"    # GitHub writes the + as %2B
  verify "$WORK/$fname" "$WORK/py-SHA256SUMS"
  mv "$WORK/$fname" "$WORK/py-$name.tar.gz"
  record "python-$name" "$fname" "$(shasum -a 256 "$WORK/py-$name.tar.gz" | awk '{print $1}')"
  mkdir -p "$WORK/python-$name"
  tar -xzf "$WORK/py-$name.tar.gz" -C "$WORK/python-$name" --strip-components 1   # on the Mac's own disk
  "${COPY[@]}" "$WORK/python-$name/" "$L/runtime/python-$name/"                     # then onto the drive
done

HOST_ARCH="$(uname -m)"; [ "$(sysctl -in sysctl.proc_translated 2>/dev/null)" = "1" ] && HOST_ARCH="arm64"
HPY="$WORK/python-$HOST_ARCH/bin/python3"
[ -x "$HPY" ] || HPY="$L/runtime/python-$HOST_ARCH/bin/python3"

say "Python packages (pinned and hash-checked)"
for pair in "arm64:macosx_14_0_arm64" "x86_64:macosx_14_0_x86_64"; do
  name="${pair%%:*}"; plat="${pair##*:}"
  PIP=("$HPY" -m pip install --target "$L/runtime/site-$name" --upgrade --only-binary=:all:
       --python-version "$PY_VER" --implementation cp --platform "$plat" -q --require-hashes)
  "${PIP[@]}" -r "$REPO/scripts/requirements-mac.lock" && echo "  ✓ site-$name" || { warn "Package install failed for $name Macs"; exit 1; }
  if [ $MESH = 1 ]; then  # optional Meshtastic radio support (GPL-3.0), USB and Wi-Fi only
    "${PIP[@]}" --no-deps -r "$REPO/scripts/requirements-mesh.lock" && echo "  ✓ Meshtastic add-on ($name)" || warn "Meshtastic add-on failed for $name Macs"
  fi
done

# ---------------------------------------------------------------- the AI engine
say "AI engine (Ollama $OLLAMA_VERSION)"
if [ -z "$(find "$L/ollama/mac" -type f -name ollama 2>/dev/null | head -1)" ]; then
  if [ "$OLLAMA_VERSION" = "latest" ]; then
    OURL="https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz"
  else
    OURL="https://github.com/ollama/ollama/releases/download/$OLLAMA_VERSION/ollama-darwin.tgz"
  fi
  fetch "$OURL" "$WORK/ollama-darwin.tgz"
  curl -fsSL "${OURL%/ollama-darwin.tgz}/sha256sum.txt" -o "$WORK/ollama-sums.txt" || true
  verify "$WORK/ollama-darwin.tgz" "$WORK/ollama-sums.txt"
  OLLAMA_HASH="$(shasum -a 256 "$WORK/ollama-darwin.tgz" | awk '{print $1}')"
  mkdir -p "$WORK/ollama"; tar -xzf "$WORK/ollama-darwin.tgz" -C "$WORK/ollama"
  "${COPY[@]}" "$WORK/ollama/" "$L/ollama/mac/"
fi
OLLAMA_BIN="$(find "$L/ollama/mac" -type f -name ollama | head -1 || true)"
[ -n "$OLLAMA_BIN" ] || { warn "The AI engine download had no ollama program in it. Try --ollama-version with an older release."; exit 1; }
chmod +x "$OLLAMA_BIN" 2>/dev/null || true; xattr -dr com.apple.quarantine "$L/ollama" 2>/dev/null || true
ollama_version() { "$OLLAMA_BIN" --version 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)+' | tail -1 || true; }
echo "  ✓ Ollama $(ollama_version)"
[ -z "${OLLAMA_HASH:-}" ] || record ollama ollama-darwin.tgz "$OLLAMA_HASH"

export OLLAMA_HOST="127.0.0.1:11435" OLLAMA_MODELS="$L/models"
"$OLLAMA_BIN" serve >"$L/data/ollama-build.log" 2>&1 &
OPID=$!; trap '{ kill $OPID && wait $OPID; } 2>/dev/null || true; rm -rf "$WORK"' EXIT   # wait, so bash doesn't print "Terminated"
for _ in $(seq 1 60); do curl -s "http://$OLLAMA_HOST/api/version" >/dev/null && break; sleep 0.5; done

export BEACON_OLLAMA_URL="http://$OLLAMA_HOST" BEACON_DATA_ROOT="$L" PYTHONNOUSERSITE=1
export PYTHONPATH="$L/runtime/site-$HOST_ARCH:$L/app" PYTHONPYCACHEPREFIX="$WORK/pycache"
INSTALL=("$HPY" -m beacon.installer)

say "AI brains: $MODELS"
"${INSTALL[@]}" --models "$MODELS" || warn "Some models didn't download; add them later in the Library tab."

say "Checking the AI runs from the drive"
SMALLEST="$(echo "$MODELS" | awk '{print $1}')"
if curl -s -m 300 "http://$OLLAMA_HOST/api/generate" -d "{\"model\":\"$SMALLEST\",\"prompt\":\"Reply with one word: READY\",\"stream\":false,\"options\":{\"num_predict\":8}}" | grep -q '"response"'; then
  echo "  ✓ $SMALLEST answered from the drive"
else
  warn "The AI didn't answer. See $L/data/ollama-build.log. Try --ollama-version with an older release."
fi

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

say "Indexing the manuals so the AI can search them"
"$HPY" -m beacon.ingest_cli || warn "Indexing failed; use 'Index manuals' in the Library tab."

say "Software list (what's on this drive, with versions and hashes)"
{
  echo "Beacon drive built $(date '+%Y-%m-%d %H:%M') on macOS $(sw_vers -productVersion)"
  echo; echo "Downloaded programs (name, file, SHA-256):"; cat "$L/data/downloads.txt" 2>/dev/null || echo "  (not recorded)"
  echo; echo "AI engine: Ollama $(ollama_version)"
  for name in arm64 x86_64; do
    echo; echo "Python packages for $name Macs:"; "$HPY" -m pip list --path "$L/runtime/site-$name" --format=freeze 2>/dev/null
  done
  echo; echo "Bundled web libraries:"; cat "$REPO/static/vendor/VERSIONS.txt"
} > "$L/data/SBOM.txt"
echo "  ✓ Beacon/data/SBOM.txt"

dot_clean -m "$L" 2>/dev/null || true
say "Done. Free space left: $(df -h "$TARGET" | awk 'NR==2{print $4}')"
cat <<EOF

  Open the drive, then the Beacon folder, and double-click Beacon.
  START-HERE.txt at the top of the drive explains everything else.
EOF
