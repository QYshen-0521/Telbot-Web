# Telbot 天文控制台

这是 Telbot 项目的网页控制台版本，用于通过浏览器完成天文问答、望远镜自然语言控制、相机拍照、设备状态查看、观测计划等操作。

## 功能

- 对话控制：输入自然语言，例如“帮我指向木星”“拍5秒”“归位”“检查设备”。
- 天文问答：询问项目和天文问题，例如“什么是 INDI”“M31 怎么拍”“暗场和平场有什么区别”。
- 相机拍摄：单张曝光、预览、边拍边叠、校准帧入口。
- 设备状态：查看赤道仪、相机、滤镜轮、电调等设备状态。
- 计划页面：系外行星凌星相关计划入口。
- 安全模式：默认干跑，不会真实转动望远镜或曝光；打开真机执行前需要确认。

## 目录说明

```text
web/
  index.html      前端页面结构
  styles.css      页面样式
  app.js          前端交互逻辑

src/telbot/
  http_app.py     FastAPI 后端入口，提供 /、/web、/chat、/text、/camera/snap 等接口
  chat_qa.py      天文问答逻辑
  text_intent.py  中文自然语言命令识别
  intent_exec.py  控制意图执行
```

## 本地运行

需要 Python 3.11 或更高版本。

```powershell
cd Telbot-Web
pip install -e .
telbot serve --host 127.0.0.1 --port 8765
```

然后浏览器打开：

```text
http://127.0.0.1:8765/
```

## 给别人临时访问

如果对方不在同一个局域网，可以用 Cloudflare Tunnel：

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://127.0.0.1:8765
```

它会生成一个 `https://xxxx.trycloudflare.com` 临时网址。

## 安全提醒

公网链接不要随便发给不可信的人。网站默认是干跑模式；连接真实设备时，不要随意开启“真机执行”。
