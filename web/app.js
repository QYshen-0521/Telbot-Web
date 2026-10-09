const STORAGE_BASE = "telbot.apiBase";
const STORAGE_REMEMBER = "telbot.rememberApi";
const STORAGE_TUNNEL = "telbot.tunnelUrl";
const PROBE_TIMEOUT_MS = 2000;

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

const state = {
  connected: false,
  probing: false,
  apiBase: "",
  execute: false,
  health: null,
  notice: "",
  lastError: "",
  probeLog: [],
  checkedAt: null,
  messages: [],
  envValues: {},
  mediaRecorder: null,
  audioChunks: [],
  greeted: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const el = {
  statusPill: $("#statusPill"),
  modeBadge: $("#modeBadge"),
  overviewState: $("#overviewState"),
  apiBase: $("#apiBase"),
  rememberApi: $("#rememberApi"),
  redetect: $("#redetect"),
  connectionExplain: $("#connectionExplain"),
  mixedHint: $("#mixedHint"),
  usingBase: $("#usingBase"),
  checkedAt: $("#checkedAt"),
  healthSummary: $("#healthSummary"),
  openHealthJson: $("#openHealthJson"),
  probeLog: $("#probeLog"),
  lockBanner: $("#lockBanner"),
  onlineBanner: $("#onlineBanner"),
  controlFieldset: $("#controlFieldset"),
  executeToggle: $("#executeToggle"),
  abortButton: $("#abortButton"),
  messages: $("#messages"),
  composer: $("#composer"),
  promptInput: $("#promptInput"),
  recordButton: $("#recordButton"),
  lastIntent: $("#lastIntent"),
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

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function asJson(data) {
  return JSON.stringify(data, null, 2);
}

function normalizeBase(raw) {
  let value = String(raw || "").trim();
  if (!value || [".", "same", "relative", "origin"].includes(value)) return "";
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
  value = value.replace(/\/+$/, "").replace(/\/health$/i, "");
  return value;
}

function joinUrl(base, path) {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  if (!base) return suffix;
  return `${base}${suffix}`;
}

function isTunnelUrl(base) {
  if (!base || !/^https:\/\//i.test(base)) return false;
  try {
    const host = new URL(base).hostname;
    if (host === "localhost" || host === "127.0.0.1" || host.endsWith(".local")) return false;
    return true;
  } catch {
    return false;
  }
}

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

function storageRemove(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* private mode */
  }
}

function rememberedBase() {
  if (storageGet(STORAGE_REMEMBER) !== "1") return null;
  const value = storageGet(STORAGE_BASE);
  return value == null ? null : normalizeBase(value);
}

function savedTunnel() {
  if (storageGet(STORAGE_REMEMBER) !== "1") return "";
  return normalizeBase(storageGet(STORAGE_TUNNEL) || "");
}

function loadPrefs() {
  const remember = storageGet(STORAGE_REMEMBER) === "1";
  el.rememberApi.checked = remember;
  if (location.protocol === "https:") el.mixedHint.hidden = false;
}

function persistAfterDetect(successBase) {
  const remember = el.rememberApi.checked;
  if (!remember) {
    storageSet(STORAGE_REMEMBER, "0");
    storageRemove(STORAGE_BASE);
    storageRemove(STORAGE_TUNNEL);
    return;
  }
  storageSet(STORAGE_REMEMBER, "1");
  if (successBase !== null && successBase !== undefined) {
    storageSet(STORAGE_BASE, successBase);
    if (isTunnelUrl(successBase)) storageSet(STORAGE_TUNNEL, successBase);
  }
}

function buildCandidates(preferred) {
  const list = [];
  const add = (value) => {
    const base = normalizeBase(value);
    if (!list.includes(base)) list.push(base);
  };
  if (preferred !== undefined && preferred !== null && String(preferred).trim() !== "") add(preferred);
  add("");
  const remembered = rememberedBase();
  if (remembered !== null) add(remembered);
  const tunnel = savedTunnel();
  if (tunnel) add(tunnel);
  add("http://telbot.local:8765");
  add("http://127.0.0.1:8765");
  return list;
}

function readQueryApi() {
  const params = new URLSearchParams(location.search);
  if (!params.has("api")) return { kind: "auto" };
  const raw = (params.get("api") || "").trim();
  if (["", ".", "same", "relative", "origin"].includes(raw)) return { kind: "relative-only" };
  return { kind: "url", value: normalizeBase(raw) };
}

async function probe(base) {
  const label = base || "同源 /health";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(joinUrl(base, "/health?quick=1"), {
      method: "GET",
      cache: "no-store",
      mode: "cors",
      credentials: "omit",
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("json")) data = await response.json();
    else {
      const text = await response.text();
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!response.ok || !data || typeof data !== "object" || (data.status && data.status !== "ok")) {
      return { ok: false, label, base, error: `HTTP ${response.status}` };
    }
    return { ok: true, label, base, health: data };
  } catch (error) {
    const aborted = error && error.name === "AbortError";
    return { ok: false, label, base, error: aborted ? "超时" : "无法连接" };
  } finally {
    clearTimeout(timer);
  }
}

function formatClock(date) {
  if (!date) return "尚未检测";
  return `上次检测 ${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date)}`;
}

function renderProbeLog() {
  el.probeLog.replaceChildren();
  if (!state.probeLog.length) {
    const item = document.createElement("li");
    item.textContent = state.probing ? "正在检测…" : "打开页面后会自动检测。";
    el.probeLog.appendChild(item);
    return;
  }
  for (const entry of state.probeLog) {
    const item = document.createElement("li");
    item.textContent = entry.ok ? `${entry.label}：成功` : `${entry.label}：${entry.error || "失败"}`;
    el.probeLog.appendChild(item);
  }
}

function deviceLine(device) {
  if (!device) return "未报告";
  const name = device.name || device.device || device.label || "设备";
  if (device.connected === true) return `${name} · 已连接`;
  if (device.connected === false) return `${name} · 未连接`;
  return String(name);
}

function deviceClass(device) {
  if (!device) return "";
  if (device.connected === true) return "ok";
  if (device.connected === false) return "warn-text";
  return "";
}

function renderHealth() {
  const health = state.health;
  el.healthSummary.replaceChildren();
  el.openHealthJson.disabled = !health;
  if (!health) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = "健康检查";
    const value = document.createElement("dd");
    value.textContent = "尚无数据";
    row.append(term, value);
    el.healthSummary.appendChild(row);
    renderDeviceCards(null);
    return;
  }
  const rows = [
    ["版本", health.version || "未知", ""],
    ["INDI", health.indi_tools ? "可用" : "不可用", health.indi_tools ? "ok" : "warn-text"],
    ["赤道仪", deviceLine(health.mount), deviceClass(health.mount)],
    ["相机", deviceLine(health.camera), deviceClass(health.camera)],
    ["电调", deviceLine(health.focuser), deviceClass(health.focuser)],
    ["滤镜轮", deviceLine(health.filter_wheel || health.filterwheel), deviceClass(health.filter_wheel || health.filterwheel)],
  ];
  for (const [label, value, cls] of rows) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const cell = document.createElement("dd");
    cell.textContent = value;
    if (cls) cell.className = cls;
    row.append(term, cell);
    el.healthSummary.appendChild(row);
  }
  renderDeviceCards(health);
}

