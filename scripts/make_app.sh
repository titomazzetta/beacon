#!/bin/bash
# Builds Beacon.app: a small launcher with Beacon's icon that starts app/scripts/launch.sh
# from the folder it sits in. Used by build_usb.sh, and by the tests on a Mac.
#
#   scripts/make_app.sh /path/to/Beacon.app
#
# osacompile signs the app it makes; changing the icon and name afterwards breaks that
# seal, and macOS refuses to open an app whose seal is broken. So sign it again last.
set -euo pipefail
OUT="${1:?Usage: scripts/make_app.sh /path/to/Beacon.app}"
HERE="$(cd "$(dirname "$0")" && pwd)"

rm -rf "$OUT"
osacompile -o "$OUT" "$HERE/Beacon.applescript"
cp -X "$HERE/Beacon.icns" "$OUT/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Beacon" "$OUT/Contents/Info.plist"
xattr -cr "$OUT"                                   # no download flags or stray metadata
codesign --force --sign - "$OUT" 2>/dev/null      # sign again, for this Mac and any other
codesign --verify --strict "$OUT"                  # stops here if the seal isn't intact
