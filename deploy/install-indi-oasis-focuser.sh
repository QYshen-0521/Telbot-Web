#!/usr/bin/env bash
# Install indi_oasis_focuser without apt install indi-3rdparty-drivers (avoids removing Debian indi-bin/sbig).
# Extracts driver binary + XML from astroberry indi-3rdparty-drivers .deb (INDI 2.x build; may run with indiserver 1.9.9).
#
# Usage: cd ~/Telbot && sudo bash deploy/install-indi-oasis-focuser.sh
# Optional:
#   INDI_3RDPARTY_DRIVERS_DEB=/path/to/indi-3rdparty-drivers_*.deb
#   INDI_3RDPARTY_LIBS_DEB=/path/to/indi-3rdparty-libs_*.deb
#   INDI_ASTROASIS_DEB=...          # legacy alias for drivers .deb
# See docs/INDI_APT_STACK.md §7.1

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASTROBERRY_VER="${ASTROBERRY_INDI_VER:-2.2.0}"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "${ARCH}" in
  aarch64) ARCH=arm64 ;;
  x86_64) ARCH=amd64 ;;
esac

DRIVERS_DEB="${INDI_3RDPARTY_DRIVERS_DEB:-${INDI_ASTROASIS_DEB:-}}"
LIBS_DEB="${INDI_3RDPARTY_LIBS_DEB:-}"
WORKDIR=""
EXTRACT=""
LIBS_EXTRACT=""

cleanup() {
  [[ -n "${WORKDIR}" && -d "${WORKDIR}" ]] && rm -rf "${WORKDIR}"
}
trap cleanup EXIT

# Status to stderr only — never use command substitution on functions that log to stdout.
log() { echo "$*" >&2; }

DRIVERS_DEB_PATH=""
LIBS_DEB_PATH=""

