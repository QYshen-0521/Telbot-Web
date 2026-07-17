#!/bin/sh
# Select INDI mount profile from USB + mount_profiles.json; restart indi-telescope.service.
# Install: copy deploy/*.json *.py *.sh to e.g. /usr/local/lib/telbot-deploy/ and symlink this script to /usr/local/bin.
#
# Usage: telbot-select-mount.sh
# Env:
#   TELBOT_MOUNT_PROFILES, TELBOT_INDI_SYSTEMD_UNIT, TELBOT_SELECT_MOUNT_DRY_RUN=1
#   TELBOT_SELECT_MOUNT_TRY_LOCK=1  — flock -n (ExecStartPre; skip if main script holds lock)
#
# Restart runs *outside* flock so ExecStartPre does not deadlock (see docs/MOUNT_AUTO.md).

set -e
_SCRIPT="$(readlink -f "$0" 2>/dev/null || echo "$0")"
DIR="$(CDPATH= cd -- "$(dirname "$_SCRIPT")" && pwd)"
LOCK=/run/telbot/select-mount.lock
UNIT="${TELBOT_INDI_SYSTEMD_UNIT:-indi-telescope.service}"
INDI_PORT="${TELBOT_INDI_PORT:-7624}"
PWI4_UNIT="${TELBOT_PWI4_SYSTEMD_UNIT:-pwi4.service}"
PWI4_URL="${TELBOT_PWI4_HTTP_URL:-http://127.0.0.1:8220}"

_pwi4_required() {
  [ -f /run/telbot/pwi4_required ] && [ "$(cat /run/telbot/pwi4_required 2>/dev/null)" = "1" ]
}

_stop_pwi4() {
  if systemctl list-unit-files "${PWI4_UNIT}" >/dev/null 2>&1; then
    systemctl stop "$PWI4_UNIT" 2>/dev/null || true
  fi
}

_wait_for_pwi4_http_ready() {
  _max="${TELBOT_PWI4_READY_TIMEOUT_S:-60}"
  _i=0
  while [ "$_i" -lt "$_max" ]; do
    if curl -sf "${PWI4_URL}/status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    _i=$((_i + 1))
  done
  echo "telbot: PWI4 HTTP ${PWI4_URL} not ready after ${_max}s" >&2
  return 1
}

_pwi4_mount_is_connected() {
  _status="$(curl -sf "${PWI4_URL}/status" 2>/dev/null || true)"
  case "$_status" in
    *mount.is_connected=true*) return 0 ;;
    *"mount.is_connected":true*) return 0 ;;
    *mount.is_connected*True*) return 0 ;;
  esac
  return 1
}

_pwi4_mount_connect() {
  _code="$(curl -s -o /dev/null -w '%{http_code}' "${PWI4_URL}/mount/connect" 2>/dev/null || echo 000)"
  case "$_code" in
    200|204) return 0 ;;
    *)
      echo "telbot: PWI4 mount/connect HTTP ${_code} (url ${PWI4_URL}/mount/connect)" >&2
      return 1
      ;;
  esac
}

_pwi4_ensure_mount_connected() {
  # 须在 INDI PlaneWave CONNECT 之后调用（见 docs/MOUNT_AUTO.md PlaneWave 专节）
  _max="${TELBOT_PWI4_MOUNT_CONNECT_TIMEOUT_S:-45}"
  _i=0
  while [ "$_i" -lt "$_max" ]; do
    if _pwi4_mount_is_connected; then
      echo "telbot: PWI4 mount.is_connected=true" >&2
      return 0
    fi
    _pwi4_mount_connect || true
    sleep 2
    _i=$((_i + 2))
  done
  echo "Warning: PWI4 mount.is_connected still false after ${_max}s; check journalctl -u ${PWI4_UNIT}" >&2
  curl -sf "${PWI4_URL}/status" 2>/dev/null | grep -E 'mount\.is_connected|mount\.' >&2 || true
  return 1
}

_start_pwi4_if_needed() {
  if ! _pwi4_required; then
    _stop_pwi4
    return 0
  fi
  if ! systemctl list-unit-files "${PWI4_UNIT}" >/dev/null 2>&1; then
    echo "Warning: ${PWI4_UNIT} not installed (deploy/pwi4.service); PlaneWave needs PWI4" >&2
    return 1
  fi
  if ! systemctl start "$PWI4_UNIT"; then
    echo "systemctl start ${PWI4_UNIT} failed" >&2
    return 1
  fi
  if ! _wait_for_pwi4_http_ready; then
    return 1
  fi
  return 0
}

