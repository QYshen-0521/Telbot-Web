# Telbot 天文控制台

Telbot 的网页是一层**始终可打开的静态壳**。没有树莓派时，它就是一份公开说明：功能概览、工作原理、安全说明、界面导览。检测到 Telbot 后端（`GET /health` 成功）之后，同一页才启用指向、拍摄、设备和计划。

```text
浏览器
  ├─ 静态壳（GitHub Pages，或树莓派上的 /）
  │    概览、原理、安全、导览：不需要后端
  └─ GET /health
       ├─ 失败 → 浏览模式，控制停用，状态为「设备未连接」
       └─ 成功 → 启用 /text /chat /camera/* /plan/* /config/env …
            └─ 树莓派 FastAPI → INDI → 赤道仪 / 相机 / 电调 / 滤镜轮
```

两种用法可以同时存在：

| | 页面放在哪 | 控制 |
| --- | --- | --- |
| A. GitHub Pages | 免费静态托管，仓库里的 `web/` | 可选。填 API 地址，或让浏览器探测到本机 / 局域网里的 Telbot |
| B. 树莓派同源 | `telbot serve` 直接提供 `/` | 相对路径调用同一进程里的 API |

## 更新说明

- 2026-10：网页改为离线可浏览的静态控制台。未检测到后端时停用全部控制；`GET /health` 成功后才启用。FastAPI 允许浏览器跨域调用，并用 GitHub Actions 把 `web/` 部署到 GitHub Pages。

## 功能

- 浏览模式：不连接设备也能阅读 Telbot 能做什么、请求怎么走、干跑和真机的差别。
- 对话：连接后，操作句走 `POST /text`，问句走 `POST /chat`。
- 拍摄：单张、预览、边拍边叠、Bias / Dark / Flat / Light。
- 设备：赤道仪、相机、电调、滤镜轮、USB。
- 计划：系外行星凌星状态、启动和中止。
- 安全：默认干跑（`execute=false`）。打开真机执行前要确认；之后每一次真实操作还会再确认。保存 `.env` 会单独确认，因为它总是写入，不受干跑开关控制。

## 目录

```text
web/
  index.html      静态页面。GitHub Pages 的站点根就是这个目录
  styles.css
  app.js          连接探测、浏览/控制切换、API 调用
  .nojekyll       若改用分支部署，避免 Jekyll 忽略文件

src/telbot/
  http_app.py     FastAPI：/、/styles.css、/app.js、/web/* 以及控制 API
  chat_qa.py      /chat 问答
  text_intent.py  中文指令识别
  intent_exec.py  意图执行
```

## 连接是怎么判断的

页面加载后自动请求 `GET /health?quick=1`（成功后再读完整的 `GET /health` 做设备摘要）。满足 HTTP 成功且 JSON 里 `status` 为 `ok`（或没有 `status` 字段）才算连上。

探测顺序：

1. 地址栏 `?api=`，或连接面板里填写的地址（填了会排在最前；若它失败，仍继续往下找，并在面板说明实际用了哪一个）。`?api=same` 只检测与页面同源的 `/health`。
2. 与当前页面同源的 `/health`。树莓派打开 `http://主机:8765/` 时走这里。
3. 勾选「记住此地址」后写入 `localStorage` 的 API 根地址（键 `telbot.apiBase`）。
4. 同样在勾选记住时保存的 https 隧道（键 `telbot.tunnelUrl`），例如 `https://xxxx.trycloudflare.com`。
5. `http://telbot.local:8765`
6. `http://127.0.0.1:8765`

取消「记住此地址」后再点「重新检测」，会忘掉已保存的地址和隧道。

GitHub Pages 是 HTTPS。浏览器会把页面上对 `http://127.0.0.1` 或 `http://telbot.local` 的请求当成混合内容拦掉。从 Pages 远程控制时，请填写 **https** 隧道；人在望远镜旁边时，直接打开树莓派上的 http 页面即可。

跨域响应带有 `Access-Control-Allow-Origin: *`，以及 Chrome 访问局域网所需的 `Access-Control-Allow-Private-Network: true`。这只解决浏览器拦截，**不是身份验证**。

## 本地运行

需要 Python 3.11 或更高版本。

```bash
cd Telbot-Web
pip install -e .
telbot serve --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

这是同源控制。局域网里要让别的设备访问时，把 `--host` 改成 `0.0.0.0`，再用 `http://telbot.local:8765/` 或树莓派的 IP。

只看静态页、先不启后端：

```bash
cd web
python -m http.server 8080
```

打开 `http://127.0.0.1:8080/`。此时应显示「设备未连接」，介绍可滚动阅读，控制区为停用。若本机 8765 上已有 Telbot，刷新后会自动探测到 `http://127.0.0.1:8765` 并启用控制。也可以手动写 `?api=http://127.0.0.1:8765`。

## GitHub Pages（一直在线的免费静态站）

仓库里的 [`.github/workflows/pages.yml`](.github/workflows/pages.yml) 会在 `main` 上 `web/` 变化时，把 `web/` 部署到 GitHub Pages。

启用步骤：

1. 打开仓库 **Settings → Pages**。
2. **Build and deployment** 的 Source 选 **GitHub Actions**（不要选 Deploy from a branch，除非你打算不用这个 workflow）。
3. 把包含 `web/` 的提交合并进 `main`。Actions 里的 “Deploy GitHub Pages” 成功后即可访问。

本仓库的站点地址是：

```text
https://qyshen-0521.github.io/Telbot-Web/
```

组织名或仓库名如果改过，把用户名和仓库名换成小写用户名后的实际 Pages 域名；仓库名保留大小写。Pages 环境第一次可能要等 workflow 跑完才出现。

也可以不用 Actions，在 Pages 里选 Deploy from a branch，分支 `main`，目录 `/web`。`web/.nojekyll` 是给这种部署方式用的。两种方式选一种即可，推荐 Actions。

## 给别人临时访问 API

Pages 上的说明页谁都可以看。要让不在同一局域网的浏览器真正控制设备，需要一条到达树莓派的 **https** 隧道，例如：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

把生成的 `https://xxxx.trycloudflare.com` 填进控制台的 API 地址并勾选记住。隧道是临时的，也会暴露 API。

## 安全

- 公网链接和隧道不要发给不信任的人。
- 默认干跑。连接真实设备时，不要随手打开「真机执行」。
- 真机前确认镜筒、线缆和周围的人，并且不要让 Ekos 等程序同时控制同一套设备。
- CORS 不代替登录。树莓派不要直接对公网监听。
