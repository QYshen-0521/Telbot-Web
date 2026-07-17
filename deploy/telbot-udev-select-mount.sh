#!/bin/sh
# udev / systemd-run 调用：设置 TELBOT_ENV_FILE 后执行选镜（见 /etc/default/telbot-mount）。
# 勿直接当用户登录脚本用；正常选镜仍用 telbot-select-mount.sh

set -e
if [ -r /etc/default/telbot-mount ]; then
  # shellcheck source=/dev/null
  . /etc/default/telbot-mount
else
  logger -p user.warning -t telbot-udev "缺少 /etc/default/telbot-mount：请设置 TELBOT_ENV_FILE"
fi
export TELBOT_ENV_FILE
export TELBOT_UDEV_TRIGGER=1

# udev 会传入 ACTION=add|remove；拔线后多等一会再 lsusb，避免仍看到已拔设备
_udev_action="${ACTION:-add}"
if [ "$_udev_action" = "remove" ] && [ -n "${ID_VENDOR_ID:-}" ] && [ -n "${ID_MODEL_ID:-}" ]; then
  # 供 telbot_select_mount.py 从 lsusb 快照中剔除刚拔掉的 VID:PID（否则选镜以为相机仍在）
  TELBOT_UDEV_REMOVED_VIDPID="$(printf '%s:%s' "$ID_VENDOR_ID" "$ID_MODEL_ID" | tr '[:upper:]' '[:lower:]')"
  export TELBOT_UDEV_REMOVED_VIDPID
fi
if [ "$_udev_action" = "remove" ]; then
  _settle="${TELBOT_UDEV_REMOVE_SETTLE_SECONDS:-5}"
else
  _settle="${TELBOT_UDEV_SETTLE_SECONDS:-3}"
fi
if [ -n "$_settle" ] && [ "$_settle" != "0" ]; then
  sleep "$_settle"
fi

_select_mount="/usr/local/lib/telbot-deploy/telbot-select-mount.sh"
if [ ! -x "$_select_mount" ]; then
  _select_mount="/usr/local/bin/telbot-select-mount.sh"
fi
if [ ! -x "$_select_mount" ]; then
  logger -p user.err -t telbot-udev "未找到 telbot-select-mount.sh（请安装到 /usr/local/lib/telbot-deploy/ 或 /usr/local/bin/）"
  exit 1
fi
logger -p user.info -t telbot-udev "触发选镜 action=${_udev_action}: $_select_mount (settle=${_settle}s)"
exec "$_select_mount"