function renderDeviceCards(health) {
  el.deviceCards.replaceChildren();
  if (!health) {
    const empty = document.createElement("p");
    empty.className = "empty-hint";
    empty.textContent = "连接后显示赤道仪、相机和电调。";
    el.deviceCards.appendChild(empty);
    return;
  }
  const devices = [
    ["Telbot", health.status === "ok" ? "在线" : String(health.status || "未知"), `版本 ${health.version || "未知"}`],
    ["INDI 工具", health.indi_tools ? "可用" : "不可用", "indi_getprop / indi_setprop"],
    ["赤道仪", deviceLine(health.mount), "Mount"],
    ["相机", deviceLine(health.camera), "CCD"],
    ["电调", deviceLine(health.focuser), "Focuser"],
    ["滤镜轮", deviceLine(health.filter_wheel || health.filterwheel), "CFW"],
  ];
  for (const [name, status, desc] of devices) {
    const card = document.createElement("article");
    card.className = "device-card";
    const title = document.createElement("h3");
    title.textContent = name;
    const line = document.createElement("p");
    line.textContent = status;
    const note = document.createElement("p");
    note.textContent = desc;
    card.append(title, line, note);
    el.deviceCards.appendChild(card);
  }
}

function renderConnection() {
  const online = state.connected;
  document.body.dataset.connected = online ? "true" : "false";
  el.controlFieldset.disabled = !online;
  el.statusPill.textContent = online ? "设备已连接" : "设备未连接";
  el.statusPill.classList.toggle("online", online);
  el.statusPill.classList.toggle("offline", !online);
  el.lockBanner.hidden = online;
  el.onlineBanner.hidden = !online;
  el.redetect.disabled = state.probing;
  el.redetect.textContent = state.probing ? "正在检测…" : "重新检测";
  el.checkedAt.textContent = state.probing ? "正在检测…" : formatClock(state.checkedAt);

  if (!online) {
    state.execute = false;
    el.executeToggle.checked = false;
  }
  const live = online && state.execute;
  el.modeBadge.textContent = !online ? "浏览模式" : live ? "真机模式" : "干跑模式";
  el.modeBadge.classList.toggle("live", live);

  if (state.probing && !online) {
    el.connectionExplain.textContent = "正在检测 Telbot 后端。在此之前保持浏览模式，控制不会发出。";
  } else if (!online) {
    el.connectionExplain.textContent =
      "设备未连接。介绍、原理、安全和导览可以继续看。指向、拍摄、边拍边叠、校准、设备操作、凌星运行、参数保存和语音发送都已停用。GET /health 成功后，这些控制才会打开。";
  } else {
    const where = state.apiBase || "与页面同源";
    el.connectionExplain.textContent = `设备已连接，正在使用 ${where}。控制已启用，默认干跑。打开真机执行后，每次真实操作都会再确认。${state.notice || ""}`;
  }
  el.overviewState.textContent = online
    ? "设备已连接。控制台里的操作已经启用，当前仍默认干跑。"
    : "设备未连接。你正在浏览模式。连接成功后，控制台里的指向、拍摄、叠图、参数保存、凌星运行和语音发送才会启用。";
  el.usingBase.textContent = online
    ? `正在使用：${state.apiBase || "与页面同源"}`
    : state.lastError
      ? state.lastError
      : "正在使用：尚未连接";
  renderProbeLog();
  renderHealth();
}

