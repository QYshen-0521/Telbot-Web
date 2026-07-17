# Telbot HTTP API 错误说明（iOS / App 对接）

**维护**：与 `src/telbot/http_app.py`、`src/telbot/http_errors.py` 同步。App 解析错误时**必须读取响应 JSON 正文**，不要只显示 HTTP 状态行（如 `500 Internal Server Error`）。

自 Telbot 0.6+：`telbot serve` 对 **4xx/5xx/422** 统一返回 JSON 信封（见下文）。成功响应仍为各接口原有字段（通常含 `"ok": true`）。

---

## 1. 统一错误 JSON 信封

任意错误响应（含原未处理的 **500**）体形如下：

```json
{
  "ok": false,
  "status_code": 500,
  "error": "internal_error",
  "message": "人类可读的一句说明（优先展示给用户）",
  "detail": "字符串或对象；与历史 FastAPI detail 兼容",
  "path": "/listen/text",
  "exception_type": "NameError",
  "hint": "可选：建议用户或维护者采取的操作"
}
```

| 字段 | App 用法 |
|------|----------|
| **`ok`** | 固定 `false` |
| **`status_code`** | 与 HTTP 状态码相同 |
| **`error`** | 机器可读错误码（见第 3 节） |
| **`message`** | **主文案**：弹窗 / Toast / 日志首选 |
| **`detail`** | 补充；可能是字符串、对象或校验 errors 数组 |
| **`path`** | 出错的 API 路径，便于对照本文档 |
| **`exception_type`** | 仅 **500** 未捕获异常时可能有（如 `ValueError`） |
| **`hint`** | 可选中文操作建议 |

**App 解析示例（Swift 伪代码）**：

```text
若 HTTP 状态码 >= 400：
  解析 body 为 JSON
  展示 text = json["message"] ?? json["detail"]（若为字符串）?? HTTP 状态行
  若有 json["hint"]，可作为副标题或「帮助」按钮
```

调试：Pi 上设置 `TELBOT_HTTP_DEBUG=1` 后重启 `telbot serve`，500 响应可能多 `traceback` 字段（勿对终端用户展示）。

---

## 2. HTTP 状态码一览

| 状态码 | 含义 | 常见 `error` |
|--------|------|----------------|
| **400** | 请求或业务参数不合法（地平、无意图、凌星规划失败等） | `bad_request`、`plan_or_input_error`、`below_horizon`、`no_intent`、`empty_text` |
| **422** | JSON 体不符合 schema（缺字段、类型错误） | `validation_error` |
| **404** | 资源不存在（如凌星计划文件） | `not_found` |
| **409** | 冲突（凌星任务已在运行） | `conflict`、`transit_run_already_active` |
| **503** | 服务不可用（无 INDI 工具、缺可选依赖、电调未配置） | `service_unavailable`、`indi_unavailable` |
| **500** | 服务端未捕获异常（代码缺陷、环境缺失） | `internal_error` |

**200** 表示 HTTP 层成功；部分接口体内仍有 `"ok": false`（如板解失败），须读业务字段。

---

## 3. 常见 `error` 代码表

| `error` | 典型 `message` / 场景 | 处理建议 |
|---------|----------------------|----------|
| `empty_text` | 文本为空 | 提示用户输入 |
| `no_intent` | 无法解析意图 | 换说法或检查 STT 转写 |
| `no_transcript` | 语音转写为空 | 检查麦克风 / `TELBOT_OPENAI_*` |
| `plan_or_input_error` | 凌星规划/输入错误（`ValueError`） | 见第 5 节凌星 |
| `below_horizon` | 目标低于地平 | 换目标或稍后 |
| `unknown_target` | 星表无此天体名 | 先 `catalog download` |
| `runtime_error` | CCD 未连接、设备名错误等 | 检查 `.env` 与 `telbot preflight` |
| `indi_unavailable` / `service_unavailable` | 本机无 `indi_setprop` | Pi 安装 `indi-bin`；`execute=true` 时必需 |
| `transit_run_already_active` | 已有凌星任务在跑 | 先 `POST /plan/transit/abort` 或等待结束 |
| `transit_run_thread_active` | HTTP 后台线程仍在跑凌星 | 同上 |
| `validation_error` | 请求 JSON 字段错误 | 对照 `VoiceIntentV1` / 请求体 |
| `internal_error` | 未预期服务端异常 | 展示 `message` + `hint`；升级 Telbot |

---

## 4. 按接口分类（App 常用）

### 4.1 `POST /listen/text`、`POST /text`

与 `telbot text "…" --apply` 同源。

| 情况 | 状态码 | `error` | `detail` 示例 |
|------|--------|---------|----------------|
| 空文本 | 400 | `empty_text` | `{"error":"empty_text","message":"文本为空"}` |
| NLU 无法识别 | 400 | `no_intent` | 含 `transcript`、`nlu_seconds` |
| STT/云端配置错误 | 400 | `runtime_error` | `message` 为 RuntimeError 文案 |
| **规划凌星** `plan_exoplanet_transit` | 400 | `plan_or_input_error` | `message`：无 pending、找不到行星、夜窗无交集等；`hint` 有中文引导 |
| 真机执行但无 INDI | 503 | `service_unavailable` | `indi_setprop not available` |
| 代码/环境缺陷 | 500 | `internal_error` | 见第 6 节 |

