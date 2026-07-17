# Telbot 命令一览（`telbot --help` 可看 Typer 生成的完整选项）

默认**干跑**（不转镜、不真曝光）；真机须在对应命令加 **`--execute`**（或观测计划阶段 4/5 说明）。详见文末「真机」小节。配置：合并 **`./.env`** 与 **`~/Telbot/.env`**；**Pi 换镜自动选镜（udev）**：见 [docs/MOUNT_AUTO.md](docs/MOUNT_AUTO.md)「换镜自动选镜」。需安装 **`99-telbot-mount.rules`**、**`telbot-udev-select-mount.sh`** 与 **`/etc/default/telbot-mount`**（`TELBOT_ENV_FILE`）。选镜并 restart 后默认还会 **自动 CONNECTION.CONNECT** 各设备（`auto_connect_by_driver`）；关闭 **`TELBOT_SELECT_MOUNT_AUTO_CONNECT=0`**。

```bash
telbot --help                       # 顶层子命令列表与简述
telbot preflight                    # 设备就绪诊断（INDI/赤道仪/CCD/.env/保存目录；--json）
telbot version                      # 打印 Telbot 版本号
telbot serve --host 127.0.0.1 --port 8765   # 前台启动 HTTP API（Ctrl+C 结束）
telbot serve restart                        # 停旧进程 + 后台起新服务（App 调试；默认 0.0.0.0:8765）
telbot serve restart -r                     # 同上，且先 pip install -e .（Pi 上 git pull 后常用）
telbot serve stop                           # 仅停止占用 8765 的 HTTP 服务
telbot serve status                         # 端口 / pid 文件 / GET /health
telbot mount discover               # 单次全量 indi_getprop（快）；超时见 .env TELBOT_INDI_GETPROP_TIMEOUT
telbot mount sync-env               # 将当前解析设备名写入 .env（TELBOT_INDI_DEVICE_AUTO=true）
telbot mount position               # 当前指向 RA/Dec（EQUATORIAL_EOD）；可加 --json
telbot mount verify-pointing        # 拍照 + ASTAP 校验指向（--sync / --slew 须 --execute）
telbot mount goto --ra H --dec D    # GOTO：赤道坐标干跑（RA 小时，Dec 度，JNow/EOD）
telbot mount goto --json FILE.json  # 同上，JSON 为 GotoRequest（可含 dry_run）
telbot mount connect --execute      # 望远镜 CONNECTION.CONNECT（干跑）
telbot mount unpark --execute       # TELESCOPE_PARK.UNPARK（干跑）
telbot mount park --execute         # 归位 TELESCOPE_PARK（干跑）
telbot mount abort --execute        # TELESCOPE_ABORT_MOTION：真机前须 mount connect --execute，否则 INDI 无 ABORT 属性
telbot mount nudge left --execute   # 相对微移：left|right|up|down（干跑）
telbot camera snap -s <SEC> --execute # CCD 单次曝光（.env TELBOT_INDI_CCD_DEVICE，如 QHY CCD QHY174M / ZWO CCD ASI294MC Pro；FITS 见 data/ccd_captures/）
telbot camera expose-loop --duration 60   # 循环曝光至 duration/until（干跑；--session 会话子目录；--execute 真机）
telbot camera live-stack --duration 300 -s 2 --execute  # 边拍边叠（见 docs/LIVE_STACK.md）
telbot camera live-stack --duration 300 -s 2 --cal-bias .../bias_1129 --cal-dark .../dark_1129 --cal-flat .../flat_1430 --execute  # 用校准帧增强叠加
telbot camera cal bias -n 20 --execute              # 偏置场（盖镜盖；见 docs/CCD_CALIBRATION.md）
telbot camera cal dark -s 60 -n 10 --execute        # 暗场（盖镜盖、曝光与亮场一致）
telbot camera cal flat -s 1 -n 30 --execute         # 平场（均匀光源）
telbot camera cal light -s 120 -n 5 --execute       # 亮场序列
telbot schedule wait-until "2026-05-30T20:00:00+08:00"  # 阻塞等待至指定 UTC 时刻（Ctrl+C 取消）
telbot camera connect --execute     # CCD CONNECTION.CONNECT（.env TELBOT_INDI_CCD_DEVICE）
telbot camera disconnect --execute  # CCD CONNECTION.DISCONNECT
telbot filter list                  # 滤镜轮槽位 1–7 与名称（QHY CFW3 默认）
telbot filter connect --execute     # 滤镜轮 CONNECTION.CONNECT（干跑不加 --execute）
telbot filter disconnect --execute  # 滤镜轮 CONNECTION.DISCONNECT
telbot filter goto red --execute    # 切到 Red（槽 1）；亦可用 green/blue/H_Alpha/SII/OIII/LPR 或数字 1–7
telbot focuser connect --execute    # 电调 CONNECTION.CONNECT（默认 Oasis Focuser）
telbot focuser disconnect --execute # 电调 CONNECTION.DISCONNECT
telbot focuser position             # 当前绝对位置（getprop）
telbot focuser max                  # 最大行程 FOCUS_MAX_VALUE
telbot focuser rel 50 in --execute  # 相对移动 50 步向内（再 out 向外）
telbot focuser abs 33400 --execute  # 绝对移动到指定步数
telbot focuser autofocus --execute  # V 曲线自动对焦（需 CCD + astropy）
telbot ephem where BODY             # Skyfield 天体视位置（RA/Dec）；可加 --execute 再接 GOTO 真机
telbot text "句子"                  # 中文自然语言 → 意图 JSON（默认不落 INDI）；如「校准」「plate solve」→ platesolve；「校准并同步望远镜」→ platesolve + SYNC 对准（真机须 --execute）
telbot text "句子" --apply --execute # 本机解析后直接执行意图（真机；勿与 --send 同用）
telbot text "句子" --send --execute --url http://127.0.0.1:8765   # POST /intent 真机（须先 serve）
telbot text --rebuild-semantic-cache # 预计算句向量缓存后退出（调试用）
telbot listen                       # 录音→云端转写→同 text 解析路径（默认时长见 .env）
telbot listen -s 5 --apply --execute # 录 5 秒语音后本机真机执行意图（勿与 --send 同用）
telbot listen --hold-space          # 按住空格说话松手结束（需本机键盘）
telbot listen -D plughw:C,D         # 指定 ALSA 录音设备（也可用 .env TELBOT_ALSA_ARECORD_DEVICE）
telbot platesolve --execute -s 5       # 默认：真机拍一张（5s）再 ASTAP；FITS 落 ~/Telbot/data/ccd_captures/YYYYMMDD（拍照时自动设 INDI UPLOAD_DIR）
telbot platesolve --latest             # 不解算新图，仅用 CCD 保存目录内最新 .fits
telbot platesolve PATH.fits            # 仅解算指定 FITS（路径须在允许目录内）
telbot platesolve --latest --align sync           # 解算成功后干跑打印对准用 INDI（不写真机）
telbot platesolve --latest --align sync --execute # 解算成功后 JNow 同步（SYNC）；真机须配置经纬度
telbot platesolve PATH.fits --align slew --execute # 解算成功后 GOTO（SLEW）；同上
telbot catalog download             # 下载 HYG 恒星表到 ~/.cache/telbot/catalog/
telbot catalog download-openngc    # 下载 OpenNGC CSV（深空 GOTO/规划用）
telbot catalog search 片段          # 在已下载星表中按片段检索名称
telbot catalog path                 # 打印本地 HYG CSV 路径
telbot catalog path-openngc        # 打印本地 OpenNGC CSV 路径
telbot plan window                  # 观测阶段0：夜窗与 phase0 配置 JSON（可加 --from/--to）
telbot plan transits                # 今晚可观测系外行星凌星（需 pip install -e ".[exoplanets]"）
telbot plan transit-build --index 1 # 生成计划（ETC 算曝光；--planet / --filter；-s 可手动覆盖）
telbot plan transit-run --execute   # 按 UTC 时间线执行凌星计划（--plan / --force / Ctrl+C 中止；含 ingress 前 10min 预检拍照）
telbot plan transit-abort           # 立即终止正在运行的凌星观测：通知 transit-run 停镜并停曝光（另开终端运行）
telbot plan transit-abort --execute # 同上，并由本命令直接对赤道仪发送一次 ABORT（双保险，幂等）
# Skyfield 星历 de421.bsp 默认读 ~/Telbot/（任意目录运行 telbot 均可）；Pi 上已有文件则不会联网下载
telbot plan preview                 # 阶段1：夜窗+天气摘要，默认写 plan_preview_*.json（--no-save 不落盘）
telbot plan schedule                # 阶段2：OpenNGC 排程写 plan_phase2_*.json（--no-weather/--sources/--limit）
telbot plan tonight                 # 阶段3：表格预览，确认后写 tonight_*.json（--yes/--quiet/--json）
telbot plan execute                 # 阶段4：按 tonight 串行 GOTO（--execute 真机；--snap 曝光；--plan/--force）
telbot plan monitor --once          # 阶段5：一轮短时预报与超阈判断（--execute 真机 Park；--interval-minutes）
curl -s -X POST "http://127.0.0.1:8765/camera/snap?execute=false" -H "Content-Type: application/json" -d '{"exposure_seconds":1}'   # HTTP 干跑曝光示例（配合 telbot serve）
# App 错误解析：见 docs/HTTP_API_ERRORS.md（4xx/5xx 响应体为 JSON，含 message / hint / error）
# plate solve 后可选对准：body 须含 "execute":true 且 "align":"sync"|"slew"（与误触防护一致）；JNow 依赖 .env 经纬度。先拍再解算：{"snap_first":true,"execute":true} 可选 "exposure_seconds"
```

