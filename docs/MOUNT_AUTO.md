# 多品牌望远镜：USB → INDI 驱动 + Telbot 自动设备名

## 概要

1. **`deploy/mount_profiles.json`**：按 USB `VID:PID` 或 `/dev/serial/by-id` 子串匹配赤道仪，选择 `indi_*` 驱动列表。  
2. **`telbot-select-mount.sh`** / **`telbot_select_mount.py`**：写入 `/run/telbot/indiserver.args` 与 **`/run/telbot/indi_device_hint`**，必要时 **`systemctl restart indi-telescope.service`**。  
3. **`indi-telescope.service`**：`ExecStartPre` 在**无 restart** 模式下刷新 args（`TELBOT_SELECT_MOUNT_NO_RESTART=1`），`ExecStart` 用 **`telbot-indiserver-wrap.sh`** 启动 `indiserver`。  
4. **Telbot**：`TELBOT_INDI_DEVICE_AUTO=true` 时由 **`resolve_telescope_device`** 结合 hint、`indi_getprop` 与 USB 串口匹配望远镜设备名。  
   **从家目录运行 `telbot` 时**：会合并 **`~/.env`** 与 **`~/Telbot/.env`**（后者覆盖同名 `TELBOT_*`；已 `export` 的变量优先），避免 `~/.env` 仍为 Losmandy 而选镜 hint 已是 Celestron 的不一致。

## 安装（树莓派示例）

```bash
sudo mkdir -p /usr/local/lib/telbot-deploy
sudo cp deploy/mount_profiles.json deploy/telbot_select_mount.py \
  deploy/indi_auto_connect_lite.py deploy/env_sync.py deploy/telbot-select-mount.sh \
  deploy/telbot-indiserver-wrap.sh deploy/telbot-pwi4-wrap.sh \
  deploy/pwi4.service /usr/local/lib/telbot-deploy/
sudo chmod +x /usr/local/lib/telbot-deploy/*.sh
sudo ln -sf /usr/local/lib/telbot-deploy/telbot-select-mount.sh /usr/local/bin/telbot-select-mount.sh
sudo ln -sf /usr/local/lib/telbot-deploy/telbot-indiserver-wrap.sh /usr/local/bin/telbot-indiserver-wrap.sh
sudo cp deploy/indi-telescope.service /etc/systemd/system/
# 编辑 User= / Group=；若沿用旧单元：sudo systemctl disable --now indi-gemini.service
sudo systemctl daemon-reload
sudo systemctl enable --now indi-telescope.service
```

### 换镜自动选镜（udev，推荐）

插拔 **ttyACM***（常见 Meade/Gemini）或 **ttyUSB***（常见 Celestron Prolific）时触发选镜；**拔掉**对应串口时也会触发（刷新 `optional_indi_if` 等，例如 SBIG 已拔但赤道仪仍在时去掉 `indi_sbig_ccd`）。# SBIG 等可能无 tty 节点。插 USB：ATTR。拔线：usb_device 的 remove 上往往已无 `ID_VENDOR_ID`，仍有 **`PRODUCT`**（uevent，如 **`d97/101/1`** 对应 **`0d97:0101`**；vendor 在 `PRODUCT` 里常无高位前导 `0`）。规则用 **`ENV{PRODUCT}=="d97/*"`** 匹配该厂商任意产品号。

说明：**「停掉 simulator」**在实现上是 **`systemctl restart indi-telescope`** 并用新 **`indiserver.args`** 起真实驱动，**不是**关掉整个 `indi-telescope` 单元（否则 7624 与 Ekos 习惯会断）。

新增 **仅 USB、无串口节点** 的硬件时：若拔插不会触发 tty 规则，请在 **`deploy/99-telbot-mount.rules`** 增加对应的 **`ACTION=="add|remove", SUBSYSTEM=="usb", ATTR{idVendor}=="xxxx"`**（必要时加 **`ATTR{idProduct}`**），与 `mount_profiles.json` 中的 VID:PID 一致，复制到 `/etc/udev/rules.d/` 后 **`udevadm control --reload-rules`**。