function markDisconnected(message) {
  state.connected = false;
  state.health = null;
  state.execute = false;
  state.lastError = message || "与后端的连接中断。";
  state.notice = "";
  renderConnection();
}

async function detect(options = {}) {
  if (state.probing) return;
  state.probing = true;
  state.notice = "";
  state.probeLog = [];
  renderConnection();
  const candidates = options.onlyRelative ? [""] : buildCandidates(options.preferred);
  let winner = null;
  for (const base of candidates) {
    const result = await probe(base);
    state.probeLog.push(result);
    renderProbeLog();
    if (result.ok) {
      winner = result;
      break;
    }
  }
  state.probing = false;
  state.checkedAt = new Date();
  if (winner) {
    const typed = options.preferred ? normalizeBase(options.preferred) : "";
    state.connected = true;
    state.apiBase = winner.base;
    state.health = winner.health;
    state.lastError = "";
    state.notice = typed && typed !== winner.base ? ` 填写的地址没有应答，已改用 ${winner.base || "同源地址"}。` : "";
    el.apiBase.value = winner.base || "";
    persistAfterDetect(winner.base);
    renderConnection();
    greet();
    refreshFullHealth();
    loadEnv();
    return;
  }
  state.connected = false;
  state.health = null;
  state.execute = false;
  state.lastError = "没有探测到 Telbot 后端（GET /health 未成功）。";
  persistAfterDetect(null);
  renderConnection();
}

