#!/usr/bin/env bash
# Snapshot Pi-installed INDI files (/usr/local + optional indi_qhy_ccd) into deploy/indi-offline/<arch>/.
# Run on Pi after drivers are working: cd ~/Telbot && sudo bash deploy/archive-indi-installed-to-offline.sh
#
# Produces installed-snapshot.tar.gz for restore-indi-usb-registry-drivers.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${INDI_OFFLINE_ARCH:-$(dpkg --print-architecture 2>/dev/null || echo arm64)}"
case "${ARCH}" in
  aarch64) ARCH=arm64 ;;
  x86_64) ARCH=amd64 ;;
esac

OFF="${REPO_ROOT}/deploy/indi-offline/${ARCH}"
STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

log() { echo "$*" >&2; }

mkdir -p "${OFF}"

add_if_exists() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    local dest="${STAGING}${path}"
    mkdir -p "$(dirname "${dest}")"
    cp -a "${path}" "${dest}"
    log "  + ${path}"
  fi
}

log "==> Collect /usr/local INDI 2.x (PlaneWave / Oasis)"
for f in /usr/local/bin/indi_planewave_telescope /usr/local/bin/indi_oasis_focuser; do
  add_if_exists "${f}"
done
for f in /usr/local/share/indi/indi_astroasis.xml; do
  add_if_exists "${f}"
done
if [[ -d /usr/local/lib ]]; then
  while IFS= read -r -d '' so; do
    case "$(basename "${so}")" in
      libindidriver.so*|libindidevice.so*|libindiclient.so*|libindiAlignmentDriver.so*)
        add_if_exists "${so}"
        ;;
    esac
  done < <(find /usr/local/lib -maxdepth 1 -name 'libindi*.so*' -print0 2>/dev/null)
fi

log "==> Collect QHY binary if present"
add_if_exists /usr/bin/indi_qhy_ccd

LIST="${OFF}/installed-paths.txt"
{
  echo "# captured $(date -Iseconds 2>/dev/null || date)"
  find "${STAGING}" -type f | sed "s|^${STAGING}||" | sort
} | sudo tee "${LIST}" >/dev/null
sudo chown "$(id -un):$(id -gn)" "${LIST}" 2>/dev/null || true

OUT="${OFF}/installed-snapshot.tar.gz"
tar -czf "${OUT}" -C "${STAGING}" .
log "==> Wrote ${OUT} ($(wc -c <"${OUT}" | tr -d ' ') bytes)"
log "==> Path list: ${LIST}"
