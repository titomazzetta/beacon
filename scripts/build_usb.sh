#!/bin/bash
# Build a Beacon drive. Run on a Mac with internet; the drive then runs offline on any Mac
# with macOS 14 Sonoma or newer (Apple Silicon, or Intel Macs from about 2018 on).
#
#   ./scripts/build_usb.sh /Volumes/BEACON                    # suggests what fits this drive and Mac, then asks
#   ./scripts/build_usb.sh /Volumes/BEACON --fit --region "Denver"   # build the suggestion, no questions
#   ./scripts/build_usb.sh /Volumes/BEACON --quick                   # Core + the light brain: the fastest first load
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
TIER=""; MODELS=""; REGION=""; RADIUS="300"; MAPS=1; OLLAMA_VERSION="latest"; MESH=1; VERIFY=1; FIT=0; QUICK=0
PY_VER="3.12"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --fit) FIT=1; shift ;;
    --quick) QUICK=1; shift ;;
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
[ -n "$TARGET" ] || { echo "Usage: $0 /Volumes/YOUR_DRIVE [--tier core|extended|complete|everything] [--region CITY] [--models \"...\"]"; exit 1; }
[ -d "$TARGET" ] || { warn "Can't find $TARGET. Check that the drive is plugged in and the name is right (ls /Volumes lists them)."; exit 1; }
[ -w "$TARGET" ] || { warn "You don't have permission to write to $TARGET."
  warn "A folder made with sudo: run  sudo chown \"${USER:-$(id -un)}\" \"$TARGET\"  then try again."
  warn "A whole drive: select it in Finder, choose File > Get Info, and tick \"Ignore ownership on this volume\"."; exit 1; }
[ "$(uname)" = "Darwin" ] || { echo "Run this on a Mac."; exit 1; }
MACOS="$(sw_vers -productVersion 2>/dev/null || echo 0)"
[ "${MACOS%%.*}" -ge 14 ] 2>/dev/null || { warn "This Mac has macOS $MACOS. Building a drive needs macOS 14 Sonoma or newer, the same as using one."; exit 1; }

# ---- not while Beacon is open: two programs writing the same records would lose downloads
if curl -s -m 2 "http://127.0.0.1:8642/api/ping" >/dev/null 2>&1; then
  warn "Beacon is open. Quit it first (the status button at the top right, then Quit) and run this again."; exit 1
fi

# ---- not a Time Machine backup drive: macOS won't open apps stored on one
MOUNT="$(df -P "$TARGET" | tail -1 | sed -E 's/^.*[0-9]+% +//' || true)"
if [ -d "$MOUNT/Backups.backupdb" ] || \
   tmutil destinationinfo 2>/dev/null | sed -n 's/^Mount Point *: *//p' | grep -xF "$MOUNT" >/dev/null; then
  warn "$MOUNT is a Time Machine backup drive. macOS won't open apps stored on one, so Beacon couldn't start."
  warn "Use a separate drive, or give Beacon its own volume: in Disk Utility, select this drive and choose Edit > Add APFS Volume."
  exit 1
fi

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

# ---- what fits: the drive's free space and this Mac's memory decide the suggestion
FREE_GB=$(( $(df -k "$TARGET" | awk 'NR==2{print $4}') / 1048576 ))
RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
RESERVE=$(( FREE_GB / 10 )); [ $RESERVE -lt 5 ] && RESERVE=5          # kept free for your own PDFs, plans and maps
tier_gb()    { case "$1" in core) echo 10 ;; extended) echo 35 ;; complete) echo 70 ;; everything) echo 290 ;; esac; }  # measured Oct 2026
tier_about() { case "$1" in core) echo "Core: the essentials" ;; extended) echo "Extended: + repair, off-grid, homesteading, the reading shelf" ;;
                            complete) echo "Complete: + WikiHow, Wikipedia intros, learning" ;; everything) echo "Everything: + all of Wikipedia (text) and Khan Academy" ;; esac; }
PLAN_MODELS="qwen3:4b"; BRAINS_GB=3                                   # the light brain runs on any Mac, and is the fallback
[ $RAM_GB -ge 16 ] && { PLAN_MODELS="$PLAN_MODELS qwen3:14b"; BRAINS_GB=$((BRAINS_GB + 10)); }
BIG=""; BIG_GB=0                                                      # the strongest brain this Mac can run
if   [ $RAM_GB -ge 96 ]; then BIG="gpt-oss:120b"; BIG_GB=65
elif [ $RAM_GB -ge 32 ]; then BIG="qwen3.6:27b";  BIG_GB=17
elif [ $RAM_GB -ge 24 ]; then BIG="gpt-oss:20b";  BIG_GB=14; fi
[ $QUICK = 1 ] && { BIG=""; BIG_GB=0; PLAN_MODELS="qwen3:4b"; BRAINS_GB=3; }   # quick: the light brain only
plan_tier() { # the largest library that fits beside $1 GB of brains
  local gb="$1" t out=""
  for t in core extended complete everything; do
    [ $(( $(tier_gb $t) + gb + 5 + RESERVE )) -le $FREE_GB ] && out=$t
  done
  echo "$out"
}
PLAN_TIER="$(plan_tier $((BRAINS_GB + BIG_GB)))"
if [ -n "$BIG" ] && [ "$(plan_tier $BRAINS_GB)" != "$PLAN_TIER" ] && [ "$PLAN_TIER" != everything ]; then
  [ $RAM_GB -ge 96 ] && { BIG="qwen3.6:27b"; BIG_GB=17; PLAN_TIER="$(plan_tier $((BRAINS_GB + BIG_GB)))"; }   # Titan costs a whole tier: step down
