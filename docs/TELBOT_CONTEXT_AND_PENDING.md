# Telbot 上下文与待办汇总

本文档在对话上下文将耗尽时整理 **三项待完成工作** 与 **关键现场/技术信息**，便于后续 Agent 或人工接续。详细设计仍以各专项文档为准。

---

## 一、规划观测清单（Observing plan）

### 当前实现（阶段 0）

- **配置**：`src/telbot/config.py` 中 `TELBOT_PLAN_*`；`.env.example` 有注释。
- **时间窗**：`src/telbot/planning/window.py` — 自动「今晚」（太阳视高度阈值）或 `--from` / `--to`（ISO 8601 含时区）。
- **CLI**：`telbot plan window`（JSON 输出含 `phase0_config`、`plans_dir`）。
- **路径**：`data/plans/`（`repo_paths.plans_dir()`）；`.gitignore` 忽略 `data/plans/*.json`。
- **文档**：`README.md`（已实现速览中的观测计划一行 + `telbot plan` CLI）；**注意**：`docs/MOUNT_AUTO_PLAN.md` 描述的是 **赤道仪 USB 自动选驱动**，与观测计划无关。

### 当前实现（阶段 1）

- **天气**：`src/telbot/planning/weather.py` — `open_meteo`（Open-Meteo 逐小时，与夜窗时间重叠的小时聚合）、`seven_timer`（粗序列）、`qweather`（占位）、`none`。
- **合并与落盘**：`src/telbot/planning/preview.py` — `build_plan_preview_payload` / `save_plan_preview_json`。
- **CLI**：`telbot plan preview`（默认写 `data/plans/plan_preview_*.json`）；`--no-save` 仅打印。

### 当前实现（阶段 2）

- **星表**：`src/telbot/dso_catalog.py` — `list_plan_candidates`（OpenNGC 本地 CSV）。
- **坐标与月亮**：`src/telbot/planning/coordinates.py`。
- **排程**：`src/telbot/planning/phase2_schedule.py` — `build_phase2_payload` / `save_phase2_plan_json`。
- **CLI**：`telbot plan schedule`（`--no-weather` / `--sources` / `--limit`）；默认写 `plan_phase2_*.json`。

### 当前实现（阶段 3）

- **合并与确认**：`src/telbot/planning/tonight.py` — `build_tonight_payload` / `save_tonight_plan_json` / `print_tonight_summary`。
- **CLI**：`telbot plan tonight`（`--no-save` / `--yes` / `--quiet` / `--json`）；落盘 `tonight_*.json`，含 `confirmation`。
- **说明**：真机 GOTO 仍为阶段 4，不在 `plan tonight` 中执行。

### 当前实现（阶段 4）

- **执行**：`src/telbot/planning/execute.py` — `resolve_latest_tonight_plan`、`load_plan_json`、`execute_tonight_plan`（J2000→JNow、`slew_equatorial_eod`、可选 `execute_voice_intent` snap）。
- **CLI**：`telbot plan execute`（`--plan`、`--execute`、`--snap`、`--force`、`--on-fail ask|park|abort`）。

### 当前实现（阶段 5）

- **监控**：`src/telbot/planning/monitor.py` — `should_park_from_weather`、`run_monitor_cycle`。
- **CLI**：`telbot plan monitor`（`--once`、`--execute`、`--interval-minutes`、`--max-iterations`）。
- **未做**：自动调焦/导星；天气变化时的脱焦与线缆风险由现场评估。

### 待完成（增强项，摘要）

| 内容 | 说明 |
|------|------|
| 调焦/导星 | 与 INDI 设备能力及现场流程结合，非本仓库首版范围。 |

**风险边界**：子午线翻转与线缆、NTP、真机须确认安全。详见 `README.md`。

---

## 二、兼容尽可能多品牌的望远镜

### 已实现

- **Manifest**：`deploy/mount_profiles.json` — `usb_vid_pid` / `by_id_substring` → `indi_drivers` + `optional_indi_drivers` + `device_name_hint`。
- **选镜脚本**：`deploy/telbot_select_mount.py`、`deploy/telbot-select-mount.sh`（`flock`）；写 `/run/telbot/indiserver.args`、`indi_device_hint`、`mount_profile_id`；可 `systemctl restart indi-telescope.service`。
- **systemd**：`deploy/indi-telescope.service`（`ExecStartPre` 用 `TELBOT_SELECT_MOUNT_NO_RESTART=1`）、`deploy/telbot-indiserver-wrap.sh`。
- **udev 示例**：`deploy/99-telbot-mount.rules`。
- **Telbot**：`TELBOT_INDI_DEVICE_AUTO`、`resolve_telescope_device`（`src/telbot/mount_resolve.py`）；`discover_telescope_devices`（`src/telbot/indi.py`）；CLI/HTTP/intent 已接解析。
- **文档**：`docs/MOUNT_AUTO.md`、`docs/MOUNT_AUTO_PLAN.md`；`README`（含树莓派联机与语音意图）；`日常观测操作指南`（若存在）。

### 待增强（建议）