**text / listen 常用调试**：`--no-llm` 禁用云端大模型意图；`--no-semantic` 仅规则；`--semantic-only` 仅句向量。

---

## 语音与 `telbot text` / `listen` 可完成的操作

与 `telbot text "…"`、`telbot listen`、`POST /intent`、`POST /listen/audio`（转写后再解析）共用 **`VoiceIntentV1`**。默认只输出意图 JSON；**真机执行**须 **`telbot text … --apply --execute`**、**`telbot listen … --apply --execute`**，或 **`--send --execute`**（须先 **`telbot serve`**）。**`--apply` 后**会多打印 **`自然语言（App）`** JSON（字段 `nl`，仅中文，见 [`docs/INTENT_NATURAL_LANGUAGE.md`](docs/INTENT_NATURAL_LANGUAGE.md)）。解析顺序（规则）：**abort → connect → unpark → platesolve → snap → park → focuser → cfw → plan_exoplanet_transit → exoplanet_transits → usb_devices → help → nudge → describe → goto**；未命中时可再走句向量 / LLM。电调 **`TELBOT_INDI_FOCUSER_DEVICE`**；滤镜轮 **`TELBOT_INDI_CFW_DEVICE`**（如 `QHYCFW3`）。详细短语见 **`src/telbot/text_intent.py`**。