pool_url() {
  local component="$1" pkg="$2"
  echo "https://astroberry.io/debian/pool/main/${component}/${pkg}/${pkg}_${ASTROBERRY_VER}_${ARCH}.deb"
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

apt_download_deb() {
  local pkg="$1"
  TELBOT_INDI_GUARD_DISABLED=1 apt-get download "${pkg}" >&2
}

download_drivers_deb() {
  local out_dir="$1" f url
  cd "${out_dir}"
  if [[ -n "${DRIVERS_DEB}" ]]; then
    [[ -f "${DRIVERS_DEB}" ]] || {
      echo "ERROR: drivers .deb not found: ${DRIVERS_DEB}" >&2
      exit 1
    }
    cp -f "${DRIVERS_DEB}" "${out_dir}/drivers.deb"
    DRIVERS_DEB_PATH="${out_dir}/drivers.deb"
    return 0
  fi

  log "==> Download indi-3rdparty-drivers .deb only (NOT apt install — avoids stack conflict)"
  if apt_download_deb indi-3rdparty-drivers; then
    f="$(echo indi-3rdparty-drivers_*.deb | head -1)"
    if [[ -f "${f}" ]]; then
      DRIVERS_DEB_PATH="${out_dir}/${f}"
      return 0
    fi
  fi

  # Legacy name (bookworm / old docs); trixie astroberry has no separate indi-astroasis.
  if apt_download_deb indi-astroasis 2>/dev/null; then
    f="$(echo indi-astroasis_*.deb | head -1)"
    if [[ -f "${f}" ]]; then
      log "NOTE: using legacy package indi-astroasis"
      DRIVERS_DEB_PATH="${out_dir}/${f}"
      return 0
    fi
  fi

  url="$(pool_url i indi-3rdparty-drivers)"
  curl_download_deb "${url}" "${out_dir}/indi-3rdparty-drivers.deb"
  DRIVERS_DEB_PATH="${out_dir}/indi-3rdparty-drivers.deb"
}

download_libs_deb() {
  local out_dir="$1" f url
  cd "${out_dir}"
  if [[ -n "${LIBS_DEB}" ]]; then
    [[ -f "${LIBS_DEB}" ]] || {
      echo "ERROR: libs .deb not found: ${LIBS_DEB}" >&2
      exit 1
    }
    cp -f "${LIBS_DEB}" "${out_dir}/libs.deb"
    LIBS_DEB_PATH="${out_dir}/libs.deb"
    return 0
  fi

  log "==> Download indi-3rdparty-libs .deb (shared libs only, not apt install)"
  if apt_download_deb indi-3rdparty-libs; then
    f="$(echo indi-3rdparty-libs_*.deb | head -1)"
    if [[ -f "${f}" ]]; then
      LIBS_DEB_PATH="${out_dir}/${f}"
      return 0
    fi
  fi

  url="$(pool_url i indi-3rdparty-libs)"
  curl_download_deb "${url}" "${out_dir}/indi-3rdparty-libs.deb"
  LIBS_DEB_PATH="${out_dir}/indi-3rdparty-libs.deb"
}

install_shared_libs_from_extract() {
  local root="$1"
  local count=0
  while IFS= read -r -d '' so; do
    sudo install -m 644 "${so}" /usr/local/lib/
    count=$((count + 1))
  done < <(find "${root}" \( -path '*/usr/lib/*' -o -path '*/usr/lib/aarch64-linux-gnu/*' -o -path '*/usr/lib/x86_64-linux-gnu/*' \) \
    \( -name 'liboasisfocuser.so*' -o -name 'libastroasis.so*' \) -print0 2>/dev/null)
  if [[ "${count}" -gt 0 ]]; then
    echo "==> Installed ${count} Oasis/Astroasis lib(s) under /usr/local/lib"
    sudo ldconfig 2>/dev/null || true
  fi
}

echo "==> Prerequisite: Debian indi-bin 1.9.9 (liboasisfocuser from pass1 build, libs .deb, or libastroasis package)"
if ! dpkg -s indi-bin >/dev/null 2>&1; then
  echo "ERROR: indi-bin not installed. Run deploy/install-indi-drivers-debian.sh first."
  exit 1
fi

NEED_LIBS=0
if ! ldconfig -p 2>/dev/null | grep -q liboasisfocuser; then
  if [[ -f /usr/lib/aarch64-linux-gnu/liboasisfocuser.so ]] \
    || [[ -f /usr/lib/x86_64-linux-gnu/liboasisfocuser.so ]] \
    || ls /usr/local/lib/liboasisfocuser.so* >/dev/null 2>&1; then
    echo "WARN: liboasisfocuser on disk but not in ldconfig — will run ldconfig after install"
    NEED_LIBS=1
  else
    echo "WARN: liboasisfocuser not found — will extract from indi-3rdparty-libs if possible"
    NEED_LIBS=1
  fi
fi

sudo apt install -y libhidapi-hidraw0 libhidapi-libusb0 2>/dev/null || true

WORKDIR="$(mktemp -d)"
download_drivers_deb "${WORKDIR}"
DEB_FILE="${DRIVERS_DEB_PATH}"
[[ -f "${DEB_FILE}" ]] || {
  echo "ERROR: drivers .deb missing after download" >&2
  exit 1
}

EXTRACT="${WORKDIR}/extract-drivers"
mkdir -p "${EXTRACT}"
log "==> Extract ${DEB_FILE}"
dpkg-deb -x "${DEB_FILE}" "${EXTRACT}"

FOCUSER_BIN="$(find "${EXTRACT}" -name 'indi_oasis_focuser' -type f | head -1)"
if [[ -z "${FOCUSER_BIN}" ]]; then
  echo "ERROR: indi_oasis_focuser not in ${DEB_FILE}. Sample contents:"
  find "${EXTRACT}" -type f | head -40
  exit 1
fi

XML="$(find "${EXTRACT}" \( -path '*/indi_astroasis.xml' -o -name 'indi_astroasis.xml' \) | head -1)"
UDEV="$(find "${EXTRACT}" -path '*astroasis*.rules' | head -1)"

if [[ "${NEED_LIBS}" -eq 1 ]]; then
  LIBS_EXTRACT="${WORKDIR}/extract-libs"
  mkdir -p "${LIBS_EXTRACT}"
  download_libs_deb "${WORKDIR}"
  LIBS_FILE="${LIBS_DEB_PATH}"
  [[ -f "${LIBS_FILE}" ]] || {
    echo "ERROR: libs .deb missing after download" >&2
    exit 1
  }
  log "==> Extract ${LIBS_FILE}"
  dpkg-deb -x "${LIBS_FILE}" "${LIBS_EXTRACT}"
  install_shared_libs_from_extract "${LIBS_EXTRACT}"
fi

echo "==> Install binary to /usr/local/bin (do not overwrite Debian indi-bin packages)"
sudo install -m 755 "${FOCUSER_BIN}" /usr/local/bin/indi_oasis_focuser

if [[ -n "${XML}" ]]; then
  sudo install -d /usr/local/share/indi
  sudo install -m 644 "${XML}" /usr/local/share/indi/indi_astroasis.xml
fi

if [[ -n "${UDEV}" ]]; then
  echo "==> udev: ${UDEV}"
  sudo install -m 644 "${UDEV}" /etc/udev/rules.d/99-astroasis-telbot.rules
  sudo udevadm control --reload-rules 2>/dev/null || true
  sudo udevadm trigger 2>/dev/null || true
fi

if [[ ! -f /etc/udev/rules.d/99-telbot-oasis-hidraw.rules ]]; then
  cat <<'UDEV' | sudo tee /etc/udev/rules.d/99-telbot-oasis-hidraw.rules >/dev/null
# Oasis focuser 338f:a0f0 — HID (telbot)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="338f", ATTRS{idProduct}=="a0f0", MODE="0660", GROUP="plugdev"
UDEV
  sudo udevadm control --reload-rules 2>/dev/null || true
  echo "==> Added /etc/udev/rules.d/99-telbot-oasis-hidraw.rules (user must be in group plugdev)"
fi

echo "==> Verify"
if ! command -v indi_oasis_focuser >/dev/null; then
  echo "ERROR: /usr/local/bin/indi_oasis_focuser missing"
  exit 1
fi
BIN="$(command -v indi_oasis_focuser)"
echo "  path: ${BIN}"
echo "  ldd:"
ldd "${BIN}" || true

if ldd "${BIN}" 2>/dev/null | grep -q 'libindi1'; then
  echo ""
  echo "NOTE: Binary links to libindi1 (astroberry INDI 2.x). It may still work with indiserver 1.9.9 — test:"
  echo "  indiserver -v indi_oasis_focuser"
  echo "  indi_getprop -d 'Oasis Focuser' 'CONNECTION.CONNECT'"
  echo "If it crashes, Oasis cannot coexist with Debian 1.9.9 stack without full INDI 2.x upgrade."
fi

if ldd "${BIN}" 2>/dev/null | grep -q 'not found'; then
  echo ""
  echo "WARN: missing shared libraries. Options:"
  echo "  - Do NOT run 'apt autoremove' if libastroasis is listed (may remove libs QHY pass1 needs)."
  echo "  - Re-run pass1: sudo bash deploy/build-indi-3rdparty-qhy-oasis.sh"
  echo "  - Or: sudo INDI_3RDPARTY_LIBS_DEB=/path/to/indi-3rdparty-libs_${ASTROBERRY_VER}_${ARCH}.deb \\"
  echo "         bash deploy/install-indi-oasis-focuser.sh"
fi

echo ""
echo "Done. Plug Oasis USB (338f:a0f0), ensure user in plugdev: sudo usermod -aG plugdev qyshen"
echo "  sudo telbot-select-mount.sh"
echo "  telbot preflight"
