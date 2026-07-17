#!/usr/bin/env bash
# Build indi_qhy_ccd (and optionally indi_oasis_focuser) from indi-3rdparty on Debian INDI 1.9.9.
# Prerequisite: deploy/install-indi-drivers-debian.sh (indi-bin + libindi-dev stack).
#
# Usage: cd ~/Telbot && sudo bash deploy/build-indi-3rdparty-qhy-oasis.sh
# Oasis on INDI 1.9.9: see docs/INDI_APT_STACK.md §7 (cannot compile v2.1.x astroasis driver here).
# See docs/INDI_APT_STACK.md §7

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${INDI_3RDPARTY_SRC:-/usr/local/src/indi-3rdparty}"
BUILD_DIR="${SRC_DIR}/build-telbot"
GIT_URL="${INDI_3RDPARTY_GIT:-https://github.com/indilib/indi-3rdparty.git}"
# Debian trixie ships INDI 1.9.9 — use matching indi-3rdparty tag for QHY (see qhy_ccd.h: no INDI::FITSRecord).
# v2.1.x drivers need INDI 2.x C++ Property API; master also needs hotplugcapabledevice.h (2.1.7+).
GIT_REF="${INDI_3RDPARTY_REF:-v1.9.9}"
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing command: $1"
    exit 1
  }
}

echo "==> Check Debian INDI runtime (must be 1.9.x from deb.debian.org, not astroberry 2.2)"
for pkg in indi-bin libindidriver1; do
  if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
    echo "ERROR: ${pkg} not installed. Run: sudo bash ${REPO_ROOT}/deploy/install-indi-drivers-debian.sh"
    exit 1
  fi
done
if command -v indi_sbig_ccd >/dev/null && ! dpkg -s indi-sbig >/dev/null 2>&1; then
  echo "WARN: indi_sbig_ccd exists but indi-sbig package not recorded — continue anyway"
fi

echo "==> Build dependencies (includes libindi-dev headers)"
sudo apt install -y \
  build-essential cmake git pkg-config \
  libindi-dev libnova-dev libcfitsio-dev libusb-1.0-0-dev \
  zlib1g-dev libgsl-dev libjpeg-dev libcurl4-gnutls-dev \
  libtiff-dev libfftw3-dev libhidapi-dev libhidapi-hidraw0 \
  nlohmann-json3-dev

if ! dpkg -s libindi-dev >/dev/null 2>&1; then
  echo "ERROR: libindi-dev still missing after apt install (check apt sources / pin)."
  exit 1
fi

require_cmd cmake
require_cmd git
require_cmd make

clone_indi_3rdparty_repo() {
  local attempt
  local max_attempts="${INDI_3RDPARTY_GIT_RETRIES:-5}"
  sudo mkdir -p "$(dirname "${SRC_DIR}")"
  sudo rm -rf "${SRC_DIR}"
  for attempt in $(seq 1 "${max_attempts}"); do
    echo "==> git clone attempt ${attempt}/${max_attempts}: ${GIT_URL} (ref ${GIT_REF})"
    if sudo git \
      -c http.lowSpeedLimit=1000 \
      -c http.lowSpeedTime=300 \
      clone --depth 1 --branch "${GIT_REF}" "${GIT_URL}" "${SRC_DIR}"; then
      sudo chown -R "$(id -u):$(id -g)" "${SRC_DIR}" 2>/dev/null || true
      return 0
    fi
    echo "WARN: clone failed (TLS/timeout on Pi→GitHub is common). Retry in 20s…"
    sudo rm -rf "${SRC_DIR}"
    sleep 20
  done
  return 1
}

install_indi_3rdparty_from_tarball() {
  local tarball="${1:?}"
  if [[ ! -f "${tarball}" ]]; then
    echo "ERROR: tarball not found: ${tarball}"
    return 1
  fi
  sudo mkdir -p "$(dirname "${SRC_DIR}")"
  sudo rm -rf "${SRC_DIR}"
  local tmp
  tmp="$(mktemp -d)"
  tar -xzf "${tarball}" -C "${tmp}"
  local extracted
  extracted="$(find "${tmp}" -maxdepth 1 -type d -name 'indi-3rdparty*' | head -1)"
  if [[ -z "${extracted}" ]]; then
    echo "ERROR: no indi-3rdparty-* directory inside ${tarball}"
    rm -rf "${tmp}"
    return 1
  fi
  sudo mv "${extracted}" "${SRC_DIR}"
  rm -rf "${tmp}"
  sudo chown -R "$(id -u):$(id -g)" "${SRC_DIR}" 2>/dev/null || true
  echo "==> Installed sources from tarball -> ${SRC_DIR}"
  return 0
}