| 意图 | 说明与示例说法 | 真机 |
|------|----------------|------|
| **abort** | 立刻停止、马上停、别动了、中止、急停、停止跟踪等；子串「停止」较宽 | **`--execute`** |
| **connect** | 连接望远镜、连上赤道仪、建立连接；整句 `connect` / `connect the mount` / `indi connect` 等 | **`--execute`** |
| **unpark** | 解除停车、解锁停车；听写常见 **on park**、**onpark**、**un park** | **`--execute`** |
| **platesolve** | **校准**、板校、**plate solve** / platesolve；**校准并同步望远镜**、**plate solve and sync** 等 → 解算后 **SYNC** 对准；句中可带 **拍5秒** / **曝光3秒** 指定曝光 | **`--execute`**（须 CCD、ASTAP、**经纬度**；同步还须镜筒安全） |
| **snap** | 拍照、快门、开始曝光、**take a photo** 等；**拍5秒**、**曝光3秒**；与「看木星」等 GOTO 同句且含天体时**不**判为 snap | **`--execute`** |
| **park** | 归位、停车、回到初始、初始位置等 | **`--execute`** |
| **nudge** | **往左一点**、**往上转一点**、**再往下一点** 等（赤经左=西、右=东；上/下=赤纬） | **`--execute`** |
| **focuser_position** | **查询当前电调位置**、**电调位置多少**、**查看调焦位置** 等 | **`--execute`**（读位置；未连接时会先 CONNECT） |
| **focuser_rel** | **把电调向前/向后移动 N**、**调焦器往前移 30** 等（向前/往外→`out`，向后/往里→`in`，与 `telbot focuser rel` 一致） | **`--execute`** |
| **focuser_autofocus** | **帮我自动对焦**、**自动调焦** 等（CCD 拍图 + HFR V 曲线） | **`--execute`**（需 CCD、`pip install -e ".[autofocus]"`） |
| **cfw_current** | **查询当前滤镜**、**现在用的是哪个滤镜** 等 | **`--execute`**（读槽位；未连接时会先 CONNECT） |
| **cfw_list** | **有哪些滤镜可以用**、**列出所有滤镜** 等（默认 QHY CFW3 槽位表） | 无硬件动作（仅列表） |
| **cfw_goto** | **切换到红色滤镜**、**换成 Ha 滤镜**、**切到 4 号滤镜** 等（槽号或 red/H_Alpha/红 等） | **`--execute`** |
| **usb_devices** | **当前有哪些设备连接到 pi**、**树莓派上连了哪些设备**、**查询 usb 连接的设备** 等（`lsusb` + 登记表，见 `docs/USB_DEVICE_REGISTRY.md`） | **`--apply`** 即可（读 USB，无需 INDI） |
| **exoplanet_transits** | **今晚有哪些系外行星凌星**、**今晚有哪些系外行星观测事件**、**查询今晚凌星事件** 等（规则优先，无需 LLM；NASA Archive + astroplan） | **`--apply`** 即可（需 `pip install -e ".[exoplanets]"` 与网络） |
| **plan_exoplanet_transit** | **帮我规划第 1 个凌星**、**帮我规划第一个凌星**、**规划第 2 个凌星**、**今晚观测 WASP-12 b 凌星** 等（规则优先；生成 `telbot.plan_transit.v1`） | **`--apply`** 即可（须先查凌星列表或带行星全名；真机执行用 **`plan transit-run --execute`**） |
| **help** | **请介绍一下你的功能**、**你能做什么**、**使用帮助** 等（Telbot 能力与支持的设备说明，面向新手） | **`--apply`** 即可（无硬件） |
| **preflight** | **检查设备**、**设备就绪**、**设备诊断** 等（INDI/赤道仪/CCD/.env 一键诊断） | **`--apply`** 即可（只读） |
| **describe** | **介绍一下木星**、**M31是什么天体** 等（仅终端/HTTP 简介，**不转镜**） | 无赤道仪转动 |
| **goto** | **帮我指向木星**、**请帮我指向土星**、**帮我指向 M31**、**我要看火星**、**帮我把望远镜对准月球** 等（规则优先；M/NGC/HD 编号不依赖星表下载；中文深空名建议 `telbot catalog download`） | **`--execute`** |

