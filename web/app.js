const STORAGE_BASE = "telbot.apiBase";
const STORAGE_REMEMBER = "telbot.rememberApi";
const STORAGE_TUNNEL = "telbot.tunnelUrl";
const PROBE_TIMEOUT_MS = 2000;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const envDefs = [
  ["INDI 与设备", [
    ["TELBOT_INDI_HOST", "INDI 主机", "通常为 127.0.0.1。"],
    ["TELBOT_INDI_PORT", "INDI 端口", "常见为 7624。"],
    ["TELBOT_INDI_DEVICE", "赤道仪设备名", "与 indi_getprop 一致，例如 Losmandy Gemini。"],
    ["TELBOT_INDI_CCD_DEVICE", "主相机设备名", "例如 QHY CCD QHY174M。"],
    ["TELBOT_INDI_CFW_DEVICE", "滤镜轮设备名", "例如 QHYCFW3。"],
    ["TELBOT_INDI_FOCUSER_DEVICE", "电调设备名", "例如 Oasis Focuser。"],
  ]],
  ["观测地", [
    ["TELBOT_LATITUDE", "纬度（°）", "十进制度数，例如 31.2。"],
    ["TELBOT_LONGITUDE", "经度（°）", "十进制度数，例如 121.5。"],
    ["TELBOT_ELEVATION_M", "海拔（米）", "用于地平与计划计算。"],
    ["TELBOT_PLAN_TIMEZONE", "时区", "IANA 时区，例如 Asia/Shanghai。"],
    ["TELBOT_MIN_ALTITUDE_DEG", "最低高度角（°）", "GOTO / 语音转镜安全下限。"],
  ]],
  ["曝光", [
    ["TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS", "CCD 默认曝光（秒）", "单次 snap 未指定时的曝光。"],
    ["TELBOT_PLAN_DEFAULT_EXPOSURE_SECONDS", "计划默认曝光（秒）", "非凌星计划的默认曝光。"],
    ["TELBOT_TRANSIT_EXPOSURE_SECONDS", "凌星固定曝光（秒）", "大于 0 时跳过 ETC，强制使用该曝光；0 表示由 ETC 计算。"],
    ["TELBOT_EXPOSE_LOOP_OVERHEAD_SECONDS", "连拍间隔 overhead（秒）", "cadence = 曝光 + 此项（expose-loop）。"],
  ]],
  ["ETC 光学", [
    ["TELBOT_OTA_APERTURE_MM", "OTA 口径（mm）", "0 表示从选镜 profile / 板解自动推断。"],
    ["TELBOT_OTA_FOCAL_LENGTH_MM", "OTA 焦距（mm）", "0 表示自动推断。"],
    ["TELBOT_TRANSIT_ETC_APERTURE_MM", "ETC 口径（mm）", "显式覆盖 ETC 仪器模型。"],
    ["TELBOT_TRANSIT_ETC_FOCAL_LENGTH_MM", "ETC 焦距（mm）", "显式覆盖 ETC 仪器模型。"],
  ]],
  ["ETC 传感器", [
    ["TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM", "像素尺寸（μm）", "可从 CCD 登记表 / INDI 自动解析。"],
    ["TELBOT_TRANSIT_ETC_READ_NOISE_E", "读出噪声（e⁻）", "传感器读出噪声。"],
    ["TELBOT_TRANSIT_ETC_FULL_WELL_E", "满阱（e⁻）", "用于饱和约束。"],
    ["TELBOT_TRANSIT_ETC_APERTURE_RADIUS_PIX", "测光孔径半径（像素）", "ETC 测光圆孔半径。"],
  ]],
  ["ETC 观测条件", [
    ["TELBOT_TRANSIT_ETC_SEEING_ARCSEC", "视宁（角秒）", "影响星像展宽与背景。"],
    ["TELBOT_TRANSIT_ETC_SKY_MAG_PER_ARCSEC2", "天空亮度（mag/角秒²）", "背景天空亮度。"],
    ["TELBOT_TRANSIT_ETC_SYSTEM_THROUGHPUT", "系统透过率", "0–1，光学+滤镜综合效率。"],
    ["TELBOT_TRANSIT_ETC_TARGET_SNR_ON_DEPTH", "目标 SNR", "凌深测光目标信噪比。"],
  ]],
  ["ETC 曝光范围", [
    ["TELBOT_TRANSIT_ETC_MIN_EXPOSURE_SECONDS", "ETC 最短曝光（秒）", "ETC 结果下限。"],
    ["TELBOT_TRANSIT_ETC_MAX_EXPOSURE_SECONDS", "ETC 最长曝光（秒）", "ETC 结果上限。"],
  ]],
  ["其它", [
    ["TELBOT_LLM_MODEL", "LLM 模型", "语义解析模型；不含 API Key。"],
    ["TELBOT_OPENAI_TRANSCRIPTION_MODEL", "语音转写模型", "Whisper 等转写模型。"],
    ["TELBOT_PLATESOLVE_TIMEOUT_S", "解算超时（秒）", "Plate solve 最长等待。"],
    ["TELBOT_INDI_GETPROP_TIMEOUT", "INDI 读数超时（秒）", "indi_getprop -t 参数。"],
  ]],
];

const calKinds = [
  {
    id: "bias",
    title: "偏置场",
    subtitle: "盖住镜头 · 自动连拍很多张极短照片",
    count: 20,
    exposure: 0,
    prep: "这一步在「完全看不见光」的情况下拍很多张极短照片，用来减少画面上的杂点。\n\n开始前请确认：\n1. 相机前面的盖子已经盖好，或镜头被完全挡住，不要让光漏进去。\n2. 手机已连上 Telbot 盒子，且相机显示为已连接。\n3. 拍摄过程中请保持遮光，不要中途打开盖子。\n\n拍完后照片会保存在设备里，供后续处理使用。",
  },
  {
    id: "dark",
    title: "暗场",
    subtitle: "盖住镜头 · 每张时间和正式拍星空时一样长",
    count: 10,
    exposure: 60,
    prep: "这一步同样在盖住镜头的情况下拍摄，但每张会拍一会儿，用来记录相机自身的噪点。\n\n开始前请确认：\n1. 盖子已盖好，遮光方式和接下来要拍的「正式星空照」一样。\n2. 每张拍多久，建议和正式星空照相同（可在「高级选项」里改）。\n3. 若相机刚开机，可先等几分钟再开始，让温度稳定一些。\n\n以后处理正式照片时，会用这些照片把噪点减掉。",
  },
  {
    id: "flat",
    title: "平场",
    subtitle: "对准一块亮度均匀的地方",
    count: 30,
    exposure: 1,
    prep: "这一步要对准「整块亮度差不多」的画面，用来让照片四角不会一边亮一边暗。\n\n开始前请确认：\n1. 望远镜对准均匀亮面，例如：专用白板、均匀的灯光，或阴天/黎明时均匀的天空。\n2. 画面里不要出现星星、树木、楼房等明暗不一的东西。\n3. 若拍出来太亮或太暗，可在「高级选项」里调整每张的秒数，多试几次。\n4. 若使用滤镜，请调到和之后拍正式星空照时相同的位置。\n\n拍的时候请保持画面稳定，不要晃动望远镜。",
  },
];

const statusTitle = {
  not_started: "未开始",
  observing: "正在观测",
  finished: "结束",
  cancelled: "已取消",
  terminated: "已终止",
};

const viewTitle = { chat: "对话", capture: "拍摄", plan: "计划", settings: "设置" };

const state = {
  connected: false,
  probing: false,
  checked: false,
  apiBase: "",
  execute: false,
  advanced: false,
  health: null,
  notice: "",
  lastError: "",
  view: "chat",
  captureMode: "liveStack",
  messages: [],
  plans: [],
  planBadge: 0,
  photos: [],
  envValues: {},
  envLoaded: false,
  devicesRefreshing: false,
  deviceCheckedAt: null,
  snapshot: emptySnapshot(),
  filterSlots: [],
  filterPlanId: null,
  live: { running: false, previewUrl: "", status: "", error: "" },
  cal: { running: false, status: "", error: "", kind: "" },
  snap: { running: false, status: "", error: "" },
  liveTimer: 0,
  planTimer: 0,
  flight: 0,
  abort: null,
  voiceMode: false,
  recorder: null,
  recordStarted: 0,
  voiceChunks: [],
  voiceBlob: null,
  pendingKind: null,
};