sudo mkdir -p "$(dirname "${SRC_DIR}")"
if [[ -n "${INDI_3RDPARTY_TARBALL:-}" ]]; then
  install_indi_3rdparty_from_tarball "${INDI_3RDPARTY_TARBALL}"
elif [[ ! -d "${SRC_DIR}/.git" ]] && [[ ! -f "${SRC_DIR}/CMakeLists.txt" ]]; then
  if ! clone_indi_3rdparty_repo; then
    cat <<EOF
ERROR: 无法从 GitHub clone indi-3rdparty（GnuTLS recv error -110 多为网络/TLS 中断，不是 INDI 版本问题）。

请在 Pi 上重试：
  cd ~/Telbot && sudo bash deploy/build-indi-3rdparty-qhy-oasis.sh

或先测连通：
  curl -I --max-time 30 https://github.com

或在能访问 GitHub 的电脑上打包再 scp（标签须为 ${GIT_REF}）：
  curl -L -o indi-3rdparty-${GIT_REF}.tar.gz \\
    https://github.com/indilib/indi-3rdparty/archive/refs/tags/${GIT_REF}.tar.gz
  scp indi-3rdparty-${GIT_REF}.tar.gz telbot:~/
  ssh telbot 'cd ~/Telbot && sudo INDI_3RDPARTY_TARBALL=/home/qyshen/indi-3rdparty-${GIT_REF}.tar.gz bash deploy/build-indi-3rdparty-qhy-oasis.sh'
EOF
    exit 1
  fi
elif [[ ! -d "${SRC_DIR}/.git" ]]; then
  echo "==> Using existing source tree (no .git): ${SRC_DIR}"
else
  echo "==> Sync ${SRC_DIR} to ref ${GIT_REF} (not master — INDI 1.9.9 lacks hotplug headers)"
  git -C "${SRC_DIR}" fetch --depth 1 origin "refs/tags/${GIT_REF}:refs/tags/${GIT_REF}" 2>/dev/null \
    || git -C "${SRC_DIR}" fetch --depth 1 origin "${GIT_REF}" 2>/dev/null \
    || git -C "${SRC_DIR}" fetch --tags --depth 1 origin
  git -C "${SRC_DIR}" checkout -f "${GIT_REF}"
fi