# 仅通过 systemd 跑 indiserver；清掉占用 7624 的手动 indiserver（避免日志刷到 SSH 终端、拔 USB 后驱动仍在）
_restart_indi_unit() {
  _u="$1"
  if ! systemctl list-unit-files "${_u}" >/dev/null 2>&1; then
    echo "Warning: systemd unit ${_u} not found; install deploy/indi-telescope.service" >&2
    return 1
  fi
  systemctl stop "$_u" 2>/dev/null || true
  sleep 0.5
  _free_indi_port
  sleep 0.3
  if ! systemctl start "$_u"; then
    echo "systemctl start ${_u} failed" >&2
    return 1
  fi
  indi_getprop -p "$INDI_PORT" -t 8 '*.*.*' >/dev/null 2>&1 || true
  return 0
}

_free_indi_port() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${INDI_PORT}/tcp" 2>/dev/null || true
  else
    pkill -x indiserver 2>/dev/null || true
  fi
}

# 杀掉非 indi-telescope.service 管理的 indiserver（SSH 里 indiserver -v … & 会导致拔 USB 后驱动仍在）
_enforce_indiserver_sync() {
  _want=""
  if [ -f /run/telbot/indiserver.args ]; then
    IFS= read -r _want < /run/telbot/indiserver.args || _want=""
  fi
  _main="0"
  if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
    _main=$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null || echo 0)
  fi
  _orphan=0
  for _pid in $(pgrep -x indiserver 2>/dev/null); do
    if [ "$_pid" != "$_main" ] || [ "$_main" = "0" ]; then
      echo "telbot: 停止非 systemd 的 indiserver pid $_pid（请用 systemctl，勿在终端 indiserver &）" >&2
      kill "$_pid" 2>/dev/null || true
      _orphan=1
    fi
  done
  _running=$(pgrep -a -x indiserver 2>/dev/null | head -1)
  if [ -n "$_want" ] && [ -n "$_running" ]; then
    case "$_running" in
      *"$_want"*) ;;
      *)
        echo "telbot: 运行中的 indiserver 与 /run/telbot/indiserver.args 不一致，将重启 $UNIT" >&2
        _orphan=1
        ;;
    esac
  fi
  if [ "$_orphan" -eq 1 ]; then
    _free_indi_port
    sleep 0.3
    if systemctl list-unit-files "${UNIT}" >/dev/null 2>&1; then
      systemctl start "$UNIT" 2>/dev/null || systemctl restart "$UNIT" 2>/dev/null || true
    fi
  fi
}

if [ -r /etc/default/telbot-mount ]; then
  # shellcheck source=/dev/null
  . /etc/default/telbot-mount
fi
PYTHON="${TELBOT_PYTHON:-python3}"

mkdir -p /run/telbot
export TELBOT_MOUNT_PROFILES="${TELBOT_MOUNT_PROFILES:-$DIR/mount_profiles.json}"

if [ "${TELBOT_SELECT_MOUNT_TRY_LOCK:-}" = "1" ]; then
  flock -n "$LOCK" -c "
    export TELBOT_SELECT_MOUNT_NO_RESTART=1
    exec \"$PYTHON\" \"$DIR/telbot_select_mount.py\"
  " || true
  exit 0
fi

rc=0
did_restart=0
flock "$LOCK" -c "
  export TELBOT_SELECT_MOUNT_NO_RESTART=1
  export TELBOT_SELECT_MOUNT_DEFER_RESTART=1
  \"$PYTHON\" \"$DIR/telbot_select_mount.py\"
" || rc=$?

if [ "$rc" -eq 2 ]; then
  did_restart=1
  if ! _start_pwi4_if_needed; then
    exit 1
  fi
  if ! _restart_indi_unit "$UNIT"; then
    exit 1
  fi
  echo "Applied profile and restarted $UNIT (logs: journalctl -u $UNIT -f)" >&2
  rc=0
elif ! _pwi4_required; then
  _stop_pwi4
fi

# 含「args 未变、跳过 restart」时也执行 CONNECT（计划写在 /run/telbot/auto_connect.json）
if [ -f /run/telbot/auto_connect.json ]; then
  if [ "$did_restart" = "0" ]; then
    export TELBOT_SELECT_MOUNT_AUTO_CONNECT_QUICK=1
  fi
  if ! "$PYTHON" "$DIR/telbot_select_mount.py" --post-restart-auto-connect; then
    echo "telbot: INDI auto-connect failed (see messages above)" >&2
  fi
fi

# PlaneWave：INDI CONNECT 后再连 PWI4 镜架（mount.is_connected）
if _pwi4_required; then
  if ! _pwi4_ensure_mount_connected; then
    echo "telbot: PWI4 mount not connected; INDI may show CONNECT=On but mount will not slew" >&2
  fi
fi

if [ "${TELBOT_SELECT_MOUNT_TRY_LOCK:-}" != "1" ]; then
  _enforce_indiserver_sync
fi

exit "$rc"
