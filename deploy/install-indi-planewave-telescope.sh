#!/usr/bin/env bash
# Install indi_planewave_telescope without apt install astroberry indi-bin (avoids removing Debian indi-sbig).
# Extracts driver from astroberry indi-bin .deb (INDI 2.x build; may run with indiserver 1.9.9).
#
# Prerequisite: PWI4 installed (~/pwi-4.1.8final/run-pwi4, ~/.planewave/PWI4/Settings).
# Usage: cd ~/Telbot && sudo bash deploy/install-indi-planewave-telescope.sh
# Optional: INDI_BIN_DEB=/path/to/indi-bin_*_arm64.deb
#           INDI_LIBINDI1_DEB=/path/to/libindi1_*_arm64.deb
#           ASTROBERRY_INDI_BIN_VER=2.2.1
# See docs/INDI_APT_STACK.md §7.2, docs/MOUNT_AUTO.md (PlaneWave)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASTROBERRY_VER="${ASTROBERRY_INDI_BIN_VER:-2.2.1}"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "${ARCH}" in
  aarch64) ARCH=arm64 ;;
  x86_64) ARCH=amd64 ;;
esac

INDI_BIN_DEB="${INDI_BIN_DEB:-}"
INDI_LIBINDI1_DEB="${INDI_LIBINDI1_DEB:-}"
WORKDIR=""

cleanup() {
  [[ -n "${WORKDIR}" && -d "${WORKDIR}" ]] && rm -rf "${WORKDIR}"
}
trap cleanup EXIT

log() { echo "$*" >&2; }

INDI_BIN_DEB_PATH=""
LIBINDI1_DEB_PATH=""

astroberry_indi_bin_url() {
  echo "https://astroberry.io/debian/pool/main/libi/libindi/indi-bin_${ASTROBERRY_VER}_${ARCH}.deb"
}

astroberry_libindi1_url() {
  echo "https://astroberry.io/debian/pool/main/libi/libindi/libindi1_${ASTROBERRY_VER}_${ARCH}.deb"
}

install_indi2_libs_from_extract() {
  local root="$1"
  local count=0
  while IFS= read -r -d '' so; do
    sudo install -m 644 "${so}" /usr/local/lib/
    count=$((count + 1))
  done < <(find "${root}" \( -path '*/usr/lib/aarch64-linux-gnu/*' -o -path '*/usr/lib/x86_64-linux-gnu/*' -o -path '*/usr/lib/*' \) \
    \( -name 'libindidriver.so*' -o -name 'libindidevice.so*' -o -name 'libindiclient*.so*' -o -name 'libindi*.so*' \) \
    ! -name 'libindialignmentdriver*.so*' \
    -print0 2>/dev/null)
  if [[ "${count}" -gt 0 ]]; then
    log "==> Installed ${count} INDI 2.x lib(s) under /usr/local/lib (for planewave driver only)"
    sudo ldconfig 2>/dev/null || true
  fi
}

download_libindi1_deb() {
  local out_dir="$1" f url
  cd "${out_dir}"
  if [[ -n "${INDI_LIBINDI1_DEB}" ]]; then
    [[ -f "${INDI_LIBINDI1_DEB}" ]] || {
      echo "ERROR: INDI_LIBINDI1_DEB not found: ${INDI_LIBINDI1_DEB}" >&2
      exit 1
    }
    cp -f "${INDI_LIBINDI1_DEB}" "${out_dir}/libindi1.deb"
    LIBINDI1_DEB_PATH="${out_dir}/libindi1.deb"
    return 0
  fi
  log "==> Download astroberry libindi1 .deb (runtime for libindidriver.so.2 — NOT apt install)"
  url="$(astroberry_libindi1_url)"
  curl_download_deb "${url}" "${out_dir}/libindi1.deb"
  LIBINDI1_DEB_PATH="${out_dir}/libindi1.deb"
}

curl_download_deb() {
  local url="$1" dest="$2"
  log "==> curl ${url}"
  if command -v curl >/dev/null; then
    curl -fsSL -o "${dest}" "${url}"
  else
    wget -q -O "${dest}" "${url}"
  fi
}

download_indi_bin_deb() {
  local out_dir="$1" f url
  cd "${out_dir}"
  if [[ -n "${INDI_BIN_DEB}" ]]; then
    [[ -f "${INDI_BIN_DEB}" ]] || {
      echo "ERROR: INDI_BIN_DEB not found: ${INDI_BIN_DEB}" >&2
      exit 1
    }
    cp -f "${INDI_BIN_DEB}" "${out_dir}/indi-bin.deb"
    INDI_BIN_DEB_PATH="${out_dir}/indi-bin.deb"
    return 0
  fi

  log "==> Download astroberry indi-bin_${ASTROBERRY_VER} .deb (NOT apt install; skip Debian 1.9.9 indi-bin)"
  url="$(astroberry_indi_bin_url)"
  curl_download_deb "${url}" "${out_dir}/indi-bin.deb"
  INDI_BIN_DEB_PATH="${out_dir}/indi-bin.deb"
}

