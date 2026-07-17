#!/usr/bin/env bash
# Install Telbot field INDI drivers on Debian trixie (arm64).
# Core from Debian; QHY CCD / Oasis focuser may need indi-3rdparty build (see docs).
#
# Usage: cd ~/Telbot && sudo bash deploy/install-indi-drivers-debian.sh
# See docs/INDI_APT_STACK.md

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREF_SRC="${REPO_ROOT}/deploy/apt-telbot-indi.pref"
PREF_DST="/etc/apt/preferences.d/telbot-indi-debian.pref"

# Must exist on Debian trixie arm64 (script fails if apt install fails).
APT_REQUIRED=(
  indi-bin
  indi-sbig
  libsbig4t64
  indi-asi
)

# Headers for deploy/build-indi-3rdparty-qhy-oasis.sh (same Debian 1.9.x stack as indi-bin).
APT_BUILD_DEPS=(
  libindi-dev
)

# Tried after required; missing packages are OK (documented build path).
APT_OPTIONAL=(
  indi-3rdparty-drivers
  indi-qhy
  indi-astroasis
  indi-celestron
)

# From indi-bin (Debian trixie): lx200gemini, celestron_gps, qhycfw3, indi_getprop, indiserver
BINARIES_REQUIRED=(
  indiserver
  indi_getprop
  indi_setprop
  indi_lx200gemini
  indi_sbig_ccd
  indi_asi_ccd
  indi_celestron_gps
  indi_qhycfw3_wheel
)

# Not in Debian trixie packages (were on astroberry 2.2 stack); optional post-build.
BINARIES_OPTIONAL=(
  indi_qhy_ccd
  indi_oasis_focuser
)

has_apt_candidate() {
  local pkg="$1"
  local cand
  cand="$(apt-cache policy "${pkg}" 2>/dev/null | awk '/^\s+Candidate:/ {print $2; exit}')"
  [[ -n "${cand}" && "${cand}" != "(none)" ]]
}

echo "==> APT pin: Debian INDI core over astroberry indi-bin/libindi1"
sudo cp "${PREF_SRC}" "${PREF_DST}"

for f in /etc/apt/sources.list.d/*astroberry* /etc/apt/sources.list.d/*Astroberry*; do
  if [[ -f "${f}" ]] && grep -qE '^[[:space:]]*deb ' "${f}" 2>/dev/null; then
    echo "==> Comment astroberry deb lines (avoid indi-bin 2.2): ${f}"
    sudo sed -i.bak-telbot-indi 's/^\([[:space:]]*deb[[:space:]].*astroberry.*\)/# \1/' "${f}" || true
  fi
done

if ! grep -rq 'non-free' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
  echo "WARN: apt sources may lack contrib/non-free (needed for indi-sbig / libsbig4t64)."
fi

sudo apt update

echo "==> Install required: ${APT_REQUIRED[*]}"
sudo apt install -y "${APT_REQUIRED[@]}"

echo "==> Install build headers for QHY/Oasis compile: ${APT_BUILD_DEPS[*]}"
sudo apt install -y "${APT_BUILD_DEPS[@]}"

echo "==> Install optional (skip if no candidate; never abort script)"
for pkg in "${APT_OPTIONAL[@]}"; do
  if has_apt_candidate "${pkg}"; then
    echo "    trying ${pkg} ..."
    if sudo apt install -y "${pkg}"; then
      echo "    OK ${pkg}"
    else
      echo "    WARN apt install ${pkg} failed (may conflict with Debian indi-bin — see docs)"
    fi
  else
    echo "    SKIP ${pkg} (no installation candidate on this system)"
  fi
done

echo "==> Verify binaries"
req_miss=0
for b in "${BINARIES_REQUIRED[@]}"; do
  if command -v "${b}" >/dev/null 2>&1; then
    echo "  OK   ${b}"
  else
    echo "  FAIL ${b}"
    req_miss=1
  fi
done
opt_miss=0
for b in "${BINARIES_OPTIONAL[@]}"; do
  if command -v "${b}" >/dev/null 2>&1; then
    echo "  OK   ${b} (optional)"
  else
    echo "  MISS ${b} (optional — run deploy/build-indi-3rdparty-qhy-oasis.sh; see docs/INDI_APT_STACK.md §7)"
    opt_miss=1
  fi
done

echo "==> apt policy"
apt-cache policy indi-bin indi-sbig indi-asi 2>/dev/null | sed 's/^/  /' || true

if [[ "${req_miss}" -ne 0 ]]; then
  echo "ERROR: required drivers missing. Ensure: sudo apt install -y indi-bin indi-sbig libsbig4t64 indi-asi"
  exit 1
fi

if [[ "${opt_miss}" -ne 0 ]]; then
  echo "NOTE: QHY CCD / Oasis focuser not in Debian trixie arm64 packages."
  echo "      They were previously from astroberry indi-qhy / indi-astroasis (removed with libindi 2.2)."
  echo "      Next: sudo bash ${REPO_ROOT}/deploy/build-indi-3rdparty-qhy-oasis.sh"
fi

if systemctl list-unit-files indi-telescope.service >/dev/null 2>&1; then
  echo "==> Restart indi-telescope.service"
  sudo systemctl restart indi-telescope.service || true
fi

echo "==> Install apt/dpkg guard (blocks removal of Debian INDI stack)"
sudo bash "${REPO_ROOT}/deploy/install-indi-apt-guard.sh"

echo "Done. Run: telbot preflight"
echo "      Before manual apt: telbot indi apt-guard check -- apt install <pkg>"