const el = {
  splash: $("#splash"),
  statusPill: $("#statusPill"),
  statusPillTop: $("#statusPillTop"),
  executeToggle: $("#executeToggle"),
  advancedToggle: $("#advancedToggle"),
  viewTitle: $("#viewTitle"),
  messages: $("#messages"),
  chatEmpty: $("#chatEmpty"),
  chatScroll: $("#chatScroll"),
  chatStatus: $("#chatStatus"),
  composer: $("#composer"),
  controlFieldset: $("#controlFieldset"),
  micButton: $("#micButton"),
  prompt: $("#prompt"),
  voiceHold: $("#voiceHold"),
  sendButton: $("#sendButton"),
  apiBase: $("#apiBase"),
  rememberApi: $("#rememberApi"),
  redetect: $("#redetect"),
  mixedHint: $("#mixedHint"),
  deviceList: $("#deviceList"),
  deviceFoot: $("#deviceFoot"),
  deviceError: $("#deviceError"),
  envFields: $("#envFields"),
  envStatus: $("#envStatus"),
  captureNotice: $("#captureNotice"),
  livePane: $("#livePane"),
  calPane: $("#calPane"),
  snapPane: $("#snapPane"),
  liveStage: $("#liveStage"),
  liveEmpty: $("#liveEmpty"),
  liveStatusBar: $("#liveStatusBar"),
  liveStatus: $("#liveStatus"),
  liveStatusLabel: $("#liveStatusLabel"),
  liveShutter: $("#liveShutter"),
  calBody: $("#calBody"),
  calStatusBar: $("#calStatusBar"),
  calStatus: $("#calStatus"),
  calStatusLabel: $("#calStatusLabel"),
  snapStage: $("#snapStage"),
  snapEmpty: $("#snapEmpty"),
  snapStatusBar: $("#snapStatusBar"),
  snapStatus: $("#snapStatus"),
  snapStatusLabel: $("#snapStatusLabel"),
  snapShutter: $("#snapShutter"),
  snapAlbum: $("#snapAlbum"),
  snapExposure: $("#snapExposure"),
  planEmpty: $("#planEmpty"),
  planFilled: $("#planFilled"),
  planNotice: $("#planNotice"),
  planPrecheck: $("#planPrecheck"),
  planList: $("#planList"),
  planBadge: $("#planBadge"),
  confirmDialog: $("#confirmDialog"),
  confirmText: $("#confirmText"),
  confirmAccept: $("#confirmAccept"),
  confirmCancel: $("#confirmCancel"),
  prepDialog: $("#prepDialog"),
  prepTitle: $("#prepTitle"),
  prepBody: $("#prepBody"),
  albumDialog: $("#albumDialog"),
  albumGrid: $("#albumGrid"),
  filterDialog: $("#filterDialog"),
  filterList: $("#filterList"),
};

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
}
function storageRemove(key) {
  try { localStorage.removeItem(key); } catch { /* private mode */ }
}
function readJson(key, fallback) {
  try {
    const raw = storageGet(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function emptySlot() {
  return { displayName: "", vidPid: "", configured: false, connected: false, usesUsbDetection: false, usesServiceDetection: false, endpointLabel: "" };
}
function emptySnapshot() {
  return {
    telbotBox: { ...emptySlot(), usesServiceDetection: true },
    mount: emptySlot(),
    mainCamera: emptySlot(),
    filterWheel: emptySlot(),
    focuser: emptySlot(),
    fetchError: "",
  };
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
function rememberedBase() {
  if (storageGet(STORAGE_REMEMBER) !== "1") return null;
  const value = storageGet(STORAGE_BASE);
  return value == null ? null : normalizeBase(value);
}
function savedTunnel() {
  if (storageGet(STORAGE_REMEMBER) !== "1") return "";
  return normalizeBase(storageGet(STORAGE_TUNNEL) || "");
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

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function extractError(data, status) {
  if (!data) return status ? `HTTP ${status}` : "";
  if (typeof data === "string") return data;
  if (typeof data.detail === "string" && data.detail) return data.detail;
  if (data.message) return data.message;
  if (data.hint) return data.hint;
  if (data.detail && data.detail.message) return data.detail.message;
  if (data.error) return String(data.error);
  try { return JSON.stringify(data, null, 2); } catch { return `HTTP ${status}`; }
}

async function api(path, options = {}) {
  if (!state.connected && !options.allowOffline) throw new ApiError("未连接", 0, null);
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
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    markDisconnected("无法连接 Telbot 盒子");
    throw new ApiError("无法连接 Telbot 盒子", 0, null);
  }
  const contentType = response.headers.get("content-type") || "";
  let data = null;
  if (contentType.includes("application/json")) data = await response.json();
  else if (contentType.startsWith("text/")) data = await response.text();
  if (!response.ok) throw new ApiError(extractError(data, response.status), response.status, data);
  return data;
}

async function probe(base) {
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
      try { data = JSON.parse(await response.text()); } catch { data = null; }
    }
    if (!response.ok || !data || typeof data !== "object" || (data.status && data.status !== "ok")) {
      return { ok: false, base };
    }
    return { ok: true, base, health: data };
  } catch {
    return { ok: false, base };
  } finally {
    clearTimeout(timer);
  }
}

async function detect(options = {}) {
  if (state.probing) return;
  state.probing = true;
  state.notice = "";
  renderConnection();
  const candidates = options.onlyRelative ? [""] : buildCandidates(options.preferred);
  let winner = null;
  for (const base of candidates) {
    const result = await probe(base);
    if (result.ok) {
      winner = result;
      break;
    }
  }
  state.probing = false;
  state.checked = true;
  if (winner) {
    const typed = options.preferred ? normalizeBase(options.preferred) : "";
    state.connected = true;
    state.apiBase = winner.base;
    state.health = winner.health;
    state.lastError = "";
    state.notice = typed && typed !== winner.base ? `填写的地址没有应答，已改用 ${winner.base || "同源地址"}。` : "";
    el.apiBase.value = winner.base || "";
    persistAfterDetect(winner.base);
    renderConnection();
    refreshDevices();
    if (state.view === "settings") {
      refreshDevices();
      loadEnv();
    }
    syncLiveIfRunning();
    refreshPlans();
    return;
  }
  state.connected = false;
  state.health = null;
  state.lastError = "无法连接 Telbot 盒子（telbot）：请求超时或 Pi 未开机。请确认在同一 Wi‑Fi 后重新检测。";
  state.snapshot = emptySnapshot();
  state.snapshot.fetchError = state.lastError;
  state.snapshot.telbotBox.endpointLabel = "telbot";
  persistAfterDetect(null);
  renderConnection();
  renderDevices();
  renderCaptureLock();
}

function markDisconnected(message) {
  state.connected = false;
  state.health = null;
  state.lastError = message || "无法连接 Telbot 盒子";
  state.snapshot = emptySnapshot();
  state.snapshot.fetchError = state.lastError;
  renderConnection();
  renderDevices();
  renderCaptureLock();
}

function statusLabel() {
  if (!state.connected) return "未连接";
  return state.execute ? "已连接 · 真机" : "已连接";
}

function renderConnection() {
  document.body.dataset.connected = state.connected ? "true" : "false";
  const label = statusLabel();
  el.statusPill.textContent = label;
  el.statusPillTop.textContent = label;
  el.statusPill.classList.toggle("online", state.connected);
  el.statusPill.classList.toggle("offline", !state.connected);
  el.statusPillTop.classList.toggle("online", state.connected);
  el.statusPillTop.classList.toggle("offline", !state.connected);
  el.controlFieldset.disabled = !state.connected;
  el.executeToggle.disabled = !state.connected;
  el.executeToggle.checked = state.connected && state.execute;
  el.redetect.disabled = state.probing;
  el.redetect.textContent = state.probing ? "正在检测…" : "重新检测";
  updateSendButton();
  renderCaptureLock();
  renderPlans();
}

function canModifyPlans() {
  return state.checked && state.connected;
}
function canCapture() {
  return state.connected && state.snapshot.mainCamera.connected;
}
function captureReason() {
  if (state.probing || state.devicesRefreshing) return "正在检测设备连接…";
  if (!state.connected) return "请先连接 Telbot 盒子：确认 Pi 已开机、与手机在同一 Wi‑Fi，并在「设置 → 连接设备」中重新检测。";
  if (!state.snapshot.mainCamera.connected) return "请先在「设置 → 连接设备」中确认主相机已通过 USB 连接（显示 USB 已连接）。";
  return "";
}
function planReason() {
  if (state.probing || !state.checked) return "正在确认与 Telbot 盒子的连接，请稍候…";
  if (!state.connected) return "请先连接 Telbot 盒子：确认 Pi 已开机、与手机在同一 Wi‑Fi，并在「设置 → 连接设备」中重新检测。";
  return "";
}

function slotSubtitle(slot) {
  if (slot.usesServiceDetection) {
    if (slot.connected) return slot.endpointLabel ? `已连接（${slot.endpointLabel}）` : "已连接";
    return "未连接到 Telbot 服务（请确认 Telbot 盒子已开机、在同一 Wi‑Fi，且 telbot serve 已运行）";
  }
  if (slot.usesUsbDetection) {
    if (!slot.connected) return "未检测到 USB（请检查线缆、供电与树莓派 lsusb）";
    const label = slot.displayName || slot.vidPid || "（登记设备）";
    if (slot.vidPid && !label.includes(slot.vidPid)) return `${label} · USB 已连接 (${slot.vidPid})`;
    return `${label} · USB 已连接`;
  }
  return "未在 Telbot 配置";
}

function parseUsbSlot(dict) {
  if (!dict || typeof dict !== "object") {
    return { ...emptySlot(), configured: true, usesUsbDetection: true };
  }
  const connected = Boolean(dict.connected);
  const name = String(dict.label_zh || dict.name || "").trim();
  const vid = String(dict.vid_pid || "").trim();
  return {
    displayName: name,
    vidPid: vid,
    configured: true,
    connected,
    usesUsbDetection: true,
    usesServiceDetection: false,
    endpointLabel: "",
  };
}

function applyUsb(root) {
  const slots = root && root.slots ? root.slots : {};
  state.snapshot.mount = parseUsbSlot(slots.mount);
  state.snapshot.mainCamera = parseUsbSlot(slots.main_camera);
  state.snapshot.filterWheel = parseUsbSlot(slots.filter_wheel);
  state.snapshot.focuser = parseUsbSlot(slots.focuser);
  const devices = Array.isArray(root.devices) ? root.devices : [];
  const byCat = { mount: "mount", ccd: "mainCamera", cfw: "filterWheel", focuser: "focuser" };
  for (const device of devices) {
    const key = byCat[device.category];
    if (!key || state.snapshot[key].connected) continue;
    state.snapshot[key] = {
      displayName: String(device.label_zh || device.name || "").trim(),
      vidPid: String(device.vid_pid || "").trim(),
      configured: true,
      connected: true,
      usesUsbDetection: true,
      usesServiceDetection: false,
      endpointLabel: "",
    };
  }
}

async function refreshDevices() {
  state.devicesRefreshing = true;
  renderDevices();
  renderCaptureLock();
  if (!state.connected) {
    state.snapshot = emptySnapshot();
    state.snapshot.fetchError = state.lastError;
    state.devicesRefreshing = false;
    state.deviceCheckedAt = new Date();
    renderDevices();
    renderCaptureLock();
    return;
  }
  state.snapshot.telbotBox = {
    ...emptySlot(),
    connected: true,
    usesServiceDetection: true,
    endpointLabel: state.apiBase || "同源",
  };
  try {
    const data = await api("/usb/devices");
    applyUsb(data || {});
    state.snapshot.fetchError = "";
  } catch (error) {
    state.snapshot.fetchError = error.message;
    for (const key of ["mount", "mainCamera", "filterWheel", "focuser"]) {
      state.snapshot[key] = { ...state.snapshot[key], connected: false };
    }
  }
  state.devicesRefreshing = false;
  state.deviceCheckedAt = new Date();
  renderDevices();
  renderCaptureLock();
}

function renderDevices() {
  const rows = [
    ["Telbot盒子", state.snapshot.telbotBox],
    ["赤道仪", state.snapshot.mount],
    ["主相机", state.snapshot.mainCamera],
    ["滤镜轮", state.snapshot.filterWheel],
    ["电调焦", state.snapshot.focuser],
  ];
  el.deviceList.replaceChildren();
  for (const [title, slot] of rows) {
    const row = document.createElement("div");
    row.className = `device-row${slot.connected ? "" : " warn"}`;
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = slotSubtitle(slot);
    row.append(strong, span);
    el.deviceList.appendChild(row);
  }
  if (state.snapshot.fetchError) {
    el.deviceError.hidden = false;
    el.deviceError.textContent = state.snapshot.fetchError;
  } else {
    el.deviceError.hidden = true;
  }
  const when = state.deviceCheckedAt
    ? `上次检测：${new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(state.deviceCheckedAt)}（打开页面时自动更新，可手动重新检测）`
    : "尚未完成 USB 检测；请确认已配置服务地址。";
  const note = state.notice ? `${state.notice} ` : "";
  el.deviceFoot.textContent = `${note}${when} Telbot 盒子：能否访问 Pi 的 HTTP 服务（GET /health）。其余设备以树莓派 lsusb 与 USB 登记表为准（VID:PID），不依赖 INDI CONNECTION。`;
}

function showView(name) {
  state.view = name;
  document.body.dataset.view = name;
  for (const id of ["chat", "capture", "plan", "settings"]) {
    const node = document.getElementById(`view-${id}`);
    const on = id === name;
    node.classList.toggle("active", on);
    node.hidden = !on;
  }
  $$(".side-nav button").forEach((button) => {
    const on = button.dataset.view === name;
    if (on) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  el.viewTitle.textContent = viewTitle[name];
  closeNav();
  if (name === "plan") {
    state.planBadge = 0;
    renderPlanBadge();
    maybeAskNotify();
    refreshPlans();
  }
  if (name === "capture") {
    renderCaptureLock();
    if (state.captureMode === "liveStack") syncLiveIfRunning();
  }
  if (name === "settings") {
    refreshDevices();
    loadEnv();
  }
}


function closeNav() {
  document.body.classList.remove("nav-open");
  $("#scrim").hidden = true;
}

function confirmAction(message, acceptLabel = "确认") {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      if (el.confirmDialog.open) el.confirmDialog.close();
    };
    el.confirmText.textContent = message;
    el.confirmAccept.textContent = acceptLabel;
    el.confirmAccept.onclick = () => finish(true);
    el.confirmCancel.onclick = () => finish(false);
    el.confirmDialog.onclose = () => finish(false);
    if (!el.confirmDialog.open) el.confirmDialog.showModal();
  });
}

function setChatStatus(text) {
  el.chatStatus.hidden = !text;
  el.chatStatus.textContent = text || "";
}

function saveChat() {
  storageSet("telbot.chatItems", JSON.stringify(state.messages.filter((item) => !item.pending)));
}
function loadChat() {
  state.messages = readJson("telbot.chatItems", []).filter((item) => item && item.text);
}
function savePlans() {
  storageSet("telbot.plans", JSON.stringify(state.plans));
}
function loadPlans() {
  state.plans = readJson("telbot.plans", []);
}

function stampFor(date, now = new Date()) {
  const time = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(now) - day(date)) / 86400000);
  if (diff === 0) return time;
  if (diff === 1) return `昨天 ${time}`;
  const week = (d) => {
    const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const dayNum = utc.getUTCDay() || 7;
    utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
    return `${utc.getUTCFullYear()}-${Math.ceil((((utc - yearStart) / 86400000) + 1) / 7)}`;
  };
  if (week(date) === week(now)) {
    const names = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    return `${names[date.getDay()]} ${time}`;
  }
  return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`;
}
function showStamp(items, index) {
  const item = items[index];
  if (!item || item.pending) return false;
  let prev = index - 1;
  while (prev >= 0 && items[prev].pending) prev -= 1;
  if (prev < 0) return true;
  if (items[prev].isUser !== item.isUser) return true;
  return new Date(item.createdAt) - new Date(items[prev].createdAt) >= 5 * 60 * 1000;
}

function renderMessages() {
  el.messages.replaceChildren();
  el.chatEmpty.hidden = state.messages.length > 0;
  state.messages.forEach((item, index) => {
    if (showStamp(state.messages, index)) {
      const stamp = document.createElement("div");
      stamp.className = "stamp";
      stamp.textContent = stampFor(new Date(item.createdAt));
      el.messages.appendChild(stamp);
    }
    const row = document.createElement("article");
    row.className = `msg ${item.isUser ? "user" : "assistant"}${item.pending ? " pending" : ""}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = item.text;
    row.appendChild(bubble);
    if (!item.isUser && !item.pending) {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "msg-copy";
      copy.textContent = "拷贝";
      copy.addEventListener("click", () => navigator.clipboard?.writeText(item.text));
      row.appendChild(copy);
    }
    if (item.redo) {
      const redo = document.createElement("button");
      redo.type = "button";
      redo.className = "redo";
      redo.textContent = "重做";
      redo.addEventListener("click", () => {
        if (item.redo.kind === "text") sendTyped(item.redo.text);
        else redoVoice();
      });
      row.appendChild(redo);
    }
    el.messages.appendChild(row);
  });
  el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
}

