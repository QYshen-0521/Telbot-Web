#!/usr/bin/env bash
# Install apt/dpkg hook that blocks removal of Debian Telbot INDI driver packages.
#
# Usage: cd ~/Telbot && sudo bash deploy/install-indi-apt-guard.sh
# See docs/INDI_APT_STACK.md

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_SRC="${REPO_ROOT}/deploy/telbot-indi-apt-guard-hook.sh"
HOOK_DST="/usr/local/lib/telbot-deploy/telbot-indi-apt-guard-hook.sh"
APT_CONF="/etc/apt/apt.conf.d/99telbot-indi-guard"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 sudo 运行本脚本"
  exit 1
fi

GUARD_PY=""
if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  GUARD_PY="${REPO_ROOT}/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  GUARD_PY="$(command -v python3)"
else
  echo "ERROR: 未找到 python3"
  exit 1
fi

# Editable install or PYTHONPATH so -m telbot.indi_apt_guard works from repo
GUARD_PYTHONPATH=""
if ! "${GUARD_PY}" -c "import telbot.indi_apt_guard" 2>/dev/null; then
  GUARD_PYTHONPATH="${REPO_ROOT}/src"
fi

echo "==> Guard python: ${GUARD_PY}"
if [[ -n "${GUARD_PYTHONPATH}" ]]; then
  echo "==> PYTHONPATH: ${GUARD_PYTHONPATH}"
fi

mkdir -p /usr/local/lib/telbot-deploy
sed \
  -e "s|__TELBOT_GUARD_PY__|${GUARD_PY}|g" \
  -e "s|__TELBOT_GUARD_PYTHONPATH__|${GUARD_PYTHONPATH}|g" \
  "${HOOK_SRC}" >"${HOOK_DST}"
chmod 755 "${HOOK_DST}"

cat >"${APT_CONF}" <<EOF
// Telbot: block apt transactions that remove Debian INDI drivers (indi-sbig, indi-bin, …)
// See docs/INDI_APT_STACK.md and: telbot indi apt-guard status
DPkg::Pre-Install-Pkgs {
    "${HOOK_DST}";
};
EOF
chmod 644 "${APT_CONF}"

echo "==> Installed hook: ${HOOK_DST}"
echo "==> Installed apt conf: ${APT_CONF}"
echo ""
echo "手动模拟 apt 前可先检查："
echo "  telbot indi apt-guard check -- apt install <包名>"
echo ""
echo "临时绕过（仅紧急）： TELBOT_INDI_GUARD_DISABLED=1 sudo apt …"
