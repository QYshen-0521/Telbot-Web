#!/bin/sh
# Start PlaneWave PWI4 (--nogui) for L-series mounts; HTTP API on :8220.
# Install: sudo cp deploy/telbot-pwi4-wrap.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/telbot-pwi4-wrap.sh
# Env (also via /etc/default/telbot-mount): TELBOT_PWI4_HOME, TELBOT_PWI4_CONFIG_ROOT

set -e

if [ -r /etc/default/telbot-mount ]; then
  # shellcheck source=/dev/null
  . /etc/default/telbot-mount
fi

PWI4_HOME="${TELBOT_PWI4_HOME:-${HOME}/pwi-4.1.8final}"
CONFIG_ROOT="${TELBOT_PWI4_CONFIG_ROOT:-${HOME}/.planewave/PWI4}"

if [ ! -x "${PWI4_HOME}/run-pwi4" ]; then
  echo "telbot-pwi4: run-pwi4 not found under ${PWI4_HOME} (set TELBOT_PWI4_HOME)" >&2
  exit 1
fi

if [ ! -d "${CONFIG_ROOT}/Settings" ]; then
  echo "telbot-pwi4: missing ${CONFIG_ROOT}/Settings" >&2
  echo "telbot-pwi4: copy Windows Documents\\PlaneWave Instruments\\PWI4 to ~/.planewave/PWI4" >&2
  exit 1
fi

cd "${PWI4_HOME}"
exec ./run-pwi4 --nogui