fi
if [ -n "$BIG" ] && [ "$(plan_tier $BRAINS_GB)" != "$PLAN_TIER" ] && [ "$PLAN_TIER" != everything ]; then
  BIG=""; BIG_GB=0; PLAN_TIER="$(plan_tier $BRAINS_GB)"                 # library before the biggest brain; add it later from the Library tab
fi
[ -z "$BIG" ] || { PLAN_MODELS="$PLAN_MODELS $BIG"; BRAINS_GB=$((BRAINS_GB + BIG_GB)); }
if [ -z "$PLAN_TIER" ]; then
  warn "This drive has $FREE_GB GB free. Even the Core library with the light brain needs about $((10 + 3 + 5)) GB, plus room for your own files."
  [ -n "$TIER" ] || exit 1
  PLAN_TIER=core
fi
PLAN_GB=$(( $(tier_gb $PLAN_TIER) + BRAINS_GB + 5 ))

if [ $QUICK = 1 ]; then
  TIER="${TIER:-core}"; MODELS="${MODELS:-qwen3:4b}"
elif [ $FIT = 1 ]; then
  TIER="${TIER:-$PLAN_TIER}"
elif [ -z "$TIER" ] && [ -t 0 ]; then
  echo
  echo "This drive has $FREE_GB GB free. This Mac has $RAM_GB GB of memory."
  echo "Suggested: $(tier_about $PLAN_TIER), with brains $PLAN_MODELS: about $PLAN_GB GB, leaving $((FREE_GB - PLAN_GB)) GB for your own files."
  echo "  Enter)  build the suggestion"
  echo "  q)      quick first load: Core + the light brain, about $((10 + 3 + 5)) GB; run this again later to add the rest"
  echo "  1-4)    1 Core, 2 Extended, 3 Complete, 4 Everything (about 10, 35, 70 and 290 GB of library)"
  read -r -p "Choice [Enter]: " n
  case "$n" in
    q|Q) TIER=core; MODELS="${MODELS:-qwen3:4b}" ;;
    1) TIER=core ;; 2) TIER=extended ;; 3) TIER=complete ;; 4) TIER=everything ;;
    *) TIER=$PLAN_TIER ;;
  esac
  read -r -p "Detailed map around which town or city? (Enter to skip): " REGION
fi
TIER="${TIER:-core}"
case "$TIER" in core|extended|complete|everything) ;; *) warn "Unknown tier \"$TIER\". Choose core, extended, complete or everything."; exit 1 ;; esac
MODELS="${MODELS:-$PLAN_MODELS}"
echo "Plan: $(tier_about $TIER); brains $MODELS; ${REGION:+detailed map $RADIUS km around $REGION; }$FREE_GB GB free on the drive."

L="$TARGET/Beacon"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/beacon-build.XXXX")"
caffeinate -i -w $$ >/dev/null 2>&1 &     # keep the Mac awake until the build ends
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$L"/{app,runtime,ollama/mac,models,library/zim,library/manuals,library/books,maps,data}
touch "$TARGET/.metadata_never_index"     # keep Spotlight from crawling gigabytes of archives
echo "Drive: $TARGET (${FS:-unknown format})"

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
cp -X "$REPO/START-HERE.txt" "$TARGET/START-HERE.txt"; cp -X "$REPO/START-HERE.txt" "$L/START-HERE.txt"   # -X: no download quarantine flags
cp -X "$REPO/scripts/Beacon (with Terminal).command" "$L/"; chmod +x "$L/Beacon (with Terminal).command" 2>/dev/null || true

say "Building Beacon.app"
if bash "$REPO/scripts/make_app.sh" "$WORK/Beacon.app"; then
  rm -rf "$L/Beacon.app"; "${COPY[@]}" "$WORK/Beacon.app" "$L/"
  echo "  ✓ Beacon.app"
else
  warn "Couldn't build Beacon.app. Start Beacon with \"Beacon (with Terminal)\" on the drive instead."
fi

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

export OLLAMA_HOST="127.0.0.1:11435" OLLAMA_MODELS="$L/models" OLLAMA_NO_CLOUD=1
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
