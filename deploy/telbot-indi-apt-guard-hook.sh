#!/bin/sh
# DPkg::Pre-Install-Pkgs hook — aborts dpkg if transaction would remove Telbot INDI stack.
# Installed by deploy/install-indi-apt-guard.sh (do not edit TELBOT_GUARD_PY on Pi by hand).

set -eu

TELBOT_GUARD_PY="__TELBOT_GUARD_PY__"
TELBOT_GUARD_PYTHONPATH="__TELBOT_GUARD_PYTHONPATH__"

if [ ! -x "${TELBOT_GUARD_PY}" ]; then
  echo "telbot-indi-guard: 未找到 ${TELBOT_GUARD_PY}，跳过保护（请运行 install-indi-apt-guard.sh）" >&2
  exit 0
fi

if [ -n "${TELBOT_GUARD_PYTHONPATH}" ]; then
  export PYTHONPATH="${TELBOT_GUARD_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
fi

exec "${TELBOT_GUARD_PY}" -m telbot.indi_apt_guard hook
