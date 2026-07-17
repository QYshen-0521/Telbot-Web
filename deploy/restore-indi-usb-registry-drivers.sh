#!/usr/bin/env bash
# One-shot restore all INDI drivers listed in docs/USB_DEVICE_REGISTRY.md from deploy/indi-offline/.
#
# Usage: cd ~/Telbot && git pull && sudo bash deploy/restore-indi-usb-registry-drivers.sh
# Prerequisite: bash deploy/fetch-indi-offline-debs.sh (and optional archive on source Pi)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${INDI_OFFLINE_ARCH:-$(dpkg --print-architecture 2>/dev/null || echo arm64)}"
case "${ARCH}" in
  aarch64) ARCH=arm64 ;;
  x86_64) ARCH=amd64 ;;
esac

OFF="${TELBOT_INDI_OFFLINE_DIR:-${REPO_ROOT}/deploy/indi-offline/${ARCH}}"
DEBIAN_DIR="${OFF}/debian"
SNAPSHOT="${OFF}/installed-snapshot.tar.gz"
ASTROBERRY_BIN_VER="${ASTROBERRY_INDI_BIN_VER:-2.2.1}"
ASTROBERRY_3P_VER="${ASTROBERRY_INDI_3P_VER:-2.2.0}"
INDI_3RDPARTY_REF="${INDI_3RDPARTY_REF:-v1.9.9}"
SKIP_QHY_BUILD="${RESTORE_SKIP_QHY_BUILD:-0}"

log() { echo "$*" >&2; }

if [[ ! -d "${OFF}" ]]; then
  echo "ERROR: offline dir missing: ${OFF}" >&2
  echo "Run: bash deploy/fetch-indi-offline-debs.sh" >&2
  exit 1
fi

log "==> Restore USB_DEVICE_REGISTRY drivers from ${OFF}"

log "==> APT pin (Debian INDI over astroberry)"
sudo cp "${REPO_ROOT}/deploy/apt-telbot-indi.pref" /etc/apt/preferences.d/telbot-indi-debian.pref
for f in /etc/apt/sources.list.d/*astroberry* /etc/apt/sources.list.d/*Astroberry*; do
  if [[ -f "${f}" ]] && grep -qE '^[[:space:]]*deb ' "${f}" 2>/dev/null; then
    sudo sed -i.bak-telbot-indi 's/^\([[:space:]]*deb[[:space:]].*astroberry.*\)/# \1/' "${f}" || true
  fi
done

if compgen -G "${DEBIAN_DIR}"/*.deb >/dev/null 2>&1; then
  log "==> Install Debian packages from ${DEBIAN_DIR}/*.deb"
  sudo apt install -y "${DEBIAN_DIR}"/*.deb
else
  log "==> No debian/*.deb in cache — install via network"
  sudo bash "${REPO_ROOT}/deploy/install-indi-drivers-debian.sh"
fi

if [[ -f "${SNAPSHOT}" ]]; then
  log "==> Restore /usr/local from ${SNAPSHOT}"
  sudo tar -xzf "${SNAPSHOT}" -C /
  sudo ldconfig 2>/dev/null || true
else
  log "==> No installed-snapshot.tar.gz — install PlaneWave + Oasis from astroberry debs"
  if [[ -f "${OFF}/indi-bin_${ASTROBERRY_BIN_VER}_${ARCH}.deb" ]]; then
    sudo INDI_BIN_DEB="${OFF}/indi-bin_${ASTROBERRY_BIN_VER}_${ARCH}.deb" \
         INDI_LIBINDI1_DEB="${OFF}/libindi1_${ASTROBERRY_BIN_VER}_${ARCH}.deb" \
         bash "${REPO_ROOT}/deploy/install-indi-planewave-telescope.sh"
  else
    log "WARN: missing indi-bin_${ASTROBERRY_BIN_VER}_${ARCH}.deb — skip PlaneWave"
  fi
  if [[ -f "${OFF}/indi-3rdparty-drivers_${ASTROBERRY_3P_VER}_${ARCH}.deb" ]]; then
    sudo INDI_3RDPARTY_DRIVERS_DEB="${OFF}/indi-3rdparty-drivers_${ASTROBERRY_3P_VER}_${ARCH}.deb" \
         INDI_3RDPARTY_LIBS_DEB="${OFF}/indi-3rdparty-libs_${ASTROBERRY_3P_VER}_${ARCH}.deb" \
         bash "${REPO_ROOT}/deploy/install-indi-oasis-focuser.sh"
  else
    log "WARN: missing indi-3rdparty-drivers deb — skip Oasis"
  fi
fi

if [[ "${SKIP_QHY_BUILD}" != "1" ]] && ! command -v indi_qhy_ccd >/dev/null 2>&1; then
  tarball="${OFF}/indi-3rdparty-${INDI_3RDPARTY_REF}.tar.gz"
  if [[ -f "${tarball}" ]]; then
    log "==> Build indi_qhy_ccd from offline tarball"
    sudo INDI_3RDPARTY_TARBALL="${tarball}" \
         bash "${REPO_ROOT}/deploy/build-indi-3rdparty-qhy-oasis.sh"
  else
    log "WARN: no QHY tarball and indi_qhy_ccd missing — run fetch with INDI_OFFLINE_WITH_QHY_TARBALL=1"
  fi
fi

log "==> Verify"
bash "${REPO_ROOT}/deploy/check-usb-registry-drivers.sh"
log "==> Done. See docs/INDI_DRIVER_CALL_CHAIN.md"