async function refreshFullHealth() {
  if (!state.connected) return;
  try {
    const health = await api("/health");
    state.health = health;
    renderHealth();
  } catch {
    renderHealth();
  }
}

function extractError(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  if (data.message) return data.message;
  if (data.hint) return data.hint;
  if (data.detail && data.detail.message) return data.detail.message;
  if (data.error) return String(data.error);
  return asJson(data);
}

async function api(path, options = {}) {
  if (!state.connected) throw new Error("设备未连接");
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  let response;
  try {
    response = await fetch(joinUrl(state.apiBase, path), {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
      cache: "no-store",
      mode: "cors",
      credentials: "omit",
    });
  } catch {
    markDisconnected("与后端的连接中断。");
    throw new Error("无法连接后端");
  }
  const contentType = response.headers.get("content-type") || "";
  let data;
  if (contentType.includes("application/json")) data = await response.json();
  else if (contentType.startsWith("text/")) data = await response.text();
  else data = null;
  if (!response.ok) throw new Error(extractError(data) || `HTTP ${response.status}`);
  return data;
}

function confirmDanger(action) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      if (el.confirmDialog.open) el.confirmDialog.close();
    };
    el.confirmText.textContent = `${action}。请确认镜筒周围无障碍、线缆安全，且没有其他软件同时控制同一设备。`;
    el.acceptConfirm.onclick = () => finish(true);
    el.cancelConfirm.onclick = () => finish(false);
    el.confirmDialog.onclose = () => finish(false);
    if (!el.confirmDialog.open) el.confirmDialog.showModal();
  });
}

function requireConfirm(action) {
  if (!state.execute) return Promise.resolve(true);
  return confirmDanger(action);
}

function showJson(data) {
  el.jsonDialogBody.textContent = asJson(data);
  if (!el.jsonDialog.open) el.jsonDialog.showModal();
}

function setResult(node, data, title = "") {
  if (!node) return;
  node.replaceChildren();
  if (typeof data === "string") {
    node.textContent = data;
    return;
  }
  if (title) {
    const p = document.createElement("p");
    p.textContent = title;
    node.appendChild(p);
  }
  const pre = document.createElement("pre");
  pre.textContent = asJson(data);
  node.appendChild(pre);
}

function addMessage(message) {
  const item = { id: uid(), role: "assistant", text: "", createdAt: Date.now(), ...message };
  state.messages.push(item);
  renderMessages();
  return item.id;
}

function updateMessage(id, patch) {
  const index = state.messages.findIndex((item) => item.id === id);
  if (index < 0) return;
  state.messages[index] = { ...state.messages[index], ...patch };
  renderMessages();
}

function renderMessages() {
  el.messages.replaceChildren();
  if (!state.messages.length) {
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = state.connected
      ? "后端已连接。输入指令，或点快捷命令填入句子。"
      : "设备未连接，对话还不能发送。连接后可以用中文下指令，也可以提天文问题。";
    el.messages.appendChild(hint);
    return;
  }
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
    ["主题/目标", payload.title || intent.target || result.device || (result.resolved && result.resolved.label) || "-"],
    ["模式", result.dry_run === false || payload.execute === true ? "真机" : "干跑"],
    ["状态", payload.ok === false || result.ok === false ? "失败" : "成功/已返回"],
  ];
  const grid = document.createElement("div");
  grid.className = "meta-grid";
  for (const [label, value] of rows) {
    const item = document.createElement("div");
    item.className = "meta-item";
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value == null || value === "" ? "-" : String(value);
    item.append(span, strong);
    grid.appendChild(item);
  }
  card.appendChild(grid);
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "查看原始 JSON";
  const pre = document.createElement("pre");
  pre.textContent = asJson(payload);
  details.append(summary, pre);
  card.appendChild(details);
  return card;
}

function describeIntent(payload) {
  const intent = payload.intent;
  if (!intent) return "我没有识别到明确意图。";
  const parts = [`我理解为 ${intent.action}`];
  if (intent.target) parts.push(`目标：${intent.target}`);
  if (intent.exposure_seconds) parts.push(`曝光：${intent.exposure_seconds} 秒`);
  if (intent.nudge_direction) parts.push(`方向：${intent.nudge_direction}`);
  return `${parts.join("，")}。`;
}

