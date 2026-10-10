# Telbot

网页控制台，和 iOS 配套 App 同一套能力：对话、拍摄、计划、设置。未连接时可以浏览界面，控制保持停用。连上树莓派 `telbot serve` 之后才能操作设备。

对话默认干跑。打开「真机执行」前会确认，之后每条真实指令还会再确认。拍摄在盒子和主相机都已连接时真实执行，按下前确认。

## 运行

```bash
pip install -e .
telbot serve --host 127.0.0.1 --port 8765
```

打开 http://127.0.0.1:8765/

只看静态页：`cd web && python -m http.server 8080`

页面会按这个顺序找后端：地址栏 `?api=`、同源 `/health`、记住的地址、记住的 https 隧道、`http://telbot.local:8765`、`http://127.0.0.1:8765`。`?api=same` 只检测同源。

## GitHub Pages

https://qyshen-0521.github.io/Telbot-Web/

`main` 上 `web/` 变更会由 [`.github/workflows/pages.yml`](.github/workflows/pages.yml) 部署。Pages 是 https，要遥控设备请在「设置 → 连接设备」填写 https 隧道；人在望远镜旁边时，直接打开树莓派上的页面即可。
