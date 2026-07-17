#!/bin/bash
# Read one line from /run/telbot/indiserver.args → indiserver argv (e.g. -v indi_lx200gemini indi_sbig_ccd).

set -euo pipefail
ARGS_FILE=/run/telbot/indiserver.args
if [ ! -s "$ARGS_FILE" ]; then
  echo "Missing or empty $ARGS_FILE — run telbot-select-mount.sh or see docs/MOUNT_AUTO.md." >&2
  exit 1
fi
read -r line < "$ARGS_FILE" || exit 1
read -r -a argv <<< "$line"
exec /usr/bin/indiserver "${argv[@]}"