---

## 麦克风与 ALSA（`telbot listen`）

`listen` 不设 `-D` 且 `.env` 为 default 时会尝试自动选 USB 等采集设备并打印 `plughw:C,D`，可复制到 **`TELBOT_ALSA_ARECORD_DEVICE`**。物理口可用拔插对照 `lsusb`；需固定设备时用 `arecord -l` 填 **`plughw:X,Y`**。CCD 与麦克风勿抢同一 USB 资源。

---

## 真机（转动 / 曝光 / Park）

| 场景 | 要点 |
|------|------|
| `plan execute` | **`--execute`**（及按需 **`--snap`**）；计划须含 **`confirmation`** 或 **`--force`** |
| `plan monitor` | 超阈归位加 **`--execute`**；长循环建议 **tmux/screen** |

现场须确认镜筒周无障碍、单一控制源、INDI 已连接；真拍注意曝光与视场安全。


## 重启 HTTP 服务（App 调试 / 更新代码后）

```bash
cd ~/Telbot && source .venv/bin/activate
telbot serve restart -r          # 推荐：重装 editable 包 + 后台重启 + 等待 /health
telbot serve status              # 确认 version 与端口
tail -f ~/Telbot/data/run/telbot-serve.log
```

`.env` 可固定绑定：`TELBOT_SERVE_HOST=0.0.0.0`、`TELBOT_SERVE_PORT=8765`（见 `.env.example`）。

手动方式（等价于 restart 的「停」步）：

```bash
sudo ss -tlnp | grep 8765
kill <pid>
telbot serve --host 0.0.0.0 --port 8765
```


## INDI 驱动（Debian trixie，多设备共存）

**勿混用 astroberry.io 的 `indi-bin` 2.2**（trixie arm64 常 404，且与 `indi-sbig` 冲突）。一次装齐赤道仪 + SBIG + ZWO + QHY + Oasis + Celestron：