# Only QHY + Astroasis; avoid building SBIG/ASI deb duplicates and other vendor deps.
CMAKE_ONLY_QHY_OASIS=(
  -DCMAKE_INSTALL_PREFIX=/usr
  -DCMAKE_BUILD_TYPE=Release
  -DWITH_QHY=ON
  -DWITH_ASTROASIS=OFF
  -DWITH_SBIG=OFF
  -DWITH_ASICAM=OFF
  -DWITH_EQMOD=OFF
  -DWITH_ASTARBOX=OFF
  -DWITH_STARBOOK=OFF
  -DWITH_STARBOOK_TEN=OFF
  -DWITH_CAUX=OFF
  -DWITH_SX=OFF
  -DWITH_MAXDOME=OFF
  -DWITH_NEXDOME=OFF
  -DWITH_SPECTRACYBER=OFF
  -DWITH_CLOUDWATCHER=OFF
  -DWITH_MI=OFF
  -DWITH_FLI=OFF
  -DWITH_INOVAPLX=OFF
  -DWITH_APOGEE=OFF
  -DWITH_FFMV=OFF
  -DWITH_GPHOTO=OFF
  -DWITH_QSI=OFF
  -DWITH_DUINO=OFF
  -DWITH_FISHCAMP=OFF
  -DWITH_GPSD=OFF
  -DWITH_GIGE=OFF
  -DWITH_DSI=OFF
  -DWITH_MGEN=OFF
  -DWITH_ASTROMECHFOC=OFF
  -DWITH_LIMESDR=OFF
  -DWITH_RADIOSIM=OFF
  -DWITH_GPSNMEA=OFF
  -DWITH_RTKLIB=OFF
  -DWITH_ARMADILLO=OFF
  -DWITH_NIGHTSCAPE=OFF
  -DWITH_ATIK=OFF
  -DWITH_ATIK_EFW=OFF
  -DWITH_TOUPCAM=OFF
  -DWITH_ALTAIRCAM=OFF
  -DWITH_BRESSERCAM=OFF
  -DWITH_MALLINCAM=OFF
  -DWITH_MEADECAM=OFF
  -DWITH_NNCAM=OFF
  -DWITH_OGMACAM=OFF
  -DWITH_OMEGONPROCAM=OFF
  -DWITH_STARSHOOTG=OFF
  -DWITH_TSCAM=OFF
  -DWITH_SVBONYCAM=OFF
  -DWITH_DREAMFOCUSER=OFF
  -DWITH_AVALON=OFF
  -DWITH_AVALONUD=OFF
  -DWITH_BEEFOCUS=OFF
  -DWITH_SHELYAK=OFF
  -DWITH_SKYWALKER=OFF
  -DWITH_TALON6=OFF
  -DWITH_PENTAX=OFF
  -DWITH_ASTROLINK4=OFF
  -DWITH_AHP_XC=OFF
  -DWITH_AHP_GT=OFF
  -DWITH_ORION_SSG3=OFF
  -DWITH_SVBONY=OFF
  -DWITH_BRESSEREXOS2=OFF
  -DWITH_PLAYERONE=OFF
  -DWITH_WEEWX_JSON=OFF
  -DWITH_ROLLOFFINO=OFF
  -DWITH_OCS=OFF
  -DWITH_GPIO=OFF
  "-DWITH_TICFOCUSER-NG=OFF"
  -DWITH_OPENOGMA=OFF
  -DWITH_LIBCAMERA=OFF
  -DWITH_BNO_IMU=OFF
  -DWITH_CELESTRON_ORIGIN=OFF
  -DWITH_WEBCAM=OFF
  -DWITH_NUT=OFF
)

run_cmake() {
  local extra=("$@")
  cmake -S "${SRC_DIR}" -B "${BUILD_DIR}" "${CMAKE_ONLY_QHY_OASIS[@]}" "${extra[@]}"
}

echo "==> indi-3rdparty tag ${GIT_REF} (matched to Debian libindi-dev 1.9.9 for indi_qhy_ccd)"
echo "==> CMake pass 1 (BUILD_LIBS: libqhy from source; v1.9.9 has no indi-astroasis)"
echo "    (ignores leftover astroberry libqhyccd in /usr/lib — pass 2 uses freshly installed libs)"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
run_cmake -DBUILD_LIBS=ON

echo "==> Build & install vendor libraries (libqhy)"
make -C "${BUILD_DIR}" -j"$(nproc)"
sudo make -C "${BUILD_DIR}" install
sudo ldconfig

echo "==> CMake pass 2 (indi-qhy driver; tag ${GIT_REF})"
# Pass 1 leaves BUILD_LIBS=ON in CMakeCache.txt; must clear or drivers are not generated.
run_cmake -DBUILD_LIBS=OFF

echo "==> Build indi_qhy_ccd"
make -C "${BUILD_DIR}" -j"$(nproc)" indi_qhy_ccd
sudo make -C "${BUILD_DIR}" install

echo "==> Verify QHY"
if ! command -v indi_qhy_ccd >/dev/null 2>&1; then
  echo "ERROR: indi_qhy_ccd missing after install"
  exit 1
fi
echo "  OK   indi_qhy_ccd -> $(command -v indi_qhy_ccd)"

if command -v indi_oasis_focuser >/dev/null 2>&1; then
  echo "  OK   indi_oasis_focuser -> $(command -v indi_oasis_focuser)"
else
  echo "  MISS indi_oasis_focuser — cannot build on Debian INDI 1.9.9 (driver needs INDI 2.x API); see docs/INDI_APT_STACK.md §7.1"
fi

if systemctl list-unit-files indi-telescope.service >/dev/null 2>&1; then
  echo "==> Restart indi-telescope.service"
  sudo systemctl restart indi-telescope.service || true
fi

echo "Done. Plug QHY / Oasis USB, then:"
echo "  sudo telbot-select-mount.sh"
echo "  telbot preflight"
echo "  indi_getprop -d 'QHY CCD*' 'CONNECTION.CONNECT'   # when QHY present"
echo "  indi_getprop -d 'Oasis Focuser' 'CONNECTION.CONNECT'"
