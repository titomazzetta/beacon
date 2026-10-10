#!/bin/bash
# Starts Beacon in a Terminal window that shows what's happening.
# Use this if Beacon.app doesn't start. Closing this window stops Beacon.
exec /bin/bash "$(cd "$(dirname "$0")" && pwd)/app/scripts/launch.sh" foreground