function updateSendButton() {
  const pending = Boolean(state.abort);
  const empty = !el.prompt.value.trim();
  el.sendButton.disabled = !state.connected || (!pending && (empty || state.voiceMode));
  el.sendButton.classList.toggle("stop", pending);
  el.sendButton.hidden = state.voiceMode && !pending;
  el.sendButton.setAttribute("aria-label", pending ? "中止请求" : "发送");
  el.micButton.disabled = !state.connected || pending;
  el.prompt.disabled = !state.connected || state.voiceMode;
  el.voiceHold.disabled = !state.connected || pending;
}

function nlFrom(obj, advanced) {
  if (!obj || typeof obj !== "object") return "";
  const pick = (root, key) => {
    const block = root && root[key];
    const text = block && typeof block.text === "string" ? block.text.trim() : "";
    return text;
  };
  const result = obj.result && typeof obj.result === "object" ? obj.result : null;
  if (advanced) return pick(obj, "nl") || (result && pick(result, "nl")) || "";
  return pick(obj, "nl_simple") || (result && pick(result, "nl_simple")) || pick(obj, "nl") || (result && pick(result, "nl")) || "";
}
function pretty(data) {
  if (typeof data === "string") return data;
  try { return JSON.stringify(data, null, 2); } catch { return String(data ?? ""); }
}
function assistantText(data) {
  return nlFrom(data, state.advanced) || pretty(data);
}