```bash
sudo cp deploy/telbot-udev-select-mount.sh /usr/local/lib/telbot-deploy/
sudo chmod +x /usr/local/lib/telbot-deploy/telbot-udev-select-mount.sh
sudo cp deploy/telbot-mount.default /etc/default/telbot-mount
# 必改：与日常 telbot 使用的 .env 一致（udev 以 root 运行，否则可能写到 /root）
sudo sed -i 's|/home/pi/Telbot/.env|/home/你的用户名/Telbot/.env|' /etc/default/telbot-mount
sudo cp deploy/99-telbot-mount.rules /etc/udev/rules.d/99-telbot-mount.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

说明：

- 规则里用 **`systemd-run --collect --no-block`** 启动选镜，避免 udev 因 **`systemctl restart`** 耗时而终止任务。
- **`/etc/default/telbot-mount`** 中的 **`TELBOT_ENV_FILE`** 用于让 **`telbot_select_mount.py`** 在 root 下仍更新你的 **`~/Telbot/.env`**。
- **`TELBOT_ENV_OWNER`**（可选）：root 选镜写 `.env` 后 **`chown`** 回该用户；未设置时从 **`/home/<用户名>/...`** 路径推断。
- **不要用 root 编辑 `~/Telbot/.env`**（`sudo vi /home/…/.env`），否则文件可能变为 root 所有，日常 `telbot` 读配置会 **Permission denied**。
- **`flock`** 仍在 `telbot-select-mount.sh` 内，快速连续插拔会合并成串行一次。
- **插拔并 restart 后自动 CONNECTION.CONNECT**：`mount_profiles.json` 顶层 **`auto_connect_by_driver`** 将每个 **`indi_*` 驱动** 映射到 INDI 设备名（赤道仪用 profile 的 **`device_name_hint`**，CCD/电调/滤镜轮用固定名）。计划写入 **`/run/telbot/auto_connect.json`**，由 **`telbot_select_mount.py --post-restart-auto-connect`** 在 flock 外执行（等价于各设备的 `telbot mount/camera/focuser/filter connect --execute`）。关闭：**`TELBOT_SELECT_MOUNT_AUTO_CONNECT=0`**。新增驱动时在 **`auto_connect_by_driver`** 增加一行即可。
- **`.env` 同步**：除赤道仪 **`TELBOT_INDI_DEVICE`** 外，若当前 `indiserver` 参数行含 **`indi_asi_ccd`** / **`indi_qhy_ccd`** / **`indi_sbig_ccd`** 等，会按 **`auto_connect_by_driver[].env`** 更新 **`TELBOT_INDI_CCD_DEVICE`**（及电调、滤镜轮对应键）。仅插 ZWO / QHY 相机时 profile **`zwo_asi294mc_usb_only`** / **`qhy174m_usb_only`** 通过 **`telbot_env_keys`** 写入对应设备名（`telbot_env_sync=false`，不写赤道仪键）。

验证（**ZWO / SBIG 等无 tty 设备**须看到 `usb` + `usb_device` 事件，不是只有 `hidraw` / `usb_interface`）：

```bash
# 终端 1
sudo udevadm monitor --udev -s usb