```bash
cd ~/Telbot
sudo bash deploy/install-indi-drivers-debian.sh   # 装 indi-bin + indi-sbig + indi-asi（勿单独 apt 混装已废弃包名）
sudo systemctl restart indi-telescope.service
which indiserver indi_getprop indi_lx200gemini indi_sbig_ccd indi_asi_ccd
telbot preflight
# QHY 相机（Debian INDI 1.9.9 对齐源码 v1.9.9）：
sudo bash deploy/build-indi-3rdparty-qhy-oasis.sh
# Oasis 电调（勿 apt install indi-3rdparty-drivers；从 drivers/libs .deb 解压）：
sudo bash deploy/install-indi-oasis-focuser.sh
command -v indi_oasis_focuser && ldd "$(command -v indi_oasis_focuser)"
# PlaneWave L350（PWI4 + 从 astroberry indi-bin deb 解压驱动）：
sudo bash deploy/install-indi-planewave-telescope.sh
command -v indi_planewave_telescope && ldd "$(command -v indi_planewave_telescope)"
# 对照 USB_DEVICE_REGISTRY 检查全部驱动二进制：
bash deploy/check-usb-registry-drivers.sh
# 登记表全部驱动离线保存（Pi）：fetch + archive → deploy/indi-offline/
# Mac 从 Pi 下载到本仓库：rsync -av telbot:~/Telbot/deploy/indi-offline/ ~/projects/Telbot/deploy/indi-offline/
# 一键恢复（Pi）：sudo bash deploy/restore-indi-usb-registry-drivers.sh
# 调用链：docs/INDI_DRIVER_CALL_CHAIN.md · 包清单：deploy/indi-offline/README.md
```

策略与排障：[`docs/INDI_APT_STACK.md`](docs/INDI_APT_STACK.md)、[`docs/PI_FIELD_HARDWARE.md`](docs/PI_FIELD_HARDWARE.md)。

## INDI apt 防删（推荐安装）
sudo bash deploy/install-indi-apt-guard.sh   # install-indi-drivers-debian.sh 已会自动调用
telbot indi apt-guard status                 # 钩子与已保护包
telbot indi apt-guard check -- apt install <包名>   # 模拟，危险则退出码 1
# 紧急绕过：TELBOT_INDI_GUARD_DISABLED=1 sudo apt …

## INDI 服务（勿在 SSH 里 `indiserver -v … &`）
telbot indi status              # 是否「手动/孤儿」进程、与 indiserver.args 是否一致
telbot indi stop                # 停掉所有 indiserver（含终端里后台任务）
sudo telbot-select-mount.sh     # 或 telbot indi sync-mount（需已安装脚本）
sudo systemctl enable --now indi-telescope.service
journalctl -u indi-telescope.service -f   # 日志只看 journal，不会刷到 SSH 提示符

## 查看当前进程
pgrep -a indiserver 
telbot indi status 
sudo ss -tlnp | grep 8765


## 查看当前连接
indi_getprop -p 7624 'Losmandy Gemini.CONNECTION.CONNECT'
indi_getprop -p 7624 'PlaneWave.CONNECTION.CONNECT'
indi_getprop -p 7624 'Celestron GPS.CONNECTION.CONNECT'

## 停掉当前进程 
sudo kill xxxx 或 pkill indiserver
sudo systemctl stop indi-gemini.service

## 更新pi上代码时
cd ~/Telbot
source .venv/bin/activate   # 若你用 venv
pip install -e .

sudo cp deploy/mount_profiles.json deploy/99-telbot-mount.rules \
        deploy/telbot_select_mount.py deploy/indi_auto_connect_lite.py \
        deploy/telbot-select-mount.sh deploy/telbot-indiserver-wrap.sh \
        deploy/telbot-udev-select-mount.sh /usr/local/lib/telbot-deploy/
sudo cp deploy/99-telbot-mount.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo chmod +x /usr/local/lib/telbot-deploy/*.sh
sudo ln -sf /usr/local/lib/telbot-deploy/telbot-select-mount.sh /usr/local/bin/telbot-select-mount.sh
sudo ln -sf /usr/local/lib/telbot-deploy/telbot-indiserver-wrap.sh /usr/local/bin/telbot-indiserver-wrap.sh

sudo cp deploy/indi-telescope.service /etc/systemd/system/
sudo systemctl daemon-reload