function parseUtc(value) {
  if (!value || typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
function planetsMatch(a, b) {
  const n = (s) => String(s || "").toLowerCase().replace(/[\s-]/g, "");
  const na = n(a);
  const nb = n(b);
  return na === nb || na.includes(nb) || nb.includes(na);
}
function sameEvent(a, b) {
  if (!planetsMatch(a.planetName, b.planetName)) return false;
  if (Math.abs(new Date(a.scheduledStart) - new Date(b.scheduledStart)) >= 2000) return false;
  if (!a.scheduledEnd && !b.scheduledEnd) return true;
  if (!a.scheduledEnd || !b.scheduledEnd) return false;
  return Math.abs(new Date(a.scheduledEnd) - new Date(b.scheduledEnd)) < 2000;
}
function scheduleText(iso) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

function ingestTransit(payload) {
  const intent = payload && payload.intent;
  if (!intent || intent.action !== "plan_exoplanet_transit") return "";
  const result = payload.result || {};
  if (result.ok === false) return "";
  const saved = String(result.saved_path || "").trim();
  if (!saved) return "";
  const plan = result.plan || {};
  const start = parseUtc((plan.window || {}).start_utc);
  if (!start) return "";
  const end = parseUtc((plan.window || {}).end_utc);
  const planet = String((plan.target || {}).planet || "").trim() || "凌星目标";
  const item = {
    id: uid(),
    planetName: planet,
    scheduledStart: start.toISOString(),
    scheduledEnd: end ? end.toISOString() : null,
    status: "not_started",
    piPlanPath: saved,
    createdAt: new Date().toISOString(),
    piRunSubmitted: false,
    precheckNotifiedCheckUtc: null,
    exposureSeconds: 0,
    selectedFilterName: "",
  };
  const existing = state.plans.find((planItem) => sameEvent(planItem, item) && planItem.status !== "cancelled" && planItem.status !== "terminated");
  if (existing) return `\n\n该凌星事件已在计划中（${existing.planetName}），未重复添加。`;
  state.plans.unshift(item);
  state.planBadge += 1;
  savePlans();
  renderPlanBadge();
  renderPlans();
  ensurePlanPoll();
  if (state.execute) submitTransitRun(item);
  const when = scheduleText(item.scheduledStart);
  const hint = state.execute
    ? `将于 ${when} 起由 Pi 自动执行（请保持 telbot serve 与网络可用）`
    : `计划拍摄 ${when}；请打开真机执行后重新规划，或在 Pi 上运行 transit-run`;
  return `\n\n已加入「计划」：${item.planetName}，${hint}。`;
}

async function submitTransitRun(plan) {
  try {
    const params = new URLSearchParams({
      execute: "true",
      force: "true",
      plan_path: plan.piPlanPath,
    });
    await api(`/plan/transit/run?${params}`, { method: "POST" });
    plan.piRunSubmitted = true;
    savePlans();
    renderPlans();
  } catch {
    /* 保留计划，可在 Pi 上手动 transit-run */
  }
}

async function postListenText(text, execute, signal) {
  const body = JSON.stringify({ text });
  try {
    return await api(`/listen/text?execute=${execute}`, { method: "POST", body, signal });
  } catch (error) {
    if (error.status === 404) return api(`/text?execute=${execute}`, { method: "POST", body, signal });
    throw error;
  }
}

async function sendTyped(command) {
  const text = String(command || "").trim();
  if (!text || state.abort) return;
  if (!state.connected) {
    setChatStatus("请确认已与 Telbot 连通（设置 → 连接设备可重新检测）。");
    return;
  }
  if (state.execute) {
    const ok = await confirmAction(`将发送「${text}」并真实控制设备。请确认镜筒与周边无阻碍。`, "确认发送");
    if (!ok) return;
  }
  el.prompt.value = "";
  resizePrompt();
  const token = ++state.flight;
  state.abort = new AbortController();
  state.messages.push({ id: uid(), isUser: true, text, createdAt: new Date().toISOString() });
  state.messages.push({ id: uid(), isUser: false, text: "正在听取指令并整理回复…", createdAt: new Date().toISOString(), pending: true });
  renderMessages();
  updateSendButton();
  try {
    const data = await postListenText(text, state.execute, state.abort.signal);
    if (token !== state.flight) return;
    state.messages = state.messages.filter((item) => !item.pending);
    state.messages.push({
      id: uid(),
      isUser: false,
      text: `${assistantText(data)}${ingestTransit(data)}`,
      createdAt: new Date().toISOString(),
    });
    setChatStatus("");
  } catch (error) {
    if (token !== state.flight || error.name === "AbortError") return;
    state.messages = state.messages.filter((item) => !item.pending);
    let server = error.message || "请求失败";
    const body = error.data;
    if (body && typeof body === "object") {
      const fromDetail = nlFrom(body.detail || {}, state.advanced) || nlFrom(body, state.advanced);
      server = fromDetail || `${server}\n\n${pretty(body)}`;
    }
    if (error.status === 404) {
      server += "\n\n文字发送依赖 POST /listen/text（或 POST /text）。当前为 404 时多半是 Pi 上 Telbot 未更新，请同步代码并重启 telbot serve。";
    }
    state.messages.push({ id: uid(), isUser: false, text: server, createdAt: new Date().toISOString() });
  } finally {
    if (token === state.flight) {
      state.abort = null;
      state.flight = 0;
      updateSendButton();
      saveChat();
      renderMessages();
    }
  }
}

function cancelFlight(redo) {
  if (!state.abort) return;
  state.abort.abort();
  state.abort = null;
  state.flight = 0;
  state.messages = state.messages.filter((item) => !item.pending);
  state.messages.push({
    id: uid(),
    isUser: false,
    text: "你已让系统终止。",
    createdAt: new Date().toISOString(),
    redo,
  });
  saveChat();
  renderMessages();
  updateSendButton();
}

function resizePrompt() {
  el.prompt.style.height = "auto";
  el.prompt.style.height = `${Math.min(el.prompt.scrollHeight, 160)}px`;
}

async function beginVoice(event) {
  if (!state.connected || state.abort) return;
  event.preventDefault();
  state.holding = true;
  try { el.voiceHold.setPointerCapture(event.pointerId); } catch { /* 不支持时仍靠 pointerup */ }
  if (!navigator.mediaDevices || typeof MediaRecorder === "undefined") {
    setChatStatus("当前浏览器不支持录音，请先使用文字输入。");
    state.holding = false;
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!state.holding) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    state.voiceChunks = [];
    state.recorder = new MediaRecorder(stream);
    state.recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size) state.voiceChunks.push(ev.data);
    };
    state.recordStarted = Date.now();
    state.recorder.start();
    el.voiceHold.classList.add("recording");
    el.voiceHold.textContent = "松开 发送";
    setChatStatus("");
  } catch {
    state.holding = false;
    setChatStatus("需要麦克风权限才能录音。");
  }
}

async function endVoice() {
  if (!state.holding && !state.recorder) return;
  state.holding = false;
  el.voiceHold.classList.remove("recording");
  el.voiceHold.textContent = "按住 录音";
  const recorder = state.recorder;
  state.recorder = null;
  if (!recorder) return;
  const tooShort = Date.now() - state.recordStarted < 350;
  const blob = await new Promise((resolve) => {
    recorder.onstop = () => {
      recorder.stream.getTracks().forEach((track) => track.stop());
      resolve(new Blob(state.voiceChunks, { type: recorder.mimeType || "audio/webm" }));
    };
    if (recorder.state === "recording") recorder.stop();
    else resolve(null);
  });
  if (tooShort || !blob || !blob.size) {
    setChatStatus("按下时间过短，未开始录音。");
    return;
  }
  state.voiceBlob = blob;
  await uploadVoice(blob, true);
}

