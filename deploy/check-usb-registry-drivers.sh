#!/usr/bin/env bash
# Verify INDI driver binaries for docs/USB_DEVICE_REGISTRY.md (on-host only).
#
# Usage: bash deploy/check-usb-registry-drivers.sh
#        sudo bash deploy/check-usb-registry-drivers.sh   # optional: dpkg -l

set -euo pipefail

# name|expected install path hint|VID:PID (registry)
ROWS=(
  'indi_lx200gemini|indi-bin|1fc9:1705 Losmandy Gemini'
  'indi_planewave_telescope|deploy/install-indi-planewave-telescope.sh|1cbe:0267 PlaneWave L350 (+ pwi4.service)'
  'indi_celestron_gps|indi-bin|067b:2303 Celestron GPS'
  'indi_sbig_ccd|indi-sbig|0d97:0101 SBIG CCD'
  'indi_qhycfw3_wheel|indi-bin|10c4:ea60 QHY CFW3'
  'indi_oasis_focuser|install-indi-oasis-focuser.sh|338f:a0f0 Oasis Focuser'
  'indi_asi_ccd|indi-asi|03c3:294f ZWO ASI294MC'
  'indi_qhy_ccd|build-indi-3rdparty-qhy-oasis.sh|1618:c175 QHY174M'
)

TOOLS=(indiserver indi_getprop indi_setprop)

ok=0
miss=0

check_binary() {
  local name="$1" hint="$2" usb="$3"
  if command -v "${name}" >/dev/null 2>&1; then
    local path missing
    path="$(command -v "${name}")"
    missing="$(ldd "${path}" 2>/dev/null | grep 'not found' || true)"
    printf 'OK   %-28s %s\n' "${name}" "${path}"
    printf '     %-28s %s\n' '' "install: ${hint} | ${usb}"
    if [[ -n "${missing}" ]]; then
      printf '     %-28s %s\n' '' "ldd missing:"
      while IFS= read -r line; do
        printf '     %-28s %s\n' '' "${line}"
      done <<<"${missing}"
    fi
    ok=$((ok + 1))
    return 0
  fi
  printf 'MISS %-28s (expected: %s)\n' "${name}" "${hint}"
  printf '     %-28s %s\n' '' "${usb}"
  miss=$((miss + 1))
  return 1
}

echo "==> USB_DEVICE_REGISTRY.md — INDI 驱动二进制（本机 PATH）"
echo ""

for row in "${ROWS[@]}"; do
  IFS='|' read -r name hint usb <<<"${row}"
  check_binary "${name}" "${hint}" "${usb}" || true
  echo ""
done

echo "==> INDI 工具"
for t in "${TOOLS[@]}"; do
  if command -v "${t}" >/dev/null 2>&1; then
    printf 'OK   %-20s %s\n' "${t}" "$(command -v "${t}")"
    ok=$((ok + 1))
  else
    printf 'MISS %-20s\n' "${t}"
    miss=$((miss + 1))
  fi
done
echo ""

echo "==> 登记表中无独立驱动（正常）"
echo "     1618:c174 QHY174 引导阶段 — 无 indi_*，上电后变为 1618:c175"
echo ""

if command -v dpkg >/dev/null 2>&1; then
  echo "==> 相关 apt 包（ii = 已安装）"
  for pkg in indi-bin indi-sbig indi-asi libindi-dev libqhy libastroasis; do
    st="$(dpkg-query -W -f='${Status}' "${pkg}" 2>/dev/null || echo 'not installed')"
    if [[ "${st}" == *"install ok installed"* ]]; then
      ver="$(dpkg-query -W -f='${Version}' "${pkg}")"
      printf '     ii  %-20s %s\n' "${pkg}" "${ver}"
    else
      printf '     --  %-20s %s\n' "${pkg}" "(not installed)"
    fi
  done
  echo ""
fi

if pgrep -a indiserver >/dev/null 2>&1; then
  echo "==> 当前 indiserver 进程"
  pgrep -a indiserver | sed 's/^/     /'
  echo ""
else
  echo "==> indiserver 未运行（仅检查二进制时可为空）"
  echo "     插设备后: sudo telbot-select-mount.sh  或  systemctl status indi-telescope"
  echo ""
fi

echo "==> 汇总: OK=$((ok))  MISS=$((miss))"
if [[ "${miss}" -gt 0 ]]; then
  echo "     缺驱动时: deploy/install-indi-drivers-debian.sh"
  echo "               deploy/build-indi-3rdparty-qhy-oasis.sh"
  echo "               deploy/install-indi-oasis-focuser.sh"
  echo "               deploy/install-indi-planewave-telescope.sh"
  echo "     勿 apt autoremove 误删 libqhy / libastroasis"
  exit 1
fi
echo "     全部二进制已在 PATH。插 USB 后可用: telbot preflight"
exit 0