- Manifest 支持 **`TELBOT_MOUNT_FORCE_PROFILE`** 或 **无 USB 时默认 profile**（WiFi-only 赤道仪）。
- **WiFi 赤道仪**：不在 `lsusb` 中；需单独 profile 或固定 `default_profile_id` + SynScan 等驱动。
- 新品牌：**加 profile 行** + `apt`/源码安装对应 `indi_*` + 现场核对 `lsusb`/by-id。

**原则**：换镜可重启 `indiserver`；单一 `indiserver` 占 **7624**；与 Ekos 勿双控。

---

## 三、Sky-Watcher 品牌：驱动与 Pi 现状

### 官方渠道

- **Sky-Watcher 官网**（Software & Firmware）：主要提供 **SynScan / SynScan Pro**（Win/Mac/Android）、**固件**，**不提供**树莓派用的 **INDI `.deb` 单独包**。
- **Linux / Pi**：使用 **INDI 社区** 的 SynScan 类驱动，见 [INDI Sky-Watcher](https://indilib.org/telescopes/skywatcher.html)、[SynScan Telescope](https://indilib.org/telescopes/skywatcher/synscan-telescope.html)。

### 当前 Debian stable（现场 Pi）观察

- **`indi-full`**：源中 **不存在**。
- **`apt-cache pkgnames '^indi-'`**：常见仅有 **`indi-eqmod`**、**`indi-nexdome`** 等；**无** `indi-synscan` 等包。
- **`indi-eqmod`**：EQMOD 协议，**不能**替代 **SynScan WiFi（TCP）**。
- **Gemini/SBIG**：多来自 **`indi-bin`** 等**聚合包**（`dpkg -S /usr/bin/indi_lx200gemini` 可查），非「每个驱动一个 `indi-xxx` 包名」。

### 可行路径

1. **从源码编译** [indilib/indi-3rdparty](https://github.com/indilib/indi-3rdparty) 中 SynScan 相关驱动，将生成的 `indi_synscan_telescope`（以仓库为准）加入 `indiserver -v ...`。
2. **backports / 更高版本源**（需熟悉 apt pinning，慎用）。
3. **天文专用镜像**（如 StellarMate、AstroArch 等）— 改动大。

### 网络现场（用户已验证方向）

- 赤道仪 **自建热点 SSID：`SAGTI`**（开放）；Pi **Wi‑Fi 连 SAGTI** 后可 `ping` 赤道仪。
- **电脑调试**：可 **USB 共享 iPhone（Apple Mobile Device Ethernet）上网** + **Wi‑Fi 连 SAGTI** SSH Pi；必要时调 **Windows 接口跃点数**（USB metric 小、WLAN 大）。
- **长期**：Pi **网线接路由器** + **Wi‑Fi 连 SAGTI**；或赤道仪改 **STA 进家用路由**，全家同网。

### INDI 与 Telbot

- `indiserver` 仍在本机 **127.0.0.1:7624**；SynScan 驱动需在 INDI 里填 **赤道仪 IP/端口** 并 **CONNECT**。
- `.env`：**`TELBOT_INDI_DEVICE`** 与 `indi_getprop` 设备名一致；WiFi 场景建议 **`TELBOT_INDI_DEVICE_AUTO=false`** 或保证 **`/run/telbot/indi_device_hint`** 正确（无 `/dev/tty` 匹配时）。

---

## 四、其他关键信息速查

| 主题 | 要点 |
|------|------|
| **Telbot** | 默认干跑；`--execute` 真机；`TELBOT_INDI_DEVICE` / `TELBOT_INDI_CCD_DEVICE`；地平 `TELBOT_MIN_ALTITUDE_DEG`；观测地经纬度。 |
| **CCD** | 默认 FITS 目录 `~/Telbot/data/ccd_captures`（`TELBOT_CCD_SAVE_DIR` 可覆盖）；INDI `UPLOAD_DIR` 对齐；`telbot camera snap`。 |
| **Plate solve** | ASTAP + astropy；`telbot platesolve`；`POST /platesolve`。 |
| **systemd** | `indi-gemini.service` 为固定驱动遗留示例；多品牌用 **`indi-telescope.service`** + 选镜脚本；**User=/Group=dialout** 需与 Pi 用户一致。 |
| **交接** | 现场 Pi 型号、Debian/INDI 包版本、SBIG apt 说明见 [`PI_FIELD_HARDWARE.md`](PI_FIELD_HARDWARE.md)；更细 Gemini 见 `SESSION_HANDOFF.md`（若跟踪）。 |

---

## 五、建议的下一步执行顺序（给 Agent）

1. **Sky-Watcher**：在目标 Pi 上确认 `libindi`/`cmake` 依赖 → 按 INDI 文档编译 SynScan → 更新 `mount_profiles.json` 与 `indiserver` 启动行 → Ekos/`indi_getprop` 验证 → `telbot mount goto` 干跑与真机。  
2. **多品牌**：为 WiFi-only 增加 manifest/环境变量强制 profile；文档补一节。  
3. **观测计划**：从阶段 1 天气客户端 + 写 `data/plans/*.json` 草稿开始。

---

*文件路径：`docs/TELBOT_CONTEXT_AND_PENDING.md`。若需纳入 Git，请确认 `.gitignore` 中已 `!docs/TELBOT_CONTEXT_AND_PENDING.md`。*