async function uploadVoice(blob, replaceUser) {
  if (!state.connected || state.abort) return;
  if (state.execute) {
    const ok = await confirmAction("将把这段语音作为真机指令发送。请确认镜筒与周边无阻碍。", "确认发送");
    if (!ok) return;
  }
  const token = ++state.flight;
  state.abort = new AbortController();
  const userId = uid();
  state.messages.push({ id: userId, isUser: true, text: "语音指令", createdAt: new Date().toISOString() });
  state.messages.push({ id: uid(), isUser: false, text: "正在听取指令并整理回复…", createdAt: new Date().toISOString(), pending: true });
  renderMessages();
  updateSendButton();
  const form = new FormData();
  const type = blob.type || "audio/webm";
  const ext = type.includes("wav") ? "wav" : type.includes("mp4") ? "m4a" : "webm";
  form.append("file", blob, `recording.${ext}`);
  try {
    const data = await api(`/listen/audio?execute=${state.execute}`, { method: "POST", body: form, signal: state.abort.signal });
    if (token !== state.flight) return;
    const transcript = String(data.transcript || "").trim() || "（未返回识别文字）";
    if (replaceUser) {
      const user = state.messages.find((item) => item.id === userId);
      if (user) user.text = transcript;
    }
    state.messages = state.messages.filter((item) => !item.pending);
    state.messages.push({
      id: uid(),
      isUser: false,
      text: `${assistantText(data)}${ingestTransit(data)}`,
      createdAt: new Date().toISOString(),
    });
    state.voiceBlob = null;
    setChatStatus("");
  } catch (error) {
    if (token !== state.flight || error.name === "AbortError") return;
    state.messages = state.messages.filter((item) => !item.pending);
    const transcript = error.data && (error.data.transcript || (error.data.detail && error.data.detail.transcript));
    const user = state.messages.find((item) => item.id === userId);
    if (user) user.text = transcript || "（上传失败）";
    let server = error.message || "语音上传失败";
    if (error.data && typeof error.data === "object") {
      const fromDetail = nlFrom(error.data.detail || {}, state.advanced);
      server = fromDetail || `${server}\n\n${pretty(error.data)}`;
    }
    state.messages.push({ id: uid(), isUser: false, text: server, createdAt: new Date().toISOString() });
  } finally {
    if (token === state.flight) {
      state.abort = null;
      state.flight = 0;
      updateSendButton();
      saveChat();
      renderMessages();
    }
  }
}

function redoVoice() {
  if (!state.voiceBlob) {
    setChatStatus("无法重做：语音缓存已失效，请重新录音。");
    return;
  }
  uploadVoice(state.voiceBlob, true);
}

function setCaptureMode(mode) {
  if (captureBusy()) return;
  state.captureMode = mode;
  storageSet("telbot.captureMode", mode);
  $$(".segments button").forEach((button) => {
    button.setAttribute("aria-selected", button.dataset.mode === mode ? "true" : "false");
  });
  el.livePane.classList.toggle("active", mode === "liveStack");
  el.calPane.classList.toggle("active", mode === "calibration");
  el.snapPane.classList.toggle("active", mode === "singleShot");
  if (mode === "liveStack") syncLiveIfRunning();
}

function captureBusy() {
  return state.live.running || state.cal.running || state.snap.running;
}

function renderCaptureLock() {
  const reason = captureReason();
  const locked = !canCapture();
  el.captureNotice.hidden = !reason;
  el.captureNotice.textContent = reason || "";
  for (const pane of [el.livePane, el.calPane, el.snapPane]) pane.classList.toggle("locked", locked);
  const off = locked || captureBusy();
  $$(".segments button").forEach((button) => { button.disabled = captureBusy(); });
  el.liveShutter.disabled = locked;
  el.snapShutter.disabled = locked || state.snap.running;
  el.snapAlbum.disabled = false;
  $("#liveAdvanced").disabled = locked || state.live.running;
  el.snapExposure.disabled = locked || state.snap.running;
  renderCal();
}

function setStatusBar(bar, label, pre, text, isError) {
  const value = String(text || "").trim();
  bar.hidden = !value;
  bar.classList.toggle("error", Boolean(isError));
  label.textContent = isError ? "状态（报错）" : "状态";
  pre.textContent = value;
}

function renderLive() {
  const text = state.live.error || state.live.status;
  setStatusBar(el.liveStatusBar, el.liveStatusLabel, el.liveStatus, text, Boolean(state.live.error));
  el.liveShutter.classList.toggle("stop", state.live.running);
  el.liveShutter.setAttribute("aria-label", state.live.running ? "终止边拍边叠" : "开始边拍边叠");
  if (state.live.previewUrl) {
    let img = el.liveStage.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.alt = "边拍边叠预览";
      el.liveStage.appendChild(img);
    }
    img.src = state.live.previewUrl;
    el.liveEmpty.hidden = true;
  }
  el.liveEmpty.hidden = Boolean(state.live.previewUrl);
  el.liveEmpty.textContent = state.live.running
    ? "Pi 正在曝光与叠加，首帧完成后将显示预览。"
    : "点击下方按钮开始边拍边叠，预览图将显示在此处。";
  renderCaptureLock();
}

async function syncLiveIfRunning() {
  if (!state.connected || !canCapture()) return;
  try {
    const status = await api("/camera/live-stack/status");
    if (status && status.running) {
      state.live.running = true;
      applyLiveStatus(status);
      startLivePoll();
    }
  } catch {
    /* 状态接口不可用时保持空闲 */
  }
}

function applyLiveStatus(status) {
  const frames = Number(status.frames_stacked || 0);
  if (status.running) {
    state.live.status = frames > 0 ? `叠加中 · 已叠 ${frames} 帧` : (status.message || "边拍边叠运行中…");
  } else if (status.message) state.live.status = status.message;
  state.live.running = Boolean(status.running);
}

function startLivePoll() {
  if (state.liveTimer) clearInterval(state.liveTimer);
  state.liveTimer = setInterval(pollLive, 1500);
  pollLive();
}
function stopLivePoll() {
  if (state.liveTimer) clearInterval(state.liveTimer);
  state.liveTimer = 0;
}
async function pollLive() {
  if (!state.connected) return;
  try {
    const status = await api("/camera/live-stack/status");
    applyLiveStatus(status || {});
    if (!state.live.running) stopLivePoll();
  } catch { /* 继续下一轮 */ }
  try {
    const response = await fetch(joinUrl(state.apiBase, `/camera/live-stack/preview?t=${Date.now()}`), { cache: "no-store", mode: "cors", credentials: "omit" });
    if (response.ok) {
      const blob = await response.blob();
      if (state.live.previewUrl) URL.revokeObjectURL(state.live.previewUrl);
      state.live.previewUrl = URL.createObjectURL(blob);
    }
  } catch { /* 预览未就绪 */ }
  renderLive();
}

async function toggleLive() {
  if (!canCapture()) return;
  if (state.live.running) {
    if (!(await confirmAction("停止边拍边叠？", "停止"))) return;
    try {
      await api("/camera/live-stack/stop", { method: "POST" });
      const status = await api("/camera/live-stack/status");
      applyLiveStatus(status || { running: false, message: "已停止边拍边叠" });
      if (!state.live.running) state.live.status = state.live.status || "已停止边拍边叠";
    } catch (error) {
      state.live.error = error.message;
    }
    stopLivePoll();
    renderLive();
    return;
  }
  if (!(await confirmAction("开始边拍边叠？这将真实曝光。", "开始"))) return;
  const exposure = numberOr($("#liveExposure").value, 2);
  const duration = numberOr($("#liveDuration").value, 86400);
  const cadenceRaw = $("#liveCadence").value.trim();
  const cadence = cadenceRaw ? Number(cadenceRaw) : 0;
  const tag = $("#liveTag").value.trim();
  const body = { duration_seconds: duration, exposure_seconds: exposure };
  if (cadence > 0) body.cadence_seconds = cadence;
  if (tag) body.session_tag = tag;
  state.live.error = "";
  try {
    await api("/camera/live-stack/start?execute=true", { method: "POST", body: JSON.stringify(body) });
    state.live.running = true;
    state.live.status = "边拍边叠已启动，等待第一帧…";
    startLivePoll();
  } catch (error) {
    if (error.status === 409) {
      state.live.running = true;
      state.live.error = error.message || "已有边拍边叠在运行";
      startLivePoll();
    } else {
      state.live.error = error.message;
      state.live.running = false;
    }
  }
  renderLive();
}

function numberOr(value, fallback) {
  const n = Number(String(value).trim().replace(",", "."));
  return Number.isFinite(n) ? n : fallback;
}

function durationHint(count, exposure) {
  const n = Math.max(1, count);
  const exp = Math.max(0, exposure);
  const settle = exp <= 0 ? 12 : 3;
  const fits = exp <= 0 ? 8 : 5;
  const per = exp + settle + 2 + fits;
  const total = n * per;
  const fmt = (seconds) => {
    const s = Math.max(1, Math.round(seconds));
    if (s < 60) return `${s} 秒`;
    const m = Math.floor(s / 60);
    const rem = s % 60;
    if (m < 60) return rem ? `${m} 分 ${rem} 秒` : `${m} 分钟`;
    const h = Math.floor(m / 60);
    const mr = m % 60;
    return mr ? `${h} 小时 ${mr} 分` : `${h} 小时`;
  };
  const expLabel = exp <= 0 ? "极短" : (Number.isInteger(exp) ? `${exp} 秒` : `${exp.toFixed(1)} 秒`);
  return `⏱ 预计耗时（仅供参考）\n本次约 ${fmt(total)}（共 ${n} 张，每张曝光 ${expLabel}，另含读出与保存，单张约 ${fmt(per)}）。\n实际可能因相机与网络略有出入。`;
}

