# USB 设备 ↔ INDI 驱动注册表

现场通过 **`lsusb`** 看到的 **VID:PID** 与 **INDI 驱动**、内核接口、**Telbot CLI** 的对应关系。**新增硬件时请先在本表追加一行**，再视需要改 `deploy/mount_profiles.json` 与 `deploy/99-telbot-mount.rules`。

| 字段 | 说明 |
|------|------|
| **VID:PID** | `lsusb` 中 `ID xxxx:yyyy`，小写、带冒号（与 `mount_profiles` 一致） |
| **INDI 设备名** | `indi_getprop` 中显示的名称（可含空格，与 `.env` 中 `TELBOT_INDI_*_DEVICE` 一致） |
| **INDI 驱动** | `indiserver -v` 后的可执行名（如 `indi_lx200gemini`） |
| **Telbot profile** | `deploy/mount_profiles.json` 中的 `id`；无则写 `—` |
| **Telbot CLI** | 本仓库子命令（默认干跑，真机加 `--execute`） |
| **接口** | 内核枚举方式，便于写 udev |
| **备注** | 包名、权限、关键 INDI 属性 |

---

## 已登记设备

| VID:PID | 现场名称（lsusb / dmesg） | 类型 | INDI 设备名 | INDI 驱动 | Telbot profile | Telbot CLI | 接口 | 备注 |
|---------|---------------------------|------|-------------|-----------|----------------|------------|------|------|
| `1fc9:1705` | NXPbyLosmandy Gemini | 赤道仪 | `Losmandy Gemini` | `indi_lx200gemini` | `losmandy_gemini_usb` | `telbot mount *` | `cdc_acm` → `ttyACM*` | `.env`：`TELBOT_INDI_DEVICE` / `TELBOT_INDI_DEVICE_AUTO` |
| `1cbe:0267` | PlaneWave Instruments | 赤道仪 L350 | `PlaneWave` | `indi_planewave_telescope` | `planewave_l350_usb` | `telbot mount *` | `cdc_acm` → `ttyACM0/1`（**PWI4 独占**） | **Debian `indi-bin` 无 `indi_planewave_telescope`**；**`deploy/install-indi-planewave-telescope.sh`** + **`pwi4.service`**。见 **`INDI_APT_STACK.md` §7.2** |
| `067b:2303` | Prolific USB-Serial Controller D | 经纬仪 | `Celestron GPS` | `indi_celestron_gps` | `celestron_prolific_usb` | `telbot mount *` | `pl2303` → `ttyUSB*` | **`indi-bin`**（含 `indi_celestron_gps`） |
| `0d97:0101` | SBIG USBX-CAM Engine | CCD | `SBIG CCD`（常见） | `indi_sbig_ccd` | `sbig_ccd_usb_only`；赤道仪/经纬仪 `optional_indi_if` | `telbot camera *` | USB bulk，**无 tty** | **Debian trixie**：`sudo apt install indi-sbig`（依赖 `libsbig4t64`，contrib+non-free）；≠ `indi-bin`；现场主机见 [`PI_FIELD_HARDWARE.md`](PI_FIELD_HARDWARE.md) |
| `10c4:ea60` | Silicon Labs CP2102 UART Bridge | 滤镜轮 | `QHYCFW3` | `indi_qhycfw3_wheel` | `qhy_cfw3_wheel_usb` | `telbot filter *` | 串口；`by-id` 常含 `Silicon_Labs_CP2102` | 驱动在 **`indi-bin`**；多 CP2102 时宜 `match_mode: all` |
| `338f:a0f0` | Astroasis Oasis Focuser HID | 电调 | `Oasis Focuser` | `indi_oasis_focuser` | `oasis_focuser_usb_only`；赤道仪 `optional_indi_if` | `telbot focuser *` | **HID** → `/dev/hidraw*` | trixie **无** `indi-astroasis`；用 **`deploy/install-indi-oasis-focuser.sh`**（`indi-3rdparty-drivers` 解压）+ `hidraw` |
| `03c3:294f` | ZWO ASI294MC Pro | CCD | `ZWO CCD ASI294MC Pro` | `indi_asi_ccd` | `zwo_asi294mc_usb_only`；赤道仪 `optional_indi_if` | `telbot camera *` | USB3；ZWO `03c3` | **设备名含型号**；udev **`usb_device` add/remove**（`99-telbot-mount.rules`）；插拔后 `telbot-udev-select-mount.sh` 等待 3s 再选镜 |
| `1618:c174` | QHY174 WestBridge（fx3） | 引导 | — | — | — | — | USB3 | 上电后短暂出现；需 **fxload-fx3** + **QHY174.img**（`libqhy`/`85-qhyccd.rules`），随后变为 **`1618:c175`** |
| `1618:c175` | QHYCCD QHY174/GPS | CCD | `QHY CCD QHY174M` | `indi_qhy_ccd` | `qhy174m_usb_only`；赤道仪 `optional_indi_if` | `telbot camera *` | USB3 | **Debian trixie 无 `indi-qhy` deb**；`deploy/build-indi-3rdparty-qhy-oasis.sh`（见 `INDI_APT_STACK.md` §7） |