# 终端 2：插拔 ZWO 后
journalctl -t telbot-udev -n 20 --no-pager
pgrep -a indiserver
cat /run/telbot/indiserver.args
```

应出现 **`telbot-udev: 触发选镜`** 日志；`indiserver.args` 在仅插 ZWO 时为 `-v indi_asi_ccd`，仅插 QHY174（**`lsusb` 见 `1618:c175`**）时为 `-v indi_qhy_ccd`，拔掉且无其它天文 USB 时为 `-v indi_simulator_telescope`（或仍带赤道仪 optional 驱动）。

**插拔不触发、但手动 `telbot-select-mount.sh` 正常**时常见原因：

1. **Pi 上仍是旧版 `99-telbot-mount.rules`**（`add` 未加 `ENV{DEVTYPE}=="usb_device"`，匹配不到 ZWO 的 `usb_device` 节点）。
2. **未安装或未更新 `telbot-udev-select-mount.sh`**（曾硬编码 `/usr/local/bin/telbot-select-mount.sh`，未做 symlink 时 udev 静默失败）。
3. **`/etc/default/telbot-mount` 未配置**（`.env` 不同步，但选镜仍应执行；可看 `journalctl -t telbot-udev`）。
4. **枚举过慢**：增大 `TELBOT_UDEV_SETTLE_SECONDS`（默认 3）；**拔线不卸驱动**时增大 **`TELBOT_UDEV_REMOVE_SETTLE_SECONDS`**（默认 5）。
5. **终端里刷 `Client N: new arrival`**：说明 **`indiserver` 在 SSH 里手动运行**（`pgrep` 显示 `[手动/孤儿]`）。执行 **`telbot indi stop`**，再 **`sudo systemctl enable --now indi-telescope.service`**；勿再 `indiserver -v … &`。
6. **拔 QHY 后 `indi_qhy_ccd` 仍在**：多为 (a) 仍是手动 indiserver，或 (b) 拔线后 **`lsusb` 仍短暂列出 `1618:c175`**。已用 **`TELBOT_UDEV_REMOVED_VIDPID`** 在选镜时剔除刚拔设备；确认 **`journalctl -t telbot-udev`** 有 `action=remove`；**`telbot indi status`** → **`telbot indi stop`** → **`sudo telbot-select-mount.sh`**。

模拟 udev 触发（不插拔）：

```bash
sudo systemd-run --collect /usr/local/lib/telbot-deploy/telbot-udev-select-mount.sh
```

## 调试

- 干跑（不写文件、不 restart）：`TELBOT_SELECT_MOUNT_DRY_RUN=1 telbot-select-mount.sh`  
- 干跑且不写 `.env`：`TELBOT_SELECT_MOUNT_WRITE_ENV=0` 或 `telbot_select_mount.py --no-write-env`  
- 核对 USB：`lsusb`、`ls -l /dev/serial/by-id/`  
- 改 manifest 后：`sudo telbot-select-mount.sh`（成功后会原子更新 `.env` 中 `TELBOT_INDI_DEVICE` 与 `TELBOT_INDI_DEVICE_AUTO=true`；root 写盘后 **`chown`** 回 `TELBOT_ENV_OWNER`）  
- Telbot：`telbot mount discover`（profile、hint、解析结果、`.env` 是否一致）；手工对齐 `.env`：`telbot mount sync-env`
- **`.env` 权限异常**（`Permission denied`）：`ls -l ~/Telbot/.env` 应为你的用户所有；若 owner 为 root：`sudo chown $USER:$USER ~/Telbot/.env && chmod 600 ~/Telbot/.env`

**死锁说明**：`telbot-select-mount.sh` 在 **flock 外** 执行 `systemctl restart`；`indi-telescope.service` 的 **ExecStartPre** 使用 **`TELBOT_SELECT_MOUNT_TRY_LOCK=1`**（`flock -n`），若主脚本正持锁则跳过，避免与 restart 互相等待。

### Celestron Evolution（Prolific 串口线）

现场常见 **VID:PID `067b:2303`**（Prolific PL2303），manifest 中 **`celestron_prolific_usb`** profile 会起 **`indi_celestron_gps`**，设备名 **`Celestron GPS`**。换镜后执行 `telbot-select-mount.sh` 即可，**无需手改 `.env`**（除非设置 `TELBOT_SELECT_MOUNT_WRITE_ENV=0`）。

## 新增品牌 / 滤镜轮等非赤道仪

**先查/更新现场 USB 登记表**：[`docs/USB_DEVICE_REGISTRY.md`](USB_DEVICE_REGISTRY.md)（VID:PID ↔ INDI 驱动；新设备先加表再改 manifest）。

1. 用 `lsusb` 记录 **VID:PID**，或 stable **`/dev/serial/by-id`** 子串。  
2. 在 `mount_profiles.json` 增加 `profiles[]`：`priority`、`match`、`indi_drivers`、`device_name_hint`（与 `indi_getprop` 中设备名一致）。  
3. **仅滤镜轮、不占赤道仪 `.env` 时**：设 **`"telbot_env_sync": false`**，避免把 `TELBOT_INDI_DEVICE` 写成滤镜轮名。  
4. **完整 `indiserver` 参数行**（如 **`-p 7624 -v indi_qhycfw3_wheel`**）：用 **`indiserver_args_line`** 字符串；若省略则仍按 `-v` + `indi_drivers` 拼接。  
5. **USB 与 by-id 同时满足才匹配**（减少误触）：在 profile 顶层设 **`"match_mode": "all"`**，并在 `match` 里同时写 **`usb_vid_pid`** 与 **`by_id_substring`**。默认 **`any`**（任一命中即可）。  
6. `sudo apt install` 对应 INDI 包（见各 profile 的 `packages_suggest`）。**多驱动须共存**：在 Debian trixie 上请用 [`INDI_APT_STACK.md`](INDI_APT_STACK.md) 与 `deploy/install-indi-drivers-debian.sh`，新增设备前先确认 apt 不会卸掉已有 `indi-bin`/`indi-sbig` 等。  
7. 执行 `telbot-select-mount.sh` 或插拔 USB 触发 udev。

### QHY CFW3 滤镜轮（`indi_qhycfw3_wheel`）

现场常见 **Silicon Labs CP2102 转串口**：`lsusb` 为 **`10c4:ea60`**，`/dev/serial/by-id/` 多为 **`usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_*`**。profile **`qhy_cfw3_wheel_usb`** 已按 **`usb_vid_pid` + `by_id_substring`**（`match_mode` 为 **`any`**，任一命中即可）配置；`indiserver_args_line` 为 **`-p 7624 -v indi_qhycfw3_wheel`**，`telbot_env_sync: false`。  
若 Pi 上还有 **其它 CP2102（同为 `10c4:ea60`）**，请把该 profile 改为 **`"match_mode": "all"`**，并把 **`by_id_substring`** 收窄到 **你滤镜轮那条 symlink 里独有的片段**（例如序列号段）。

## 与 Ekos 的关系

换镜会 **重启 indiserver**，Ekos 需 **重新连接**。Telbot 与 Ekos 不要同时对同一 mount 发冲突指令。

## 环境变量

| 变量 | 说明 |
|------|------|
| `TELBOT_MOUNT_PROFILES` | manifest 路径（默认脚本同目录 `mount_profiles.json`） |
| `TELBOT_INDI_SYSTEMD_UNIT` | restart 的单元名（默认 `indi-telescope.service`） |
| `TELBOT_SELECT_MOUNT_NO_RESTART` | `1`：只写 `/run/telbot/*`，不 `systemctl restart`（供 systemd `ExecStartPre`） |
| `TELBOT_SELECT_MOUNT_DRY_RUN` | `1`：仅打印 |
| `TELBOT_SELECT_MOUNT_TRY_LOCK` | `1`：`flock -n`（供 `indi-telescope.service` ExecStartPre） |
| `TELBOT_SELECT_MOUNT_DEFER_RESTART` | `1`：与 `NO_RESTART` 同用；写文件后退出码 `2`，由 shell 在 flock 外 restart |
| `TELBOT_SELECT_MOUNT_WRITE_ENV` | `0`：选镜成功后不写 `.env`（默认写） |
| `TELBOT_ENV_FILE` | 选镜 / `telbot mount sync-env` 写入的 `.env` 路径（默认见 `telbot.env_sync`） |
| `TELBOT_ENV_OWNER` | root 写 `.env` 后 `chown` 的目标用户名（默认从 `/home/<用户>/…` 推断） |
| `TELBOT_PWI4_HOME` | PWI4 安装目录（默认 `~/pwi-4.1.8final`；见 `telbot-pwi4-wrap.sh`） |
| `TELBOT_PWI4_CONFIG_ROOT` | PWI4 配置根（默认 `~/.planewave/PWI4`） |
| `TELBOT_PWI4_SYSTEMD_UNIT` | PlaneWave 专用单元（默认 `pwi4.service`） |
| `TELBOT_PWI4_READY_TIMEOUT_S` | 选镜等待 PWI4 HTTP 就绪秒数（默认 60） |
| `TELBOT_PWI4_MOUNT_CONNECT_TIMEOUT_S` | INDI CONNECT 后等待 PWI4 `mount.is_connected=true` 秒数（默认 45） |

### `mount_profiles.json` 扩展字段（可选）

| 字段 | 说明 |
|------|------|
| `match_mode` | `any`（默认）或 `all`：`all` 时 `match` 里出现的 **usb_vid_pid** 与 **by_id_substring** 须各自命中（用于收紧匹配）。 |
| `indiserver_args_line` | 若设置：整行写入 `/run/telbot/indiserver.args`（如 `-p 7624 -v indi_qhycfw3_wheel`），不再用 `-v` + `indi_drivers` 拼接。 |
| `optional_indi_if` | 可选：``[{ "match": { "usb_vid_pid"|"by_id_substring" }, "match_mode"?: "any"|"all", "indi_drivers": ["…"] }]``；**仅当**对应 USB 命中时才追加驱动（如 SBIG）。若省略则回退旧字段 ``optional_indi_drivers``（始终追加）。 |
| `telbot_env_sync` | 为 **`false`** 时：选镜成功后 **不** 更新 `.env` 中的 `TELBOT_INDI_DEVICE` 等（滤镜轮专用，避免覆盖赤道仪配置）。 |
| `requires_pwi4` | 为 **`true`** 时：选镜 restart 前 **`systemctl start pwi4.service`**，等待 HTTP **`:8220`**；无匹配 / 换非 PlaneWave profile 时 **`stop pwi4`**。 |
| `auto_connect_by_driver` | **`indi_*` 可执行名 → `{ "device": "…" }` 或 `{ "device_from": "profile_hint" }` 或 `{ "skip": true }`**；可选 **`pre_connect_setprop`**（CONNECT 前 `indi_setprop`，如 PlaneWave 地址）。选镜 restart 后自动 **`CONNECTION.CONNECT=On`**（见上文）。 |
| `on_no_usb_match` | **无任一 profile 匹配当前 USB/by-id 时**（例如天文设备全拔、只剩 USB hub）：默认 **`action`: `restart`**，并写入 **`indiserver_args_line`**（随仓库默认为 **`-v indi_simulator_telescope`**），再按 `telbot-select-mount.sh` 规则 **defer `systemctl restart`**，避免旧进程仍带已拔设备的驱动（如 `indi_sbig_ccd`）。**`action`: `exit_error`** 可恢复旧行为（直接失败、不写 args）。**`action`: `stop`** 会 **`systemctl stop`** 目标单元；在 **`indi-telescope.service` 的 ExecStartPre**（`TRY_LOCK`）下会自动改按 **`restart`** 回退，以免启动阶段停掉自己。需 **`indi-bin`** 等包提供回退驱动。 |

### SBIG 相机（`0d97:0101`）

- 与赤道仪同场时：在 **Losmandy / Celestron** profile 里用 **`optional_indi_if`**，仅当 **`lsusb` 出现 `0d97:0101`** 时才在 `indiserver` 里追加 **`indi_sbig_ccd`**。  
- **仅插 SBIG**（无赤道仪）：profile **`sbig_ccd_usb_only`**（priority 75）会起 **`-v indi_sbig_ccd`**；与赤道仪同时插入时 **赤道仪 profile 优先级更高**，仍由赤道仪 profile 负责带不带 SBIG。

### Astroasis Oasis 电调（`338f:a0f0`）

- 与赤道仪同场时：**Losmandy / Celestron** profile 的 **`optional_indi_if`** 在 **`lsusb` 出现 `338f:a0f0`** 时追加 **`indi_oasis_focuser`**（与 SBIG 可同时追加）。  
- **仅插电调**（无赤道仪）：profile **`oasis_focuser_usb_only`**（priority 77）起 **`-v indi_oasis_focuser`**。  
- **udev**：`99-telbot-mount.rules` 对 **`usb` add**（`ATTR`）与 **remove**（`ENV{PRODUCT}==338f/a0f0/*`）触发选镜；需已安装 **indi-3rdparty** 中的 **`indi_oasis_focuser`**，并配置 **hidraw** 权限。

### ZWO ASI294MC Pro（`03c3:294f`）

- 与赤道仪同场时：**Losmandy / Celestron** profile 的 **`optional_indi_if`** 在 **`lsusb` 出现 `03c3:294f`** 时追加 **`indi_asi_ccd`**（可与 SBIG、Oasis 等并存；勿与第二台 CCD 同场除非改 profile）。  
- **仅插相机**（无赤道仪）：profile **`zwo_asi294mc_usb_only`**（priority 76）起 **`-v indi_asi_ccd`**。  
- **INDI 设备名**须用完整名 **`ZWO CCD ASI294MC Pro`**（`indi_setprop 'ZWO CCD.CONNECTION…'` 会失败）。  
- **Telbot**：`TELBOT_INDI_CCD_DEVICE=ZWO CCD ASI294MC Pro`；`telbot camera connect --execute` / `telbot camera snap -s 1 --execute`。  
- **udev**：`99-telbot-mount.rules` 对 **`03c3:294f`** add/remove 触发选镜；需 **`indi-asi`**（`libasi`）。

### PlaneWave L350（PWI4 + `indi_planewave_telescope`）

现场 **VID:PID `1cbe:0267`**。与 Losmandy/Celestron 不同：**INDI 不直接占串口**；须先 **PWI4** 独占 `ttyACM0/1`，INDI 经 **HTTP `127.0.0.1:8220`** 中转。

**Debian trixie `indi-bin` 1.9.9（arm64）不打包 `indi_planewave_telescope`**（上游该驱动在 INDI **2.0+**，见 `planewave_mount.cpp`）。`check-usb-registry-drivers.sh` 报 **MISS** 时，常见是已切到 Debian 1.9.9 栈、卸掉 astroberry 2.2 之后——**不是** Telbot 删了 PWI4 逻辑（`pwi4.service`、`telbot-select-mount.sh` 仍在）。仅跑通 **PWI4 HTTP**（`curl :8220/status`）不等于 INDI/Telbot 赤道仪链路已就绪。

| 项 | 值 |
|----|-----|
| profile | **`planewave_l350_usb`**（priority 101） |
| PWI4 | **`pwi4.service`** + **`telbot-pwi4-wrap.sh`**（`./run-pwi4 --nogui`） |
| 配置 | **`~/.planewave/PWI4/Settings`**（Windows `Documents\PlaneWave Instruments\PWI4` 拷到此处） |
| INDI | **`indi_planewave_telescope`**；设备名 **`PlaneWave`** |
| 地址 | auto-connect 前 **`127.0.0.1:8220`**（勿用默认 `192.168.1.1`） |
| `.env` | `TELBOT_INDI_DEVICE=PlaneWave`，`TELBOT_INDI_DEVICE_AUTO=true` |

**安装**：

```bash
cd ~/Telbot
sudo cp deploy/pwi4.service /etc/systemd/system/
sudo cp deploy/telbot-pwi4-wrap.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/telbot-pwi4-wrap.sh
# 编辑 pwi4.service 的 User/WorkingDirectory；/etc/default/telbot-mount 可设 TELBOT_PWI4_HOME
sudo systemctl daemon-reload
# 勿 enable pwi4 — 由 telbot-select-mount 在插 USB 时 start

sudo bash deploy/install-indi-planewave-telescope.sh   # INDI 驱动（Debian indi-bin 不含）
command -v indi_planewave_telescope
```

**验收**：`curl -s http://127.0.0.1:8220/status | grep mount.is_connected` 应为 **true**（选镜在 INDI auto-connect **之后**会再调 `PWI4 /mount/connect` 并重试）；`cat /run/telbot/indiserver.args` 含 `indi_planewave_telescope`；`indi_getprop -p 7624 'PlaneWave.DEVICE_ADDRESS.ADDRESS'` → `127.0.0.1`。拔 USB 后 **`pwi4.service` stopped**，indiserver 回退模拟器。

### QHY174M（引导 `1618:c174` → 工作 `1618:c175`）

| 阶段 | VID:PID | 说明 |
|------|---------|------|
| 引导 | `1618:c174` | WestBridge，需 **fxload-fx3** + **QHY174.img**（系统 `libqhy` / `85-qhyccd.rules`） |
| 工作 | `1618:c175` | **QHYCCD QHY174/GPS**，`lsusb` 与 **`mount_profiles.json` 选镜**均以此为准 |

- **INDI**：设备名 **`QHY CCD QHY174M`**，驱动 **`indi_qhy_ccd`**（现场已验证 2.9）。
- 与赤道仪同场时：**Losmandy / Celestron** 的 **`optional_indi_if`** 在 **`lsusb` 出现 `1618:c175`** 时追加 **`indi_qhy_ccd`**。
- **仅插相机**：profile **`qhy174m_usb_only`**（priority 77）起 **`-v indi_qhy_ccd`**。
- **读不到设备**：若仅见 **`c174`** 未见 **`c175`**，多为固件未加载完；增大 **`TELBOT_UDEV_SETTLE_SECONDS`**（如 8）或等几秒后 **`sudo telbot-select-mount.sh`**。勿把 **`1618:0174`**（QHY5III174）与本机混淆。
- **udev**：**`c174` 与 `c175`** 的 add/remove 均触发选镜；拔线后 **`TELBOT_UDEV_REMOVE_SETTLE_SECONDS`** 默认 5。
- **Telbot**：`TELBOT_INDI_CCD_DEVICE=QHY CCD QHY174M`；`telbot camera connect --execute` / `telbot camera snap -s 1 --execute`。

## NTP

赤道仪 GOTO 与天算依赖系统时间，请保持 **NTP** 同步。