function responseText(payload) {
  if (payload.nl_simple) return payload.nl_simple;
  if (typeof payload.nl === "string") return payload.nl;
  if (payload.result && payload.result.message) return payload.result.message;
  if (payload.result && payload.result.ok === false) return "执行没有成功，请查看详细 JSON。";
  return "请求已返回。";
}

function isNoIntentError(error) {
  const msg = String(error && error.message ? error.message : "");
  return msg.includes("no_intent") || msg.includes('"error":"no_intent"') || msg.includes("无法识别");
}

function isLikelyQuestion(text) {
  const t = text.trim().toLowerCase();
  if (!t) return false;
  const questionHints = ["是什么", "什么是", "为什么", "怎么", "如何", "解释", "区别", "意思", "介绍", "讲讲", "告诉我", "能看到", "能拍到", "适合拍", "怎么拍", "曝光多久", "有什么用", "?", "？"];
  const astronomyHints = ["telbot", "indi", "赤道仪", "望远镜", "相机", "曝光", "拍摄", "天文", "行星", "恒星", "星云", "星系", "星团", "深空", "月亮", "月球", "太阳", "木星", "火星", "土星", "金星", "水星", "天王星", "海王星", "m31", "m42", "ngc", "ic", "fits", "plate", "solve", "板解", "校准帧", "暗场", "平场", "偏置", "叠加", "滤镜", "对焦", "凌星"];
  const commandHints = ["指向", "对准", "goto", "归位", "停车", "急停", "停止", "连接", "解除停车", "切换", "移动", "检查设备"];
  const asksLikeQuestion = questionHints.some((hint) => t.includes(hint));
  const aboutAstronomy = astronomyHints.some((hint) => t.includes(hint));
  const asksNotCommand = !commandHints.some((hint) => t.includes(hint));
  return asksNotCommand && (asksLikeQuestion || (aboutAstronomy && t.includes("吗")));
}

function greet() {
  if (state.greeted) return;
  state.greeted = true;
  addMessage({
    text: "后端已连接。默认是干跑，不会转动望远镜，也不会曝光。可以说「帮我指向木星」「拍5秒」「归位」，或问「什么是 INDI」。",
  });
}

async function askQuestion(command, pendingId) {
  const qa = await api("/chat", { method: "POST", body: JSON.stringify({ text: command }) });
  updateMessage(pendingId, {
    text: `${qa.title || "问答"}\n${qa.answer || "我暂时无法回答这个问题。"}`,
    payload: qa,
  });
  el.lastIntent.replaceChildren(payloadCard(qa));
}

async function sendTextCommand(text) {
  const command = text.trim();
  if (!command) return false;
  if (!state.connected) {
    addMessage({ role: "system", text: "设备未连接，这条指令没有发送。" });
    return false;
  }
  if (isLikelyQuestion(command)) {
    addMessage({ role: "user", text: command });
    const pending = addMessage({ text: "正在整理回答…" });
    try {
      await askQuestion(command, pending);
    } catch (error) {
      updateMessage(pending, { role: "system", text: `问答失败：${error.message}` });
    }
    return true;
  }
  if (!(await requireConfirm(`发送「${command}」`))) return false;
  addMessage({ role: "user", text: command });
  const pending = addMessage({ text: "正在听取指令并整理回复…" });
  try {
    const payload = await api(`/text?execute=${state.execute}&no_semantic=true&no_llm=true`, {
      method: "POST",
      body: JSON.stringify({ text: command }),
    });
    updateMessage(pending, { text: `${describeIntent(payload)}\n${responseText(payload)}`.trim(), payload });
    el.lastIntent.replaceChildren(payloadCard(payload));
    await refreshFullHealth();
  } catch (error) {
    if (isNoIntentError(error)) {
      try {
        await askQuestion(command, pending);
      } catch (qaError) {
        updateMessage(pending, { role: "system", text: `命令未识别，问答也失败：${qaError.message}` });
      }
    } else {
      updateMessage(pending, { role: "system", text: `命令执行失败：${error.message}` });
    }
  }
  return true;
}