---

## Telbot 子命令与 INDI 属性（Oasis / QHY CFW3 / ZWO 示例）

### 电调 `telbot focuser`（Astroasis Oasis）

| CLI | INDI（设备名默认 `Oasis Focuser`） |
|-----|-------------------------------------|
| `telbot focuser connect --execute` | `{device}.CONNECTION.CONNECT=On` |
| `telbot focuser disconnect --execute` | `{device}.CONNECTION.DISCONNECT=On` |
| `telbot focuser position` | `ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION`（只读 getprop） |
| `telbot focuser max` | `FOCUS_MAX.FOCUS_MAX_VALUE` |
| `telbot focuser rel 50 in --execute` | `REL_FOCUS_POSITION.FOCUS_RELATIVE_POSITION=50` + `FOCUS_MOTION.FOCUS_INWARD=On` |
| `telbot focuser rel 50 out --execute` | 同上 + `FOCUS_MOTION.FOCUS_OUTWARD=On` |
| `telbot focuser abs 33400 --execute` | `ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION=33400` |

### 滤镜轮 `telbot filter`（QHY CFW3）

| CLI | INDI（设备名默认 `QHYCFW3`） |
|-----|------------------------------|
| `telbot filter connect --execute` | `CONNECTION.CONNECT=On` |
| `telbot filter disconnect --execute` | `CONNECTION.DISCONNECT=On` |
| `telbot filter goto red --execute` | `FILTER_SLOT.FILTER_SLOT_VALUE=1`（槽 1–7：Red…LPR） |

### 相机 `telbot camera`（ZWO ASI294MC Pro）

| CLI | INDI（设备名默认 `ZWO CCD ASI294MC Pro`，须与 `indi_getprop` 完全一致） |
|-----|-----------------------------------------------------------------------------|
| `telbot camera connect --execute` | `{device}.CONNECTION.CONNECT=On` |
| `telbot camera disconnect --execute` | `{device}.CONNECTION.DISCONNECT=On` |
| `telbot camera snap -s 5 --execute` | `UPLOAD_MODE.UPLOAD_LOCAL=On` + `UPLOAD_SETTINGS.UPLOAD_DIR=…`；`CCD_EXPOSURE.CCD_EXPOSURE_VALUE=5`；FITS 落 `~/Telbot/data/ccd_captures/YYYYMMDD/` |
| `telbot text "拍5秒" --apply --execute` | 意图 `snap`（同上曝光路径） |
| `telbot platesolve --execute -s 5` | 先 snap 再 ASTAP 解算 |

`.env`：`TELBOT_INDI_CCD_DEVICE=ZWO CCD ASI294MC Pro`（**不要用** `ZWO CCD`，那是驱动族名不是本机设备名）。

### 相机 `telbot camera`（QHY174M）