**成功**：`ok: true`，含 `intent`、`result`、`nl`（自然语言摘要）。

### 4.2 `POST /listen/audio`

| 情况 | 状态码 | `error` |
|------|--------|---------|
| 转写为空 | 400 | `no_transcript` |
| 无意图 | 400 | `no_intent` |
| 缺语音依赖 / API Key | 400/503 | `runtime_error` / `service_unavailable` |

### 4.3 `POST /intent`

Body：`VoiceIntentV1`（`version`、`action` 必填）。

| 情况 | 状态码 | 说明 |
|------|--------|------|
| 缺 `action` 等 | 422 | `validation_error`，`detail.errors` 为 Pydantic 列表 |
| `plan_exoplanet_transit` 失败 | 400 | `plan_or_input_error` |
| `execute=true` 无 INDI | 503 | 见上 |
| CCD 未连接（snap/platesolve） | 400 | `runtime_error`，message 含 CCD |

### 4.4 `GET /config/env`、`PATCH /config/env`

| 情况 | 状态码 | 说明 |
|------|--------|------|
| 请求非白名单键 | 400 | `message` 说明不允许的 `TELBOT_*` 键 |
| 写入失败 | 400 | 路径权限等 |

### 4.5 凌星 `GET/POST /plan/transit/*`

| 路径 | 情况 | 状态码 | `error` / 说明 |
|------|------|--------|----------------|
| `POST /plan/transit/run` | 已有会话在跑 | 409 | `transit_run_already_active`，`detail` 含 `session` |
| `POST /plan/transit/run` | 计划文件不存在 | 404 | `message` 为文件路径说明 |
| `POST /plan/transit/run` | `on_fail` 非法 | 400 | 须 `abort\|continue\|park` |
| `POST /plan/transit/run` | 规划配置无效 | 400 | `validate_planning_settings` |
| `GET /plan/transit/ingress-precheck` | 无预检记录 | 200 | `precheck: null`（非错误） |

规划本身经 **`/listen/text` → plan_exoplanet_transit** 时，**不需要**设备已连接；失败多为 **400** `plan_or_input_error`，不是 500。

### 4.6 `POST /goto`、`/camera/snap`、`/platesolve` 等真机接口

`execute=true` 且无 `indi_setprop` → **503**。地平以下 → **400** `below_horizon`。

---

## 5. 凌星规划相关错误（高频）

用户说「规划第 2 个凌星」「今晚观测 WASP-12 b 凌星」等 → 意图 **`plan_exoplanet_transit`**。

| `message` 关键词（中文） | 原因 | App 建议文案 |
|-------------------------|------|--------------|
| 无 pending / 已过期 | 未先查凌星列表或超过 TTL | 请先查询今晚凌星，再规划 |
| 未找到行星 / 今晚观测窗内 | 名称错误或今夜不可见 | 换目标或重新拉列表 |
| 夜窗无交集 | 凌食时间与天文夜不重叠 | 换目标或调整观测地 |
| 未配置经纬度 | `TELBOT_LATITUDE/LONGITUDE` | 在 App 默认参数中设置观测地 |

**不需要**赤道仪/CCD 在线即可规划；设备名取自 `.env` 默认值（见 `TRANSIT_OBSERVING_STRATEGY.md`）。

---

## 6. HTTP 500 `internal_error` 常见原因（历史问题）

以下为真机/现场曾导致 **仅显示 Internal Server Error** 的缺陷；升级后应返回 JSON `message`/`hint`。

| `exception_type` | 典型 `message` | 修复 |
|------------------|----------------|------|
| `NameError` | `name 'plans_dir' is not defined` | 升级 Telbot（已修：导入 `plans_dir`） |
| `ModuleNotFoundError` | `No module named 'astroplan'` | `pip install -e ".[exoplanets]"` |
| `ImportError` | platesolve / astropy 相关 | `pip install -e ".[platesolve]"` |
| `ConnectionError` | NASA / 云端 STT | 检查 Pi 网络与 API Key |
| 其它 | 见 `message` 与 Pi 上 `telbot serve` 日志 | 向维护者反馈 `path`+JSON |

---

## 7. 成功与业务失败（非 HTTP 错误）

- **HTTP 200** 且 `result.ok === false`：意图执行失败（如板解失败、GOTO 被拒），读 `result.message` 或 `nl.text`。
- **凌星预检**：`GET /plan/transit/ingress-precheck` 中 `capture_ok === false` 时读 `user_alert`（非 HTTP 错误），见 `TRANSIT_OBSERVING_STRATEGY.md` §9.1。

---

## 8. 相关源码

| 文件 | 作用 |
|------|------|
| `src/telbot/http_errors.py` | 错误信封、`hint` 推断 |
| `src/telbot/http_app.py` | 路由与 `HTTPException` |
| `tests/test_http_errors.py` | 信封与 500 处理单测 |

OpenAPI：浏览器访问 `http://<pi>:8765/docs`（`telbot serve` 运行时）。

---

*文档版本：2026-06-03，随结构化 HTTP 错误响应引入。*