async function snapPhoto() {
  if (!state.connected) return;
  const seconds = Number(el.singleExposure.value);
  if (!Number.isFinite(seconds) || seconds <= 0) return setResult(el.snapResult, "曝光秒数需要大于 0。");
  if (!(await requireConfirm(`拍摄 ${seconds} 秒照片`))) return;
  setResult(el.snapResult, "正在请求相机曝光…");
  try {
    const payload = await api(`/camera/snap?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify({ exposure_seconds: seconds }),
    });
    setResult(el.snapResult, payload, "拍照请求已返回。");
    const imageUrl = state.execute && (payload.preview_ok || payload.preview_url)
      ? joinUrl(state.apiBase, `/camera/snap/preview?t=${Date.now()}`)
      : "";
    addMessage({ role: "user", text: `拍摄 ${seconds} 秒照片` });
    addMessage({
      text: imageUrl ? "拍照完成，预览如下。" : "拍照请求已返回。干跑模式不会产生真实照片。",
      payload,
      imageUrl,
    });
    if (imageUrl) loadSnapPreview();
  } catch (error) {
    setResult(el.snapResult, `拍照失败：${error.message}`);
  }
}

async function loadSnapPreview() {
  if (!state.connected) return;
  el.snapPreviewBox.textContent = "正在加载预览…";
  try {
    const response = await fetch(joinUrl(state.apiBase, `/camera/snap/preview?t=${Date.now()}`), {
      cache: "no-store",
      mode: "cors",
      credentials: "omit",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(extractError(data) || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    el.snapPreviewBox.replaceChildren();
    const img = document.createElement("img");
    img.alt = "最近一次拍照预览";
    img.src = url;
    el.snapPreviewBox.appendChild(img);
  } catch (error) {
    el.snapPreviewBox.textContent = `暂无预览：${error.message}`;
  }
}

async function liveStackStart() {
  if (!state.connected) return;
  if (!(await requireConfirm("开始边拍边叠"))) return;
  try {
    const payload = await api(`/camera/live-stack/start?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify({
        duration_seconds: Number(el.liveDuration.value),
        exposure_seconds: Number(el.liveExposure.value),
      }),
    });
    setResult(el.liveResult, payload, "边拍边叠已请求启动。");
  } catch (error) {
    setResult(el.liveResult, `启动失败：${error.message}`);
  }
}

async function liveStackStop() {
  if (!state.connected) return;
  if (!(await requireConfirm("停止边拍边叠"))) return;
  try {
    const payload = await api("/camera/live-stack/stop", { method: "POST" });
    setResult(el.liveResult, payload, "已请求停止边拍边叠。");
  } catch (error) {
    setResult(el.liveResult, `停止失败：${error.message}`);
  }
}

async function liveStackStatus() {
  if (!state.connected) return;
  try {
    const payload = await api("/camera/live-stack/status");
    setResult(el.liveResult, payload, "边拍边叠状态。");
  } catch (error) {
    setResult(el.liveResult, `读取失败：${error.message}`);
  }
}

async function calibrationStart() {
  if (!state.connected) return;
  if (!(await requireConfirm("开始校准拍摄"))) return;
  try {
    const payload = await api(`/camera/cal/${el.calKind.value}?execute=${state.execute}`, {
      method: "POST",
      body: JSON.stringify({
        count: Number(el.calCount.value),
        exposure_seconds: Number(el.calExposure.value),
      }),
    });
    setResult(el.calResult, payload, "校准拍摄请求已返回。");
  } catch (error) {
    setResult(el.calResult, `校准失败：${error.message}`);
  }
}

async function calibrationStop() {
  if (!state.connected) return;
  if (!(await requireConfirm("停止校准拍摄"))) return;
  try {
    const payload = await api("/camera/cal/stop", { method: "POST" });
    setResult(el.calResult, payload, "已请求停止校准。");
  } catch (error) {
    setResult(el.calResult, `停止失败：${error.message}`);
  }
}