| CLI | INDI（设备名默认 `QHY CCD QHY174M`，须与 `indi_getprop` 完全一致） |
|-----|-----------------------------------------------------------------------------|
| `telbot camera connect --execute` | `{device}.CONNECTION.CONNECT=On` |
| `telbot camera disconnect --execute` | `{device}.CONNECTION.DISCONNECT=On` |
| `telbot camera snap -s 5 --execute` | `UPLOAD_MODE.UPLOAD_LOCAL=On` + `UPLOAD_SETTINGS.UPLOAD_DIR=…`；`CCD_EXPOSURE.CCD_EXPOSURE_VALUE=5`；FITS 落 `~/Telbot/data/ccd_captures/YYYYMMDD/` |

`.env`：`TELBOT_INDI_CCD_DEVICE=QHY CCD QHY174M`（**不要用** `QHY CCD`）。多台 CCD 勿同时插入，否则 `.env` 仅保留最后一台自动 CONNECT 的设备名。

---

## 无天文 USB 时的回退（非具体芯片）

| 条件 | INDI 驱动 | Telbot |
|------|-----------|--------|
| 无任何 profile 匹配 | `indi_simulator_telescope` | `mount_profiles.json` → `on_no_usb_match` |

---

## 新增设备 checklist

1. 插上设备，记录：`lsusb`、`dmesg \| tail`、`ls -l /dev/serial/by-id/`、`ls /dev/hidraw*`。
2. `indi_getprop -p 7624 \| grep -i <关键字>`，记下 **INDI 设备名** 与关键属性。
3. 在本表 **「已登记设备」** 增加一行（VID:PID、驱动、CLI、`.env` 变量名）。
4. 若需 **USB 自动选镜/起 indiserver**：改 **`deploy/mount_profiles.json`** 与 **`99-telbot-mount.rules`**。
5. 若仅需 **Telbot 手控**：实现或复用 `src/telbot/*_indi.py` + `cli.py` 子命令，并在 **`.env.example`** 增加 `TELBOT_INDI_*_DEVICE`。
6. Pi 部署：`sudo cp` 到 `/usr/local/lib/telbot-deploy/`，`pip install -e .`，验证 CLI。
7. 若需 **USB 选镜后自动 CONNECTION.CONNECT**：在 **`mount_profiles.json`** 的 **`auto_connect_by_driver`** 中为该 **`indi_*`** 增加映射（见 `docs/MOUNT_AUTO.md`）。

---

### 相机 `telbot camera`（SBIG）

| CLI | INDI（设备名默认 `SBIG CCD`） |
|-----|--------------------------------|
| `telbot camera connect --execute` | `{device}.CONNECTION.CONNECT=On` |
| `telbot camera snap -s 5 --execute` | `CCD_EXPOSURE` + `UPLOAD_LOCAL`；FITS 落 `~/Telbot/data/ccd_captures/YYYYMMDD/` |

`.env`：`TELBOT_INDI_CCD_DEVICE=SBIG CCD`。驱动二进制：`/usr/bin/indi_sbig_ccd`（包 **indi-sbig**）。

---

## 与仓库其它文件的关系

- **离线保存 / 一键恢复本表全部驱动**：`deploy/indi-offline/README.md` → `fetch-indi-offline-debs.sh`、`restore-indi-usb-registry-drivers.sh`
- **从命令到硬件的调用链**：[`INDI_DRIVER_CALL_CHAIN.md`](INDI_DRIVER_CALL_CHAIN.md)
- **一键检查本表所列 `indi_*` 是否已安装**：`bash deploy/check-usb-registry-drivers.sh`（Pi 上在 `~/Telbot` 执行）
- **现场 Pi OS / apt / 包版本**：[`PI_FIELD_HARDWARE.md`](PI_FIELD_HARDWARE.md)
- **自动选镜运行时配置**：`deploy/mount_profiles.json`
- **插拔触发**：`deploy/99-telbot-mount.rules`
- **安装与死锁说明**：`docs/MOUNT_AUTO.md`
- **命令速查**：`help.md`