function renderCal() {
  const text = state.cal.error || state.cal.status;
  setStatusBar(el.calStatusBar, el.calStatusLabel, el.calStatus, text, Boolean(state.cal.error));
  el.calBody.replaceChildren();
  if (state.cal.running) {
    const box = document.createElement("div");
    box.className = "cal-running";
    const p = document.createElement("p");
    p.textContent = state.cal.status || "正在拍摄…";
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "stop-wide";
    stop.textContent = "停止本次拍摄";
    stop.addEventListener("click", stopCal);
    box.append(p, stop);
    el.calBody.appendChild(box);
    return;
  }
  const intro = document.createElement("div");
  intro.className = "cal-intro";
  intro.innerHTML = "<p>先选一种要拍的照片类型。点开后会一步步告诉你在现场要做哪些准备，不需要天文背景也能看懂。</p><p>正式拍星空请用「拍单张」，不要在这里选亮场。</p>";
  el.calBody.appendChild(intro);
  for (const kind of calKinds) {
    const card = document.createElement("div");
    card.className = "cal-card";
    const title = document.createElement("strong");
    title.textContent = kind.title;
    const sub = document.createElement("span");
    sub.textContent = kind.subtitle;
    const open = document.createElement("button");
    open.type = "button";
    open.className = "cal-open";
    open.append(title, sub);
    if (!state.advanced) {
      const meta = document.createElement("em");
      const exp = kind.exposure;
      meta.textContent = `默认 ${kind.count} 张 · ${Number.isInteger(exp) ? String(exp) : String(exp)} 秒/张`;
      open.appendChild(meta);
    }
    open.disabled = !canCapture();
    open.addEventListener("click", () => openPrep(kind));
    card.appendChild(open);
    if (state.advanced) {
      const controls = document.createElement("div");
      controls.className = "cal-controls";
      const count = document.createElement("input");
      count.type = "number";
      count.min = "1";
      count.max = "999";
      count.value = String(kind.count);
      count.addEventListener("change", () => { kind.count = Math.max(1, Math.min(999, Number(count.value) || kind.count)); });
      const exposure = document.createElement("input");
      exposure.inputMode = "decimal";
      exposure.value = String(kind.exposure);
      exposure.addEventListener("change", () => { kind.exposure = Math.max(0, numberOr(exposure.value, kind.exposure)); });
      controls.append("张数 ", count, " 曝光（秒） ", exposure);
      card.appendChild(controls);
    }
    el.calBody.appendChild(card);
  }
  if (state.advanced) {
    const tag = document.createElement("label");
    tag.className = "field";
    tag.innerHTML = "会话后缀（可选，默认 HHMM）";
    const input = document.createElement("input");
    input.id = "calTag";
    input.placeholder = "例如 1129";
    input.value = storageGet("telbot.calTag") || "";
    input.addEventListener("change", () => storageSet("telbot.calTag", input.value));
    tag.appendChild(input);
    el.calBody.appendChild(tag);
  }
}

function openPrep(kind) {
  state.pendingKind = kind;
  el.prepTitle.textContent = `拍「${kind.title}」之前`;
  el.prepBody.textContent = `${kind.prep}\n\n${durationHint(kind.count, kind.exposure)}`;
  el.prepDialog.showModal();
}

async function startCal() {
  const kind = state.pendingKind;
  el.prepDialog.close();
  if (!kind || !canCapture()) return;
  const tagInput = $("#calTag");
  const tag = (tagInput && tagInput.value.trim()) || hhmm(new Date());
  state.cal.running = true;
  state.cal.error = "";
  state.cal.kind = kind.title;
  state.cal.status = `正在拍摄 ${kind.title}（${kind.count} 张）…请勿关闭页面`;
  renderCal();
  renderCaptureLock();
  const body = { count: kind.count, exposure_seconds: kind.exposure, session_tag: tag };
  try {
    await api(`/camera/cal/${kind.id}?execute=true`, { method: "POST", body: JSON.stringify(body) });
    state.cal.status = `${kind.title} 拍摄完成`;
  } catch (error) {
    if (error.name !== "AbortError") state.cal.error = error.message;
  } finally {
    state.cal.running = false;
    renderCal();
    renderCaptureLock();
  }
}

async function stopCal() {
  try {
    await api("/camera/cal/stop", { method: "POST" });
    state.cal.status = "已请求停止，当前帧结束后生效。";
  } catch (error) {
    state.cal.error = error.message;
  }
  renderCal();
}

function hhmm(date) {
  return `${String(date.getHours()).padStart(2, "0")}${String(date.getMinutes()).padStart(2, "0")}`;
}

function renderSnap() {
  const text = state.snap.error || state.snap.status;
  setStatusBar(el.snapStatusBar, el.snapStatusLabel, el.snapStatus, text, Boolean(state.snap.error));
  const latest = state.photos[0];
  let img = el.snapStage.querySelector("img");
  if (latest) {
    if (!img) {
      img = document.createElement("img");
      img.alt = "最近一张照片";
      el.snapStage.appendChild(img);
    }
    img.src = latest.url;
    el.snapEmpty.hidden = true;
  } else if (img) img.remove();
  if (!latest) el.snapEmpty.hidden = false;
  let busy = el.snapStage.querySelector(".stage-busy");
  if (state.snap.running) {
    if (!busy) {
      busy = document.createElement("div");
      busy.className = "stage-busy";
      el.snapStage.appendChild(busy);
    }
    busy.textContent = state.snap.status || "正在曝光…";
  } else if (busy) busy.remove();
  renderCaptureLock();
}

async function takeSnap() {
  if (!canCapture() || state.snap.running) return;
  const seconds = Math.max(0.05, Math.min(3600, numberOr(el.snapExposure.value, 0.5)));
  if (!(await confirmAction(`拍摄 ${seconds} 秒照片？这将真实曝光。`, "拍摄"))) return;
  state.snap.running = true;
  state.snap.error = "";
  state.snap.status = `正在曝光（约 ${Math.round(seconds)} 秒）…`;
  renderSnap();
  const body = JSON.stringify({ exposure_seconds: seconds });
  try {
    let data;
    try {
      data = await api(`/camera/snap?execute=true`, { method: "POST", body });
    } catch (error) {
      if (error.status !== 404) throw error;
      data = await api("/intent?execute=true", {
        method: "POST",
        body: JSON.stringify({ version: 1, action: "snap", exposure_seconds: seconds }),
      });
    }
    if (data && data.ok === false) throw new ApiError(data.message || "拍摄失败", 200, data);
    state.snap.status = "正在下载预览…";
    renderSnap();
    const blob = await fetchPreview();
    const url = URL.createObjectURL(blob);
    state.photos.unshift({ id: uid(), url, exposure: seconds });
    state.snap.status = "拍摄完成";
    state.snap.error = "";
  } catch (error) {
    state.snap.error = error.message || "拍摄失败";
    state.snap.status = "";
  } finally {
    state.snap.running = false;
    renderSnap();
    renderAlbum();
  }
}

async function fetchPreview() {
  let last = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const response = await fetch(joinUrl(state.apiBase, `/camera/snap/preview?t=${Date.now()}`), {
      cache: "no-store",
      mode: "cors",
      credentials: "omit",
    });
    if (response.ok) return response.blob();
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    last = new ApiError(extractError(data, response.status), response.status, data);
    const notReady = data && (data.error === "no_preview" || (data.detail && data.detail.error === "no_preview"));
    if (notReady && attempt < 11) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      continue;
    }
    throw last;
  }
  throw last || new ApiError("预览尚未就绪", 404, null);
}

function renderAlbum() {
  el.albumGrid.replaceChildren();
  if (!state.photos.length) {
    const p = document.createElement("p");
    p.className = "fine";
    p.textContent = "尚无照片。使用「拍单张」拍摄的照片会保存在本次浏览器会话中。";
    el.albumGrid.appendChild(p);
    return;
  }
  for (const photo of state.photos) {
    const img = document.createElement("img");
    img.alt = "拍摄的照片";
    img.src = photo.url;
    el.albumGrid.appendChild(img);
  }
}

function showsCancel(plan) {
  if (plan.status === "not_started") return true;
  if (plan.status === "observing") return Date.now() < new Date(plan.scheduledStart).getTime();
  return false;
}
function showsTerminate(plan) {
  return plan.status === "observing" && Date.now() >= new Date(plan.scheduledStart).getTime();
}
function isTerminal(plan) {
  return ["finished", "cancelled", "terminated"].includes(plan.status);
}

function renderPlanBadge() {
  el.planBadge.hidden = state.planBadge <= 0;
  el.planBadge.textContent = String(state.planBadge);
}