async function abortMount() {
  if (!state.connected) return;
  if (!(await requireConfirm("急停 / Abort"))) return;
  try {
    const payload = await api(`/abort?execute=${state.execute}`, { method: "POST" });
    addMessage({ role: "user", text: "急停 / Abort" });
    addMessage({ text: "急停请求已返回。", payload });
    await refreshFullHealth();
  } catch (error) {
    addMessage({ role: "system", text: `急停失败：${error.message}` });
  }
}

async function readUsb() {
  if (!state.connected) return;
  try {
    setResult(el.usbResult, await api("/usb/devices"), "USB 设备。");
  } catch (error) {
    setResult(el.usbResult, `USB 读取失败：${error.message}`);
  }
}

async function readFocuser() {
  if (!state.connected) return;
  try {
    setResult(el.focuserResult, await api("/focuser/position"), "电调位置。");
  } catch (error) {
    setResult(el.focuserResult, `电调读取失败：${error.message}`);
  }
}

async function moveFocuser() {
  if (!state.connected) return;
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
  if (!state.connected) return;
  try {
    const [slots, status] = await Promise.all([api("/filter/slots"), api("/filter/status")]);
    setResult(el.filterResult, { slots, status }, "滤镜轮。");
  } catch (error) {
    setResult(el.filterResult, `滤镜读取失败：${error.message}`);
  }
}

async function transitStatus() {
  if (!state.connected) return;
  try {
    setResult(el.transitResult, await api("/plan/transit/status"), "凌星计划状态。");
  } catch (error) {
    setResult(el.transitResult, `读取失败：${error.message}`);
  }
}

async function transitRun() {
  if (!state.connected) return;
  if (!(await requireConfirm("启动凌星计划"))) return;
  const params = new URLSearchParams({ execute: String(state.execute), force: "true" });
  const planPath = el.transitPlanPath.value.trim();
  if (planPath) params.set("plan_path", planPath);
  try {
    setResult(el.transitResult, await api(`/plan/transit/run?${params}`, { method: "POST" }), "凌星计划已请求启动。");
  } catch (error) {
    setResult(el.transitResult, `启动失败：${error.message}`);
  }
}

async function transitAbort() {
  if (!state.connected) return;
  if (!(await requireConfirm("中止凌星计划"))) return;
  try {
    const payload = await api(`/plan/transit/abort?execute=${state.execute}&reason=${encodeURIComponent("web user abort")}`, {
      method: "POST",
    });
    setResult(el.transitResult, payload, "已请求中止凌星计划。");
  } catch (error) {
    setResult(el.transitResult, `中止失败：${error.message}`);
  }
}

async function loadEnv() {
  if (!state.connected) return;
  try {
    const query = envKeys.map((key) => `keys=${encodeURIComponent(key)}`).join("&");
    const payload = await api(`/config/env?${query}`);
    state.envValues = payload.values || {};
    renderEnvFields();
  } catch (error) {
    el.envFields.replaceChildren();
    const box = document.createElement("div");
    box.className = "result-box";
    box.textContent = `读取参数失败：${error.message}`;
    el.envFields.appendChild(box);
  }
}

function renderEnvFields() {
  el.envFields.replaceChildren();
  for (const key of envKeys) {
    const row = document.createElement("div");
    row.className = "env-row";
    const label = document.createElement("label");
    label.htmlFor = `env-${key}`;
    label.textContent = key;
    const input = document.createElement("input");
    input.id = `env-${key}`;
    input.dataset.envKey = key;
    input.value = state.envValues[key] || "";
    row.append(label, input);
    el.envFields.appendChild(row);
  }
}

async function saveEnv() {
  if (!state.connected) return;
  const updates = {};
  $$("[data-env-key]").forEach((input) => {
    const key = input.dataset.envKey;
    if ((state.envValues[key] || "") !== input.value) updates[key] = input.value;
  });
  if (!Object.keys(updates).length) return showJson({ ok: true, message: "没有修改。" });
  if (!(await confirmDanger("保存服务器参数。这会写回树莓派上的 .env，并立即影响当前服务"))) return;
  try {
    const payload = await api("/config/env", { method: "PATCH", body: JSON.stringify({ updates }) });
    state.envValues = payload.values || state.envValues;
    showJson(payload);
    renderEnvFields();
    await refreshFullHealth();
  } catch (error) {
    showJson({ ok: false, error: error.message });
  }
}