echo "==> Prerequisite: Debian indi-bin 1.9.9 + PWI4 (run-pwi4 + ~/.planewave/PWI4/Settings)"
if ! dpkg -s indi-bin >/dev/null 2>&1; then
  echo "ERROR: indi-bin not installed. Run deploy/install-indi-drivers-debian.sh first." >&2
  exit 1
fi

if [[ ! -x "${HOME}/pwi-4.1.8final/run-pwi4" ]] && [[ ! -x "/home/qyshen/pwi-4.1.8final/run-pwi4" ]]; then
  log "WARN: ~/pwi-4.1.8final/run-pwi4 not found — install PWI4 before using PlaneWave INDI driver"
fi

WORKDIR="$(mktemp -d)"
download_indi_bin_deb "${WORKDIR}"
[[ -f "${INDI_BIN_DEB_PATH}" ]] || {
  echo "ERROR: indi-bin .deb missing after download" >&2
  exit 1
}

EXTRACT="${WORKDIR}/extract"
mkdir -p "${EXTRACT}"
log "==> Extract ${INDI_BIN_DEB_PATH}"
dpkg-deb -x "${INDI_BIN_DEB_PATH}" "${EXTRACT}"

PW_BIN="$(find "${EXTRACT}" -name 'indi_planewave_telescope' -type f | head -1)"
if [[ -z "${PW_BIN}" ]]; then
  echo "ERROR: indi_planewave_telescope not in $(basename "${INDI_BIN_DEB_PATH}"). Planewave-related files:" >&2
  find "${EXTRACT}" -type f | grep -i planewave || find "${EXTRACT}" -path '*/usr/bin/*' -type f | head -30
  exit 1
fi

XML="$(find "${EXTRACT}" \( -path '*planewave*.xml' -o -name 'indi_planewave.xml' \) 2>/dev/null | head -1)"

log "==> Install to /usr/local/bin (keep Debian /usr/bin/indi-bin untouched)"
sudo install -m 755 "${PW_BIN}" /usr/local/bin/indi_planewave_telescope

if [[ -n "${XML}" ]]; then
  sudo install -d /usr/local/share/indi
  sudo install -m 644 "${XML}" /usr/local/share/indi/"$(basename "${XML}")"
  log "==> Installed XML $(basename "${XML}")"
fi

if ldd /usr/local/bin/indi_planewave_telescope 2>/dev/null | grep -q 'not found'; then
  LIBS_EXTRACT="${WORKDIR}/extract-libindi1"
  mkdir -p "${LIBS_EXTRACT}"
  download_libindi1_deb "${WORKDIR}"
  log "==> Extract ${LIBINDI1_DEB_PATH}"
  dpkg-deb -x "${LIBINDI1_DEB_PATH}" "${LIBS_EXTRACT}"
  install_indi2_libs_from_extract "${LIBS_EXTRACT}"
fi

echo "==> Verify"
BIN="$(command -v indi_planewave_telescope)"
if [[ -z "${BIN}" ]]; then
  echo "ERROR: indi_planewave_telescope not in PATH" >&2
  exit 1
fi
echo "  path: ${BIN}"
echo "  ldd:"
ldd "${BIN}" || true

if ldd "${BIN}" 2>/dev/null | grep -qE 'libindidriver\.so\.2|libindi'; then
  echo ""
  echo "NOTE: Uses INDI 2.x libs under /usr/local/lib; Debian indiserver 1.9.9 stays in /usr/bin."
  echo "  systemctl start pwi4.service   # or plug USB → telbot-select-mount"
  echo "  curl -s http://127.0.0.1:8220/status | grep mount.is_connected"
  echo "  indiserver -v indi_planewave_telescope"
  echo "  indi_getprop -d PlaneWave 'DEVICE_ADDRESS.ADDRESS'"
fi

if ldd "${BIN}" 2>/dev/null | grep -q 'not found'; then
  echo ""
  echo "ERROR: still missing libraries (see ldd above)."
  echo "  Do NOT apt install astroberry indi-bin/libindi1 (conflicts indi-sbig)."
  echo "  Retry with offline deb: INDI_LIBINDI1_DEB=~/libindi1_${ASTROBERRY_VER}_${ARCH}.deb"
  exit 1
fi

echo ""
echo "Done. PlaneWave USB (1cbe:0267) → sudo telbot-select-mount.sh (starts pwi4 + indi_planewave_telescope)"
echo "  telbot preflight"
echo "  deploy/pwi4.service must be installed: sudo cp deploy/pwi4.service /etc/systemd/system/"