function renderPlans() {
  const has = state.plans.length > 0;
  el.planEmpty.hidden = has;
  el.planFilled.hidden = !has;
  const reason = planReason();
  el.planNotice.hidden = !has || !reason;
  el.planNotice.textContent = reason || "";
  const active = state.plans.some((plan) => !isTerminal(plan) && plan.piRunSubmitted);
  el.planPrecheck.hidden = !active;
  el.planList.replaceChildren();
  for (const plan of state.plans) {
    const card = document.createElement("article");
    card.className = "plan-card";
    const head = document.createElement("button");
    head.type = "button";
    head.className = "plan-head";
    head.innerHTML = `<span class="planet-mark" aria-hidden="true">◎</span>`;
    const meta = document.createElement("div");
    meta.className = "meta";
    const row = document.createElement("div");
    row.className = "plan-title-row";
    const name = document.createElement("strong");
    name.textContent = plan.planetName;
    const pill = document.createElement("span");
    pill.className = `pill ${plan.status}`;
    pill.textContent = statusTitle[plan.status] || plan.status;
    row.append(name, pill);
    const when = document.createElement("p");
    when.textContent = scheduleText(plan.scheduledStart);
    meta.append(row, when);
    head.append(meta);
    const open = plan.open;
    head.addEventListener("click", () => {
      plan.open = !plan.open;
      renderPlans();
    });
    card.appendChild(head);
    if (open) card.appendChild(planDetail(plan));
    el.planList.appendChild(card);
  }
}

function filterLabel(name) {
  const map = { Red: "Red（红）", Green: "Green（绿）", Blue: "Blue（蓝）", H_Alpha: "H-Alpha（哈）", SII: "SII（硫）", OIII: "OIII（氧）", LPR: "LPR（宽带）" };
  return map[name] || name || "未选择（默认）";
}

function planDetail(plan) {
  const box = document.createElement("div");
  box.className = "plan-detail";
  const add = (title, value) => {
    const row = document.createElement("div");
    row.className = "kv";
    const span = document.createElement("span");
    span.textContent = title;
    const strong = document.createElement("strong");
    strong.textContent = value;
    row.append(span, strong);
    box.appendChild(row);
  };
  add("观测开始", scheduleText(plan.scheduledStart));
  add("观测结束", plan.scheduledEnd ? scheduleText(plan.scheduledEnd) : "—");
  add("状态", statusTitle[plan.status] || plan.status);
  const editable = state.advanced && plan.status === "not_started" && canModifyPlans();
  if (state.advanced) {
    const exp = document.createElement("div");
    exp.className = "kv";
    const label = document.createElement("span");
    label.textContent = "曝光时间";
    if (editable) {
      const input = document.createElement("input");
      input.value = plan.exposureSeconds > 0 ? String(plan.exposureSeconds) : "";
      input.placeholder = "0";
      input.addEventListener("change", () => {
        const raw = input.value.trim();
        const seconds = raw === "" ? 0 : Math.min(3600, Math.max(0, numberOr(raw, plan.exposureSeconds)));
        plan.exposureSeconds = seconds;
        savePlans();
      });
      exp.append(label, input);
    } else {
      const strong = document.createElement("strong");
      strong.textContent = plan.exposureSeconds > 0 ? String(plan.exposureSeconds) : "默认";
      exp.append(label, strong);
    }
    box.appendChild(exp);
    const filter = document.createElement("div");
    filter.className = "kv";
    const fLabel = document.createElement("span");
    fLabel.textContent = "滤镜";
    const fValue = document.createElement("strong");
    if (!state.snapshot.filterWheel.connected) fValue.textContent = "未连接";
    else fValue.textContent = filterLabel(plan.selectedFilterName);
    filter.append(fLabel, fValue);
    if (editable && state.snapshot.filterWheel.connected) {
      const choose = document.createElement("button");
      choose.type = "button";
      choose.textContent = "选择";
      choose.addEventListener("click", () => openFilters(plan));
      filter.appendChild(choose);
    }
    box.appendChild(filter);
  }
  if (plan.error) {
    const err = document.createElement("p");
    err.className = "plan-error";
    err.textContent = plan.error;
    box.appendChild(err);
  }
  if (showsCancel(plan)) box.appendChild(planAction(plan, "取消计划", () => cancelPlan(plan)));
  else if (showsTerminate(plan)) box.appendChild(planAction(plan, "终止观测", () => terminatePlan(plan)));
  else if (!isTerminal(plan)) {
    const note = document.createElement("p");
    note.className = "fine";
    note.textContent = "该计划已结束或不可操作。";
    box.appendChild(note);
  }
  return box;
}

function planAction(plan, label, fn) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "danger-btn";
  button.textContent = plan.busy ? "请稍候…" : label;
  button.disabled = plan.busy || !canModifyPlans();
  button.addEventListener("click", fn);
  return button;
}

async function cancelPlan(plan) {
  if (!canModifyPlans()) {
    plan.error = planReason() || "无法修改计划：请先确认 Pi 已开机且已连接 Telbot 盒子（可在「设置 → 连接设备」中刷新）。";
    renderPlans();
    return;
  }
  if (!(await confirmAction(`取消「${plan.planetName}」？`, "取消计划"))) return;
  plan.busy = true;
  plan.error = "";
  renderPlans();
  try {
    if (plan.piRunSubmitted) {
      const status = await api("/plan/transit/status");
      if (status && status.running) {
        await api(`/plan/transit/abort?execute=true&reason=${encodeURIComponent("web user abort")}`, { method: "POST" });
      }
    }
    plan.status = "cancelled";
    plan.open = false;
  } catch (error) {
    plan.error = error.message;
  } finally {
    plan.busy = false;
    savePlans();
    renderPlans();
  }
}

async function terminatePlan(plan) {
  if (!canModifyPlans()) return;
  if (!(await confirmAction(`终止「${plan.planetName}」的观测？`, "终止观测"))) return;
  plan.busy = true;
  renderPlans();
  try {
    await api(`/plan/transit/abort?execute=true&reason=${encodeURIComponent("web user abort")}`, { method: "POST" });
    plan.status = "terminated";
    plan.open = false;
  } catch (error) {
    plan.error = error.message;
  } finally {
    plan.busy = false;
    savePlans();
    renderPlans();
  }
}

async function openFilters(plan) {
  state.filterPlanId = plan.id;
  el.filterList.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "fine";
  loading.textContent = "正在从 Pi 加载滤镜列表…";
  el.filterList.appendChild(loading);
  el.filterDialog.showModal();
  try {
    const data = await api("/filter/slots");
    const slots = Array.isArray(data.slots) ? data.slots : [];
    state.filterSlots = slots;
    el.filterList.replaceChildren();
    if (!slots.length) {
      loading.textContent = "没有可用滤镜。";
      el.filterList.appendChild(loading);
      return;
    }
    for (const slot of slots) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = filterLabel(slot.name);
      if (plan.selectedFilterName === slot.name) button.append(" ✓");
      button.addEventListener("click", () => {
        plan.selectedFilterName = slot.name;
        savePlans();
        el.filterDialog.close();
        renderPlans();
      });
      el.filterList.appendChild(button);
    }
  } catch (error) {
    loading.textContent = error.message;
  }
}

function ensurePlanPoll() {
  if (state.planTimer) return;
  if (!state.plans.some((plan) => !isTerminal(plan))) return;
  state.planTimer = setInterval(refreshPlans, 8000);
}

async function refreshPlans() {
  if (!state.connected) return;
  let status;
  try {
    status = await api("/plan/transit/status");
  } catch {
    return;
  }
  const running = Boolean(status && status.running);
  const sessionPath = status && status.session && status.session.plan;
  const pre = status && status.ingress_precheck;
  const now = Date.now();
  for (const plan of state.plans) {
    if (isTerminal(plan)) continue;
    if (pre && plan.piRunSubmitted && plan.precheckNotifiedCheckUtc !== pre.check_utc && planetsMatch(pre.planet, plan.planetName)) {
      notifyPrecheck(pre);
      plan.precheckNotifiedCheckUtc = pre.check_utc;
    }
    const pathMatches = sessionPath && sessionPath === plan.piPlanPath;
    if (running && (pathMatches || plan.piRunSubmitted)) {
      plan.status = now >= new Date(plan.scheduledStart).getTime() ? "observing" : "not_started";
      plan.piRunSubmitted = true;
    } else if (plan.piRunSubmitted && plan.status === "observing" && !running) {
      plan.status = "finished";
    } else if (plan.piRunSubmitted && plan.status === "not_started" && !running && plan.scheduledEnd) {
      if (now > new Date(plan.scheduledEnd).getTime() + 600000) plan.status = "finished";
    }
  }
  savePlans();
  renderPlans();
  if (!state.plans.some((plan) => !isTerminal(plan)) && state.planTimer) {
    clearInterval(state.planTimer);
    state.planTimer = 0;
  }
}

function notifyPrecheck(pre) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const planet = pre.planet || "凌星目标";
  if (pre.capture_ok) {
    const mins = Math.round(Number(pre.minutes_before_ingress || 10));
    new Notification(`预检通过 · 观测约 ${mins} 分钟后开始`, {
      body: `「${planet}」凌食前的测试拍照与板解正常，测试已通过。科学拍摄将按计划在约 ${mins} 分钟后自动开始，请保持 Pi 与网络在线。`,
    });
    return;
  }
  const alert = pre.user_alert || {};
  new Notification(alert.title || "预检未通过 · 请检查望远镜", { body: alert.message || `「${planet}」预检未通过。` });
}

