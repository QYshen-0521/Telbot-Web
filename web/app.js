const state = {
  execute: false,
  health: null,
  messages: [],
  activeTab: "chat",
  mediaRecorder: null,
  audioChunks: [],
  envValues: {},
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const el = {
  healthSummary: $("#healthSummary"),
  refreshHealth: $("#refreshHealth"),
  executeToggle: $("#executeToggle"),
  abortButton: $("#abortButton"),
  modeBadge: $("#modeBadge"),
  pageTitle: $("#pageTitle"),
  messages: $("#messages"),
  composer: $("#composer"),
  promptInput: $("#promptInput"),
  recordButton: $("#recordButton"),
  lastIntent: $("#lastIntent"),
  openHealthJson: $("#openHealthJson"),
  snapButton: $("#snapButton"),
  singleExposure: $("#singleExposure"),
  loadSnapPreview: $("#loadSnapPreview"),
  snapResult: $("#snapResult"),
  snapPreviewBox: $("#snapPreviewBox"),
  liveStart: $("#liveStart"),
  liveStop: $("#liveStop"),
  liveStatus: $("#liveStatus"),
  liveDuration: $("#liveDuration"),
  liveExposure: $("#liveExposure"),
  liveResult: $("#liveResult"),
  calStart: $("#calStart"),
  calStop: $("#calStop"),
  calKind: $("#calKind"),
  calCount: $("#calCount"),
  calExposure: $("#calExposure"),
  calResult: $("#calResult"),
  deviceRefresh: $("#deviceRefresh"),
  deviceCards: $("#deviceCards"),
  usbRefresh: $("#usbRefresh"),
  usbResult: $("#usbResult"),
  focuserRefresh: $("#focuserRefresh"),
  focuserPosition: $("#focuserPosition"),
  focuserMove: $("#focuserMove"),
  focuserResult: $("#focuserResult"),
  filterRefresh: $("#filterRefresh"),
  filterResult: $("#filterResult"),
  transitStatus: $("#transitStatus"),
  transitRun: $("#transitRun"),
  transitAbort: $("#transitAbort"),
  transitPlanPath: $("#transitPlanPath"),
  transitResult: $("#transitResult"),
  envLoad: $("#envLoad"),
  envSave: $("#envSave"),
  envFields: $("#envFields"),
  confirmDialog: $("#confirmDialog"),
  confirmText: $("#confirmText"),
  cancelConfirm: $("#cancelConfirm"),
  acceptConfirm: $("#acceptConfirm"),
  jsonDialog: $("#jsonDialog"),
  jsonDialogBody: $("#jsonDialogBody"),
  closeJsonDialog: $("#closeJsonDialog"),
};

const envKeys = [
  "TELBOT_INDI_HOST",
  "TELBOT_INDI_PORT",
  "TELBOT_INDI_DEVICE",
  "TELBOT_INDI_CCD_DEVICE",
  "TELBOT_INDI_CFW_DEVICE",
  "TELBOT_INDI_FOCUSER_DEVICE",
  "TELBOT_LATITUDE",
  "TELBOT_LONGITUDE",
  "TELBOT_ELEVATION_M",
  "TELBOT_PLAN_TIMEZONE",
  "TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS",
  "TELBOT_MIN_ALTITUDE_DEG",
  "TELBOT_PLAN_DEFAULT_EXPOSURE_SECONDS",
  "TELBOT_EXPOSE_LOOP_OVERHEAD_SECONDS",
  "TELBOT_INDI_GETPROP_TIMEOUT",
  "TELBOT_PLATESOLVE_TIMEOUT_S",
];

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function asJson(data) {
  return JSON.stringify(data, null, 2);
}

function setResult(node, data, title = "") {
  if (!node) return;
  if (typeof data === "string") {
    node.textContent = data;
    return;
  }
  node.innerHTML = "";
  if (title) {
    const p = document.createElement("p");
    p.textContent = title;
    node.appendChild(p);
  }
  const pre = document.createElement("pre");
  pre.textContent = asJson(data);
  node.appendChild(pre);
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const response = await fetch(path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(extractError(data) || `HTTP ${response.status}`);
  }
  return data;
}

function extractError(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  if (data.message) return data.message;
  if (data.hint) return data.hint;
  if (data.detail?.message) return data.detail.message;
  if (data.error) return data.error;
  return asJson(data);
}

function isNoIntentError(error) {
  const msg = String(error?.message || "");
  return msg.includes("no_intent") || msg.includes('"error":"no_intent"') || msg.includes("无法识别");
}

function requireConfirm(action) {
  if (!state.execute) return Promise.resolve(true);
  return new Promise((resolve) => {
    el.confirmText.textContent =
      `${action} 会真实控制设备。请确认镜筒周围无障碍、线缆安全、设备已连接，且没有 Ekos 等其他软件同时控制同一设备。`;
    const done = (value) => {
      el.acceptConfirm.onclick = null;
      el.cancelConfirm.onclick = null;
      el.confirmDialog.close();
      resolve(value);
    };
    el.acceptConfirm.onclick = () => done(true);
    el.cancelConfirm.onclick = () => done(false);
    el.confirmDialog.showModal();
  });
}

function showJson(data) {
  el.jsonDialogBody.textContent = asJson(data);
  el.jsonDialog.showModal();
}

function addMessage(message) {
  const item = { id: uid(), role: "assistant", text: "", createdAt: Date.now(), ...message };
  state.messages.push(item);
  renderMessages();
  return item.id;
}

function updateMessage(id, patch) {
  const index = state.messages.findIndex((m) => m.id === id);
  if (index < 0) return;
  state.messages[index] = { ...state.messages[index], ...patch };
  renderMessages();
}

function renderMessages() {
  el.messages.innerHTML = "";
  for (const msg of state.messages) {
    const wrap = document.createElement("article");
    wrap.className = `message ${msg.role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = msg.text || "";
    wrap.appendChild(bubble);
    if (msg.payload) wrap.appendChild(payloadCard(msg.payload));
    if (msg.imageUrl) {
      const img = document.createElement("img");
      img.alt = "照片预览";
      img.src = msg.imageUrl;
      wrap.appendChild(img);
    }
    el.messages.appendChild(wrap);
  }
  el.messages.scrollTop = el.messages.scrollHeight;
}

function payloadCard(payload) {
  const card = document.createElement("section");
  card.className = "meta-card";
  const result = payload.result || payload;
  const intent = payload.intent || {};
  const rows = [
    ["类型", payload.mode === "qa" ? "问答" : intent.action || result.action || "-"],
    ["主题/目标", payload.title || intent.target || result.device || result.resolved?.label || "-"],
    ["模式", result.dry_run === false || payload.execute === true ? "真机" : "干跑"],
    ["状态", payload.ok === false || result.ok === false ? "失败" : "成功/已返回"],
  ];
  const grid = document.createElement("div");
  grid.className = "meta-grid";
  for (const [label, value] of rows) {
    const item = document.createElement("div");
    item.className = "meta-item";
    item.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    grid.appendChild(item);
  }
  card.appendChild(grid);
  const details = document.createElement("details");
  details.innerHTML = `<summary>查看原始 JSON</summary><pre>${escapeHtml(asJson(payload))}</pre>`;
  card.appendChild(details);
  return card;
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function describeIntent(payload) {
  const intent = payload.intent;
  if (!intent) return "我没有识别到明确意图。";
  const parts = [`我理解为 ${intent.action}`];
  if (intent.target) parts.push(`目标：${intent.target}`);
  if (intent.exposure_seconds) parts.push(`曝光：${intent.exposure_seconds} 秒`);
  if (intent.nudge_direction) parts.push(`方向：${intent.nudge_direction}`);
  return parts.join("，") + "。";
}

function responseText(payload) {
  if (payload.nl_simple) return payload.nl_simple;
  if (typeof payload.nl === "string") return payload.nl;
  if (payload.result?.message) return payload.result.message;
  if (payload.result?.ok === false) return "执行没有成功，请查看详细 JSON。";
  return "请求已返回。";
}

function isLikelyQuestion(text) {
  const t = text.trim().toLowerCase();
  if (!t) return false;
  const questionHints = [
    "是什么",
    "什么是",
    "为什么",
    "怎么",
    "如何",
    "解释",
    "区别",
    "意思",
    "介绍",
    "讲讲",
    "告诉我",
    "能看到",
    "能拍到",
    "适合拍",
    "怎么拍",
    "曝光多久",
    "有什么用",
    "?",
    "？",
  ];
  const astronomyHints = [
    "telbot",
    "indi",
    "赤道仪",
    "望远镜",
    "相机",
    "曝光",
    "拍摄",
    "天文",
    "行星",
    "恒星",
    "星云",
    "星系",
    "星团",
    "深空",
    "月亮",
    "月球",
    "太阳",
    "木星",
    "火星",
    "土星",
    "金星",
    "水星",
    "天王星",
    "海王星",
    "m31",
    "m42",
    "ngc",
    "ic",
    "fits",
    "plate",
    "solve",
    "板解",
    "校准帧",
    "暗场",
    "平场",
    "偏置",
    "叠加",
    "滤镜",
    "对焦",
    "凌星",
  ];
  const commandHints = [
    "指向",
    "对准",
    "goto",
    "归位",
    "停车",
    "急停",
    "停止",
    "连接",
    "解除停车",
    "切换",
    "移动",
    "检查设备",
  ];
  const asksLikeQuestion = questionHints.some((hint) => t.includes(hint));
  const aboutAstronomy = astronomyHints.some((hint) => t.includes(hint));
  const asksNotCommand = !commandHints.some((hint) => t.includes(hint));
  return asksNotCommand && (asksLikeQuestion || (aboutAstronomy && t.includes("吗")));
}

async function askQuestion(command, pendingId) {
  const qa = await api("/chat", {
    method: "POST",
    body: JSON.stringify({ text: command }),
  });
  updateMessage(pendingId, {
    text: `${qa.title || "问答"}\n${qa.answer || "我暂时无法回答这个问题。"}`,
    payload: qa,
  });
  el.lastIntent.innerHTML = "";
  el.lastIntent.appendChild(payloadCard(qa));
}

async function sendTextCommand(text) {
  const command = text.trim();
  if (!command) return;
  addMessage({ role: "user", text: command });

  if (isLikelyQuestion(command)) {
    const pending = addMessage({ text: "正在整理回答..." });
    try {
      await askQuestion(command, pending);
    } catch (error) {
      updateMessage(pending, { role: "system", text: `问答失败：${error.message}` });
    }
    return;
  }

  if (!(await requireConfirm(`发送「${command}」`))) return;
  const pending = addMessage({ text: "正在听取指令并整理回复..." });
  try {
    const payload = await api(`/text?execute=${state.execute}&no_semantic=true&no_llm=true`, {
      method: "POST",
      body: JSON.stringify({ text: command }),
    });
    updateMessage(pending, { text: `${describeIntent(payload)}\n${responseText(payload)}`.trim(), payload });
    el.lastIntent.innerHTML = "";
    el.lastIntent.appendChild(payloadCard(payload));
    await refreshHealth();
  } catch (error) {
    if (isNoIntentError(error)) {
      try {
        await askQuestion(command, pending);
      } catch (qaError) {
        updateMessage(pending, {
          role: "system",
          text: `命令未识别，问答也失败：${qaError.message}`,
        });
      }
    } else {
      updateMessage(pending, { role: "system", text: `命令执行失败：${error.message}` });
    }
  }
}

async function refreshHealth(showToast = false) {
  try {
    const health = await api("/health");
    state.health = health;
    renderHealth(health);
    renderDeviceCards(health);
    if (showToast) addMessage({ role: "system", text: "设备状态已刷新。", payload: health });
  } catch (error) {
    el.healthSummary.innerHTML = `<div class="status-line"><span>API</span><strong class="bad">${escapeHtml(error.message)}</strong></div>`;
  }
}

function renderHealth(health) {
  const rows = [
    ["API", health.status === "ok" ? "在线" : String(health.status), "ok"],
    ["版本", health.version || "未知", ""],
    ["INDI", health.indi_tools ? "可用" : "不可用", health.indi_tools ? "ok" : "warn"],
    ["赤道仪", deviceLine(health.mount), deviceCls(health.mount)],
    ["相机", deviceLine(health.camera), deviceCls(health.camera)],
    ["电调", deviceLine(health.focuser), deviceCls(health.focuser)],
  ];
  el.healthSummary.innerHTML = rows
    .map(([label, value, cls]) => `<div class="status-line"><span>${label}</span><strong class="${cls}">${escapeHtml(value)}</strong></div>`)
    .join("");
}

function deviceLine(device) {
  if (!device) return "未知";
  const name = device.name || device.device || "设备";
  if (device.connected === true) return `${name} 已连接`;
  if (device.connected === false) return `${name} 未连接`;
  return name;
}

function deviceCls(device) {
  if (!device) return "muted";
  if (device.connected === true) return "ok";
  if (device.connected === false) return "warn";
  return "muted";
}

function renderDeviceCards(health) {
  const devices = [
    ["Telbot", health.status === "ok" ? "在线" : "异常", `版本 ${health.version || "未知"}`],
    ["INDI 工具", health.indi_tools ? "可用" : "不可用", "indi_getprop / indi_setprop"],
    ["赤道仪", deviceLine(health.mount), "Mount"],
    ["相机", deviceLine(health.camera), "CCD"],
    ["电调", deviceLine(health.focuser), "Focuser"],
  ];
  el.deviceCards.innerHTML = devices
    .map(([name, status, desc]) => `<div class="device-card"><h3>${escapeHtml(name)}</h3><p>${escapeHtml(status)}</p><p>${escapeHtml(desc)}</p></div>`)
    .join("");
}

async function snapPhoto() {
  const seconds = Number(el.singleExposure.value);
  if (!Number.isFinite(seconds) || seconds <= 0) return setResult(el.snapResult, "曝光秒数需要大于 0。");
  if (!(await requireConfirm(`拍摄 ${seconds} 秒照片`))) return;
  setResult(el.snapResult, "正在请求相机曝光...");
  try {
    const payload = await api(`/camera/snap?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify({ exposure_seconds: seconds }),
    });
    setResult(el.snapResult, payload, "拍照请求已返回。");
    addMessage({ role: "user", text: `拍摄 ${seconds} 秒照片` });
    const imageUrl = state.execute && (payload.preview_ok || payload.preview_url) ? `/camera/snap/preview?t=${Date.now()}` : "";
    addMessage({ text: imageUrl ? "拍照完成，预览如下。" : "拍照请求已返回。干跑模式不会产生真实照片。", payload, imageUrl });
    if (imageUrl) loadSnapPreview();
  } catch (error) {
    setResult(el.snapResult, `拍照失败：${error.message}`);
  }
}

