#!/usr/bin/env bash
# Download all USB_DEVICE_REGISTRY driver artifacts into deploy/indi-offline/<arch>/.
# Run on Pi (recommended, after drivers work): cd ~/Telbot && bash deploy/fetch-indi-offline-debs.sh
# Optional snapshot: sudo bash deploy/archive-indi-installed-to-offline.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${INDI_OFFLINE_ARCH:-$(dpkg --print-architecture 2>/dev/null || echo arm64)}"
case "${ARCH}" in
  aarch64) ARCH=arm64 ;;
  x86_64) ARCH=amd64 ;;
esac

ASTROBERRY_BIN_VER="${ASTROBERRY_INDI_BIN_VER:-2.2.1}"
ASTROBERRY_3P_VER="${ASTROBERRY_INDI_3P_VER:-2.2.0}"
INDI_3RDPARTY_REF="${INDI_3RDPARTY_REF:-v1.9.9}"
WITH_QHY_TARBALL="${INDI_OFFLINE_WITH_QHY_TARBALL:-1}"
WITH_DEBIAN_DEBS="${INDI_OFFLINE_WITH_DEBIAN:-1}"
RUN_ARCHIVE="${INDI_OFFLINE_ARCHIVE_AFTER_FETCH:-0}"

CACHE_DIR="${REPO_ROOT}/deploy/indi-offline/${ARCH}"
DEBIAN_DIR="${CACHE_DIR}/debian"
mkdir -p "${CACHE_DIR}" "${DEBIAN_DIR}"

log() { echo "$*" >&2; }

download_one() {
  local url="$1" dest="$2"
  if [[ -f "${dest}" ]]; then
    log "  skip (exists) $(basename "${dest}")"
    return 0
  fi
  log "  get $(basename "${dest}")"
  if command -v curl >/dev/null; then
    curl -fsSL -o "${dest}" "${url}"
  else
    wget -q -O "${dest}" "${url}"
  fi
}

download_debian_packages() {
  local dest="$1"
  local pkg
  local packages=(
    indi-bin indi-sbig libsbig4t64 indi-asi libindi-dev
    libindidriver1 libindiclient1 libindi-data libindilx200-1
  )
  log "==> Debian .deb → ${dest}/"
  mkdir -p "${dest}"
  (
    cd "${dest}"
    for pkg in "${packages[@]}"; do
      if apt-cache show "${pkg}" >/dev/null 2>&1; then
        apt-get download "${pkg}" 2>/dev/null || log "  WARN download ${pkg}"
      fi
    done
  )
  local n
  n="$(find "${dest}" -maxdepth 1 -name '*.deb' 2>/dev/null | wc -l | tr -d ' ')"
  log "     ${n} deb file(s) in debian/"
}

log "==> INDI offline cache (USB_DEVICE_REGISTRY): ${CACHE_DIR}"

if [[ "${WITH_DEBIAN_DEBS}" == "1" ]]; then
  download_debian_packages "${DEBIAN_DIR}"
fi

ASTROBERRY_DEBS=(
  "indi-bin_${ASTROBERRY_BIN_VER}_${ARCH}.deb|https://astroberry.io/debian/pool/main/libi/libindi/indi-bin_${ASTROBERRY_BIN_VER}_${ARCH}.deb"
  "libindi1_${ASTROBERRY_BIN_VER}_${ARCH}.deb|https://astroberry.io/debian/pool/main/libi/libindi/libindi1_${ASTROBERRY_BIN_VER}_${ARCH}.deb"
  "indi-3rdparty-drivers_${ASTROBERRY_3P_VER}_${ARCH}.deb|https://astroberry.io/debian/pool/main/i/indi-3rdparty-drivers/indi-3rdparty-drivers_${ASTROBERRY_3P_VER}_${ARCH}.deb"
  "indi-3rdparty-libs_${ASTROBERRY_3P_VER}_${ARCH}.deb|https://astroberry.io/debian/pool/main/i/indi-3rdparty-libs/indi-3rdparty-libs_${ASTROBERRY_3P_VER}_${ARCH}.deb"
)

log "==> astroberry .deb"
for entry in "${ASTROBERRY_DEBS[@]}"; do
  IFS='|' read -r name url <<<"${entry}"
  download_one "${url}" "${CACHE_DIR}/${name}"
done

if [[ "${WITH_QHY_TARBALL}" == "1" ]]; then
  qhy_name="indi-3rdparty-${INDI_3RDPARTY_REF}.tar.gz"
  qhy_url="https://github.com/indilib/indi-3rdparty/archive/refs/tags/${INDI_3RDPARTY_REF}.tar.gz"
  log "==> QHY source tarball"
  download_one "${qhy_url}" "${CACHE_DIR}/${qhy_name}"
fi

cp -f "${REPO_ROOT}/deploy/apt-telbot-indi.pref" "${CACHE_DIR}/apt-telbot-indi.pref"

MANIFEST="${CACHE_DIR}/MANIFEST.txt"
{
  echo "# Telbot INDI offline — USB_DEVICE_REGISTRY"
  echo "# generated $(date -Iseconds 2>/dev/null || date)"
  echo "# arch=${ARCH} debian=${WITH_DEBIAN_DEBS} astroberry_bin=${ASTROBERRY_BIN_VER} 3p=${ASTROBERRY_3P_VER} ref=${INDI_3RDPARTY_REF}"
  echo ""
  for dir in "${CACHE_DIR}" "${DEBIAN_DIR}"; do
    [[ -d "${dir}" ]] || continue
    while IFS= read -r -d '' f; do
      [[ -f "${f}" ]] || continue
      base="$(basename "${f}")"
      [[ "${base}" == "MANIFEST.txt" ]] && continue
      rel="${f#${CACHE_DIR}/}"
      sz="$(wc -c <"${f}" | tr -d ' ')"
      if command -v sha256sum >/dev/null; then
        sum="$(sha256sum "${f}" | awk '{print $1}')"
        printf '%s  %10s bytes  %s\n' "${sum}" "${sz}" "${rel}"
      else
        printf '%s bytes  %s\n' "${sz}" "${rel}"
      fi
    done < <(find "${dir}" -type f -print0 2>/dev/null)
  done
} >"${MANIFEST}"

log "==> Wrote ${MANIFEST}"

if [[ "${RUN_ARCHIVE}" == "1" ]]; then
  log "==> Archive installed binaries"
  sudo bash "${REPO_ROOT}/deploy/archive-indi-installed-to-offline.sh"
fi

log "==> Done."
log "    Restore: sudo bash deploy/restore-indi-usb-registry-drivers.sh"
log "    Docs:    deploy/indi-offline/README.md  docs/INDI_DRIVER_CALL_CHAIN.md"