async function toggleRecording() {
  if (!state.connected) return;
  if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
    state.mediaRecorder.stop();
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
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
      el.recordButton.textContent = "语音";
      stream.getTracks().forEach((track) => track.stop());
      sendAudio(new Blob(state.audioChunks, { type: state.mediaRecorder.mimeType || "audio/webm" }));
    };
    el.recordButton.classList.add("recording");
    el.recordButton.textContent = "停止";
    addMessage({ role: "system", text: "录音中，再点一次停止并发送。" });
    state.mediaRecorder.start();
  } catch (error) {
    addMessage({ role: "system", text: `无法开始录音：${error.message}` });
  }
}

async function sendAudio(blob) {
  addMessage({ role: "user", text: "语音指令" });
  const pending = addMessage({ text: "正在转写语音并整理回复…" });
  const form = new FormData();
  form.append("file", blob, "telbot-command.webm");
  try {
    const payload = await api(`/listen/audio?execute=${state.execute}&no_semantic=true&no_llm=true`, {
      method: "POST",
      body: form,
    });
    updateMessage(pending, {
      text: `你说的是：「${payload.transcript || "未返回文字"}」\n${describeIntent(payload)}\n${responseText(payload)}`,
      payload,
    });
  } catch (error) {
    updateMessage(pending, { role: "system", text: `语音命令失败：${error.message}` });
  }
}

function showConsolePanel(name) {
  document.body.classList.add("console-ready");
  $$(".console-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
  $$(".subnav button").forEach((button) => {
    const on = button.dataset.panel === name;
    button.classList.toggle("active", on);
    button.setAttribute("aria-selected", on ? "true" : "false");
  });
}

function bindEvents() {
  el.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = el.promptInput.value;
    const sent = await sendTextCommand(text);
    if (sent) {
      el.promptInput.value = "";
      el.promptInput.style.height = "auto";
    }
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
    if (!state.connected) {
      el.executeToggle.checked = false;
      state.execute = false;
      renderConnection();
      return;
    }
    if (el.executeToggle.checked) {
      const ok = await confirmDanger("打开真机执行模式");
      if (!ok) {
        el.executeToggle.checked = false;
        state.execute = false;
        renderConnection();
        return;
      }
    }
    state.execute = el.executeToggle.checked;
    renderConnection();
    addMessage({
      role: "system",
      text: state.execute ? "真机执行已打开。危险操作会继续二次确认。" : "已切回干跑模式。",
    });
  });
  $$(".subnav button").forEach((button) => button.addEventListener("click", () => showConsolePanel(button.dataset.panel)));
  $$(".quick-command").forEach((button) => button.addEventListener("click", () => {
    el.promptInput.value = button.dataset.command || "";
    el.promptInput.focus();
  }));
  el.redetect.addEventListener("click", () => {
    const typed = el.apiBase.value.trim();
    if (!typed) detect();
    else detect({ preferred: typed });
  });
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

  const sections = ["overview", "how", "safety", "tour", "console"].map((id) => document.getElementById(id)).filter(Boolean);
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      $$(".site-nav a").forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`));
    }, { rootMargin: "-20% 0px -60% 0px", threshold: [0.15, 0.4] });
    sections.forEach((section) => observer.observe(section));
  }
}

function init() {
  loadPrefs();
  bindEvents();
  showConsolePanel("chat");
  renderConnection();
  const query = readQueryApi();
  if (query.kind === "relative-only") {
    el.apiBase.value = "";
    detect({ onlyRelative: true });
    return;
  }
  if (query.kind === "url") {
    el.apiBase.value = query.value;
    detect({ preferred: query.value });
    return;
  }
  const remembered = rememberedBase();
  if (remembered) el.apiBase.value = remembered;
  detect();
}

init();