async function loadSnapPreview() {
  el.snapPreviewBox.textContent = "正在加载预览...";
  try {
    const response = await fetch(`/camera/snap/preview?t=${Date.now()}`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(extractError(data) || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    el.snapPreviewBox.innerHTML = "";
    const img = document.createElement("img");
    img.alt = "最近一次拍照预览";
    img.src = url;
    el.snapPreviewBox.appendChild(img);
  } catch (error) {
    el.snapPreviewBox.textContent = `暂无预览：${error.message}`;
  }
}

async function liveStackStart() {
  if (!(await requireConfirm("开始边拍边叠"))) return;
  const duration = Number(el.liveDuration.value);
  const exposure = Number(el.liveExposure.value);
  try {
    const payload = await api(`/camera/live-stack/start?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify({ duration_seconds: duration, exposure_seconds: exposure }),
    });
    setResult(el.liveResult, payload, "边拍边叠已请求启动。");
  } catch (error) {
    setResult(el.liveResult, `启动失败：${error.message}`);
  }
}

async function liveStackStop() {
  try {
    const payload = await api("/camera/live-stack/stop", { method: "POST" });
    setResult(el.liveResult, payload, "已请求停止边拍边叠。");
  } catch (error) {
    setResult(el.liveResult, `停止失败：${error.message}`);
  }
}

async function liveStackStatus() {
  try {
    const payload = await api("/camera/live-stack/status");
    setResult(el.liveResult, payload, "边拍边叠状态。");
  } catch (error) {
    setResult(el.liveResult, `读取失败：${error.message}`);
  }
}

async function calibrationStart() {
  if (!(await requireConfirm("开始校准拍摄"))) return;
  const kind = el.calKind.value;
  const body = {
    count: Number(el.calCount.value),
    exposure_seconds: Number(el.calExposure.value),
  };
  try {
    const payload = await api(`/camera/cal/${kind}?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setResult(el.calResult, payload, "校准拍摄请求已返回。");
  } catch (error) {
    setResult(el.calResult, `校准失败：${error.message}`);
  }
}

async function calibrationStop() {
  try {
    const payload = await api("/camera/cal/stop", { method: "POST" });
    setResult(el.calResult, payload, "已请求停止校准。");
  } catch (error) {
    setResult(el.calResult, `停止失败：${error.message}`);
  }
}

async function abortMount() {
  if (!(await requireConfirm("急停 / Abort"))) return;
  try {
    const payload = await api(`/abort?execute=${state.execute}`, { method: "POST" });
    addMessage({ role: "user", text: "急停 / Abort" });
    addMessage({ text: "急停请求已返回。", payload });
    await refreshHealth();
  } catch (error) {
    addMessage({ role: "system", text: `急停失败：${error.message}` });
  }
}

async function readUsb() {
  try {
    const payload = await api("/usb/devices");
    setResult(el.usbResult, payload, "USB 设备。");
  } catch (error) {
    setResult(el.usbResult, `USB 读取失败：${error.message}`);
  }
}

async function readFocuser() {
  try {
    const payload = await api("/focuser/position");
    setResult(el.focuserResult, payload, "电调位置。");
  } catch (error) {
    setResult(el.focuserResult, `电调读取失败：${error.message}`);
  }
}

async function moveFocuser() {
  const position = Number(el.focuserPosition.value);
  if (!Number.isFinite(position) || position < 0) return setResult(el.focuserResult, "请输入合法电调位置。");
  if (!(await requireConfirm(`移动电调到 ${position}`))) return;
  try {
    const payload = await api(`/focuser/abs?position=${encodeURIComponent(position)}&execute=${state.execute}`, { method: "POST" });
    setResult(el.focuserResult, payload, "电调移动请求已返回。");
  } catch (error) {
    setResult(el.focuserResult, `移动失败：${error.message}`);
  }
}

async function readFilter() {
  try {
    const [slots, status] = await Promise.all([api("/filter/slots"), api("/filter/status")]);
    setResult(el.filterResult, { slots, status }, "滤镜轮。");
  } catch (error) {
    setResult(el.filterResult, `滤镜读取失败：${error.message}`);
  }
}

async function transitStatus() {
  try {
    const payload = await api("/plan/transit/status");
    setResult(el.transitResult, payload, "凌星计划状态。");
  } catch (error) {
    setResult(el.transitResult, `读取失败：${error.message}`);
  }
}

async function transitRun() {
  if (!(await requireConfirm("启动凌星计划"))) return;
  const params = new URLSearchParams({ execute: String(state.execute), force: "true" });
  const planPath = el.transitPlanPath.value.trim();
  if (planPath) params.set("plan_path", planPath);
  try {
    const payload = await api(`/plan/transit/run?${params}`, { method: "POST" });
    setResult(el.transitResult, payload, "凌星计划已请求启动。");
  } catch (error) {
    setResult(el.transitResult, `启动失败：${error.message}`);
  }
}

async function transitAbort() {
  if (!(await requireConfirm("中止凌星计划"))) return;
  try {
    const payload = await api(`/plan/transit/abort?execute=${state.execute}&reason=web%20user%20abort`, { method: "POST" });
    setResult(el.transitResult, payload, "已请求中止凌星计划。");
  } catch (error) {
    setResult(el.transitResult, `中止失败：${error.message}`);
  }
}

async function loadEnv() {
  try {
    const query = envKeys.map((k) => `keys=${encodeURIComponent(k)}`).join("&");
    const payload = await api(`/config/env?${query}`);
    state.envValues = payload.values || {};
    renderEnvFields();
  } catch (error) {
    el.envFields.innerHTML = `<div class="result-box">读取参数失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderEnvFields() {
  el.envFields.innerHTML = "";
  for (const key of envKeys) {
    const row = document.createElement("div");
    row.className = "env-row";
    row.innerHTML = `<label for="env-${key}">${key}</label><input id="env-${key}" data-env-key="${key}" value="${escapeHtml(state.envValues[key] || "")}" />`;
    el.envFields.appendChild(row);
  }
}

async function saveEnv() {
  const updates = {};
  $$("[data-env-key]").forEach((input) => {
    const key = input.dataset.envKey;
    const value = input.value;
    if ((state.envValues[key] || "") !== value) updates[key] = value;
  });
  if (!Object.keys(updates).length) return showJson({ ok: true, message: "没有修改。" });
  try {
    const payload = await api("/config/env", {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    });
    state.envValues = payload.values || state.envValues;
    showJson(payload);
    renderEnvFields();
    await refreshHealth();
  } catch (error) {
    showJson({ ok: false, error: error.message });
  }
}

async function toggleRecording() {
  if (state.mediaRecorder?.state === "recording") {
    state.mediaRecorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    addMessage({ role: "system", text: "当前浏览器不支持录音，请先使用文字输入。" });
    return;
  }
  if (!(await requireConfirm("发送语音命令"))) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.audioChunks = [];
    state.mediaRecorder = new MediaRecorder(stream);
    state.mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) state.audioChunks.push(event.data);
    };
    state.mediaRecorder.onstop = () => {
      el.recordButton.classList.remove("recording");
      stream.getTracks().forEach((track) => track.stop());
      sendAudio(new Blob(state.audioChunks, { type: state.mediaRecorder.mimeType || "audio/webm" }));
    };
    el.recordButton.classList.add("recording");
    addMessage({ role: "system", text: "录音中，再点一次红点停止并发送。" });
    state.mediaRecorder.start();
  } catch (error) {
    addMessage({ role: "system", text: `无法开始录音：${error.message}` });
  }
}

async function sendAudio(blob) {
  addMessage({ role: "user", text: "语音指令" });
  const pending = addMessage({ text: "正在转写语音并整理回复..." });
  const form = new FormData();
  form.append("file", blob, "telbot-command.webm");
  try {
    const payload = await api(`/listen/audio?execute=${state.execute}&no_semantic=true&no_llm=true`, { method: "POST", body: form });
    updateMessage(pending, {
      text: `你说的是：「${payload.transcript || "未返回文字"}」\n${describeIntent(payload)}\n${responseText(payload)}`,
      payload,
    });
  } catch (error) {
    updateMessage(pending, { role: "system", text: `语音命令失败：${error.message}` });
  }
}

function switchTab(tab) {
  state.activeTab = tab;
  $$(".nav-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab-page").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));
  const titles = { chat: "对话控制", capture: "拍摄", devices: "设备", plan: "计划", settings: "设置" };
  el.pageTitle.textContent = titles[tab] || "Telbot";
}

function bindEvents() {
  el.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = el.promptInput.value;
    el.promptInput.value = "";
    el.promptInput.style.height = "auto";
    sendTextCommand(text);
  });
  el.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      el.composer.requestSubmit();
    }
  });
  el.promptInput.addEventListener("input", () => {
    el.promptInput.style.height = "auto";
    el.promptInput.style.height = `${Math.min(el.promptInput.scrollHeight, 150)}px`;
  });
  el.executeToggle.addEventListener("change", async () => {
    if (el.executeToggle.checked && !(await requireConfirm("打开真机执行模式"))) {
      el.executeToggle.checked = false;
      return;
    }
    state.execute = el.executeToggle.checked;
    el.modeBadge.textContent = state.execute ? "真机模式" : "干跑模式";
    el.modeBadge.classList.toggle("live", state.execute);
    addMessage({ role: "system", text: state.execute ? "真机执行已打开。危险操作会继续二次确认。" : "已切回干跑模式。" });
  });
  $$(".nav-tab").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $$(".quick-command").forEach((b) => b.addEventListener("click", () => {
    el.promptInput.value = b.dataset.command || "";
    el.promptInput.focus();
  }));
  el.refreshHealth.addEventListener("click", () => refreshHealth(true));
  el.deviceRefresh.addEventListener("click", () => refreshHealth(true));
  el.abortButton.addEventListener("click", abortMount);
  el.openHealthJson.addEventListener("click", () => showJson(state.health || { message: "尚无状态" }));
  el.closeJsonDialog.addEventListener("click", () => el.jsonDialog.close());
  el.recordButton.addEventListener("click", toggleRecording);
  el.snapButton.addEventListener("click", snapPhoto);
  el.loadSnapPreview.addEventListener("click", loadSnapPreview);
  el.liveStart.addEventListener("click", liveStackStart);
  el.liveStop.addEventListener("click", liveStackStop);
  el.liveStatus.addEventListener("click", liveStackStatus);
  el.calStart.addEventListener("click", calibrationStart);
  el.calStop.addEventListener("click", calibrationStop);
  el.usbRefresh.addEventListener("click", readUsb);
  el.focuserRefresh.addEventListener("click", readFocuser);
  el.focuserMove.addEventListener("click", moveFocuser);
  el.filterRefresh.addEventListener("click", readFilter);
  el.transitStatus.addEventListener("click", transitStatus);
  el.transitRun.addEventListener("click", transitRun);
  el.transitAbort.addEventListener("click", transitAbort);
  el.envLoad.addEventListener("click", loadEnv);
  el.envSave.addEventListener("click", saveEnv);
}

function init() {
  bindEvents();
  addMessage({
    text: "你好，我是 Telbot 天文控制台。你可以像聊天一样输入“帮我指向木星”“拍5秒”“归位”“检查设备”，也可以问“M31怎么拍”“什么是INDI”。默认干跑，不会真实控制设备。",
  });
  refreshHealth();
  loadEnv();
}

init();