function maybeAskNotify() {
  if (typeof Notification === "undefined" || Notification.permission !== "default") return;
  if (!state.plans.some((plan) => !isTerminal(plan) && plan.piRunSubmitted)) return;
  Notification.requestPermission().catch(() => {});
}

function renderEnvFields() {
  el.envFields.replaceChildren();
  for (const [section, rows] of envDefs) {
    const wrap = document.createElement("section");
    wrap.className = "env-section";
    const h = document.createElement("h3");
    h.textContent = section;
    wrap.appendChild(h);
    for (const [key, title, detail] of rows) {
      const row = document.createElement("div");
      row.className = "env-row";
      const label = document.createElement("label");
      label.textContent = title;
      label.htmlFor = `env-${key}`;
      const input = document.createElement("input");
      input.id = `env-${key}`;
      input.value = state.envValues[key] || "";
      input.disabled = !state.connected;
      input.placeholder = "未设置";
      input.addEventListener("change", () => commitEnv(key, title, input));
      const note = document.createElement("p");
      note.className = "fine";
      note.textContent = detail;
      row.append(label, input, note);
      wrap.appendChild(row);
    }
    el.envFields.appendChild(wrap);
  }
}

async function loadEnv() {
  if (!state.connected) {
    el.envStatus.textContent = "未连接，无法读取或写入。";
    renderEnvFields();
    return;
  }
  el.envStatus.textContent = "正在读取参数…";
  const keys = envDefs.flatMap(([, rows]) => rows.map(([key]) => key));
  const query = keys.map((key) => `keys=${encodeURIComponent(key)}`).join("&");
  try {
    const payload = await api(`/config/env?${query}`);
    state.envValues = (payload && payload.values) || {};
    state.envLoaded = true;
    el.envStatus.textContent = "";
  } catch (error) {
    el.envStatus.textContent = `读取参数失败：${error.message}`;
  }
  renderEnvFields();
}

async function commitEnv(key, title, input) {
  const value = input.value;
  if ((state.envValues[key] || "") === value) return;
  const ok = await confirmAction(`将「${title}」写回 .env 并立即生效？`, "写入");
  if (!ok) {
    input.value = state.envValues[key] || "";
    return;
  }
  try {
    const payload = await api("/config/env", { method: "PATCH", body: JSON.stringify({ updates: { [key]: value } }) });
    state.envValues = (payload && payload.values) || { ...state.envValues, [key]: value };
    el.envStatus.textContent = `已写入 ${title}`;
  } catch (error) {
    el.envStatus.textContent = error.message;
    input.value = state.envValues[key] || "";
  }
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    const prev = button.textContent;
    button.textContent = "已复制";
    setTimeout(() => { button.textContent = prev; }, 1500);
  } catch { /* 剪贴板不可用 */ }
}

function bind() {
  $("#menuButton").addEventListener("click", () => {
    document.body.classList.add("nav-open");
    $("#scrim").hidden = false;
  });
  $("#closeSidebar").addEventListener("click", closeNav);
  $("#scrim").addEventListener("click", closeNav);
  $$(".side-nav button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $$(".segments button").forEach((button) => button.addEventListener("click", () => setCaptureMode(button.dataset.mode)));

  el.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.abort) {
      cancelFlight(state.voiceMode ? { kind: "voice" } : { kind: "text", text: state.messages.filter((item) => item.isUser).slice(-1)[0]?.text || "" });
      return;
    }
    sendTyped(el.prompt.value);
  });
  el.prompt.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      el.composer.requestSubmit();
    }
  });
  el.prompt.addEventListener("input", () => {
    resizePrompt();
    updateSendButton();
  });
  el.micButton.addEventListener("click", () => {
    state.voiceMode = !state.voiceMode;
    el.prompt.hidden = state.voiceMode;
    el.voiceHold.hidden = !state.voiceMode;
    el.sendButton.hidden = state.voiceMode;
    el.micButton.setAttribute("aria-label", state.voiceMode ? "键盘" : "语音");
    updateSendButton();
  });
  el.voiceHold.addEventListener("pointerdown", beginVoice);
  el.voiceHold.addEventListener("pointerup", endVoice);
  el.voiceHold.addEventListener("pointercancel", endVoice);

  el.executeToggle.addEventListener("change", async () => {
    if (!state.connected) {
      el.executeToggle.checked = false;
      return;
    }
    if (el.executeToggle.checked) {
      const ok = await confirmAction("开启后将向赤道仪发送真实转动指令。请确认镜筒与周边（含电缆、人员与设备）均无阻碍，避免镜筒或三脚架发生碰撞、缠绕或损坏。", "确认开启");
      if (!ok) {
        el.executeToggle.checked = false;
        state.execute = false;
        storageSet("telbot.execute", "0");
        renderConnection();
        return;
      }
    }
    state.execute = el.executeToggle.checked;
    storageSet("telbot.execute", state.execute ? "1" : "0");
    renderConnection();
  });
  el.advancedToggle.addEventListener("change", () => {
    state.advanced = el.advancedToggle.checked;
    document.body.dataset.advanced = state.advanced ? "true" : "false";
    storageSet("telbot.advanced", state.advanced ? "1" : "0");
    renderCal();
    renderPlans();
  });
  el.redetect.addEventListener("click", () => {
    const typed = el.apiBase.value.trim();
    if (!typed) detect();
    else detect({ preferred: typed });
  });
  el.liveShutter.addEventListener("click", toggleLive);
  $("#liveAdvanced").addEventListener("click", () => $("#liveDialog").showModal());
  $("#liveCancel").addEventListener("click", () => $("#liveDialog").close());
  $("#liveDone").addEventListener("click", () => {
    storageSet("telbot.liveExposure", $("#liveExposure").value);
    storageSet("telbot.liveDuration", $("#liveDuration").value);
    storageSet("telbot.liveCadence", $("#liveCadence").value);
    storageSet("telbot.liveTag", $("#liveTag").value);
    $("#liveDialog").close();
  });
  $("#prepCancel").addEventListener("click", () => el.prepDialog.close());
  $("#prepStart").addEventListener("click", startCal);
  el.snapShutter.addEventListener("click", takeSnap);
  el.snapAlbum.addEventListener("click", () => {
    renderAlbum();
    el.albumDialog.showModal();
  });
  $("#albumClose").addEventListener("click", () => el.albumDialog.close());
  $("#filterClose").addEventListener("click", () => el.filterDialog.close());
  el.snapExposure.addEventListener("change", async () => {
    const seconds = Math.max(0.05, Math.min(3600, numberOr(el.snapExposure.value, 0.5)));
    el.snapExposure.value = String(seconds);
    storageSet("telbot.snapExposure", String(seconds));
    if (!canCapture()) return;
    try { await api("/camera/exposure?execute=true", { method: "POST", body: JSON.stringify({ exposure_seconds: seconds }) }); }
    catch (error) {
      if (error.status === 404) {
        try {
          await api(`/camera/exposure?execute=true`, { method: "PUT", body: JSON.stringify({ exposure_seconds: seconds }) });
        } catch (putError) {
          state.snap.error = putError.message;
          renderSnap();
        }
      } else {
        state.snap.error = error.message;
        renderSnap();
      }
    }
  });
  $("#liveCopy").addEventListener("click", () => copyText(el.liveStatus.textContent, $("#liveCopy")));
  $("#calCopy").addEventListener("click", () => copyText(el.calStatus.textContent, $("#calCopy")));
  $("#snapCopy").addEventListener("click", () => copyText(el.snapStatus.textContent, $("#snapCopy")));
}

function loadPrefs() {
  el.rememberApi.checked = storageGet(STORAGE_REMEMBER) === "1";
  const remembered = rememberedBase();
  if (remembered) el.apiBase.value = remembered;
  state.execute = storageGet("telbot.execute") === "1";
  state.advanced = storageGet("telbot.advanced") === "1";
  el.advancedToggle.checked = state.advanced;
  document.body.dataset.advanced = state.advanced ? "true" : "false";
  state.captureMode = storageGet("telbot.captureMode") || "liveStack";
  $("#liveExposure").value = storageGet("telbot.liveExposure") || "2";
  $("#liveDuration").value = storageGet("telbot.liveDuration") || "86400";
  $("#liveCadence").value = storageGet("telbot.liveCadence") || "";
  $("#liveTag").value = storageGet("telbot.liveTag") || "";
  el.snapExposure.value = storageGet("telbot.snapExposure") || "0.5";
  if (location.protocol === "https:") el.mixedHint.hidden = false;
  loadChat();
  loadPlans();
}

function init() {
  loadPrefs();
  bind();
  setCaptureMode(state.captureMode);
  renderMessages();
  renderPlans();
  renderPlanBadge();
  renderDevices();
  renderEnvFields();
  renderConnection();
  setTimeout(() => {
    el.splash.classList.add("done");
    setTimeout(() => el.splash.remove(), 320);
  }, 1600);
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
  detect();
}

init();
