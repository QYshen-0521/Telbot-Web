# INDI 离线驱动包（`USB_DEVICE_REGISTRY` 全量）

本目录保存 [`docs/USB_DEVICE_REGISTRY.md`](../../docs/USB_DEVICE_REGISTRY.md) 中登记的 **全部 `indi_*` 驱动** 及其安装材料，用于 Pi 重装、换机或备份到 Mac。

**调用链说明**（从 USB 插入到 `telbot mount/camera/...` 执行）：[`docs/INDI_DRIVER_CALL_CHAIN.md`](../../docs/INDI_DRIVER_CALL_CHAIN.md)。

`.deb` / `tar.gz` / `MANIFEST.txt` / `apt-telbot-indi.pref`（fetch 时从 `deploy/apt-telbot-indi.pref` 复制）**不提交 Git**（见根目录 `.gitignore`）。`arm64/` 下仅 **`.gitkeep`** 进仓库。

---

## 目录结构

```text
deploy/indi-offline/arm64/
  MANIFEST.txt
  apt-telbot-indi.pref
  debian/                         # Debian 1.9.9 核心（登记表 5 个驱动 + 工具）
    indi-bin_*.deb
    indi-sbig_*.deb
    indi-asi_*.deb
    libindi-dev_*.deb
    …
  indi-bin_2.2.1_arm64.deb        # PlaneWave 驱动二进制
  libindi1_2.2.1_arm64.deb
  indi-3rdparty-drivers_2.2.0_*.deb
  indi-3rdparty-libs_2.2.0_*.deb
  indi-3rdparty-v1.9.9.tar.gz     # QHY 编译
  installed-snapshot.tar.gz       # 可选：Pi 当前 /usr/local + indi_qhy_ccd
  installed-paths.txt
```

---

## 登记表驱动 ↔ 本目录

| INDI 驱动 | 恢复来源 |
|-----------|----------|
| `indi_lx200gemini` | `debian/indi-bin` |
| `indi_celestron_gps` | `debian/indi-bin` |
| `indi_qhycfw3_wheel` | `debian/indi-bin` |
| `indi_sbig_ccd` | `debian/indi-sbig` + `libsbig4t64` |
| `indi_asi_ccd` | `debian/indi-asi` |
| `indi_planewave_telescope` | astroberry `indi-bin` + `libindi1`，或 snapshot |
| `indi_oasis_focuser` | `indi-3rdparty-drivers/libs`，或 snapshot |
| `indi_qhy_ccd` | `indi-3rdparty-v1.9.9.tar.gz` 编译，或 snapshot |

PlaneWave 另需 **PWI4**（`deploy/pwi4.service`，不在此目录）。

---

## 在 Pi 上：保存到本目录

驱动已在 Pi 上装好、工作正常时：

```bash
cd ~/Telbot
git pull
bash deploy/fetch-indi-offline-debs.sh
sudo bash deploy/archive-indi-installed-to-offline.sh
ls -la deploy/indi-offline/arm64/
cat deploy/indi-offline/arm64/MANIFEST.txt
```

或一次拉 deb 并打快照：

```bash
INDI_OFFLINE_ARCHIVE_AFTER_FETCH=1 bash deploy/fetch-indi-offline-debs.sh
```

同步到 Mac 备份：

```bash
rsync -av telbot:~/Telbot/deploy/indi-offline/ ~/Telbot-offline-indi/
```

---

## 一键恢复（新 Pi 或重装后）

```bash
cd ~/Telbot
git pull
sudo bash deploy/restore-indi-usb-registry-drivers.sh
bash deploy/check-usb-registry-drivers.sh
```

顺序概要：

1. 安装 APT pin，优先 Debian INDI  
2. `apt install` **`debian/*.deb`**（无则走 `install-indi-drivers-debian.sh` 联网）  
3. 若有 **`installed-snapshot.tar.gz`** → 解压到 `/`（含 PlaneWave/Oasis/QHY 已装二进制）  
4. 否则用 astroberry deb 跑 `install-indi-planewave-telescope.sh`、`install-indi-oasis-focuser.sh`  
5. 若无 `indi_qhy_ccd` 且有 tarball → `build-indi-3rdparty-qhy-oasis.sh`  

跳过 QHY 编译（仅恢复 deb + snapshot）：

```bash
sudo RESTORE_SKIP_QHY_BUILD=1 bash deploy/restore-indi-usb-registry-drivers.sh
```

---

## 脚本索引

| 脚本 | 作用 |
|------|------|
| `deploy/fetch-indi-offline-debs.sh` | 下载 debian + astroberry + QHY tarball |
| `deploy/archive-indi-installed-to-offline.sh` | 快照 `/usr/local` 与 `indi_qhy_ccd` |
| `deploy/restore-indi-usb-registry-drivers.sh` | **一键恢复** |
| `deploy/check-usb-registry-drivers.sh` | 核对 8 个驱动二进制 |

---

## 环境变量

| 变量 | 默认 | 含义 |
|------|------|------|
| `TELBOT_INDI_OFFLINE_DIR` | `deploy/indi-offline/arm64` | 缓存根目录 |
| `INDI_OFFLINE_WITH_DEBIAN` | `1` | 是否 `apt-get download` Debian 包 |
| `INDI_OFFLINE_WITH_QHY_TARBALL` | `1` | 是否下载 QHY 源码 |
| `INDI_OFFLINE_ARCHIVE_AFTER_FETCH` | `0` | fetch 后是否自动 archive |
| `RESTORE_SKIP_QHY_BUILD` | `0` | 恢复时跳过 QHY 编译 |

栈策略见 [`docs/INDI_APT_STACK.md`](../../docs/INDI_APT_STACK.md)。
