"""
Rule-based Chinese text → VoiceIntentV1 (no ML).
Extend BODY_CN_TO_EN / keyword tuples as needed.
"""

from __future__ import annotations

import re
from typing import Literal

from telbot.models import VoiceIntentV1

NudgeDir = Literal["up", "down", "left", "right"]
FocuserDir = Literal["in", "out"]

_FOCUSER_AUTOFOCUS_RE = re.compile(
    r"(自动对焦|自动调焦|auto\s*focus|autofocus|帮.{0,6}(对焦|调焦)(?!.{0,8}(向前|向后|往前|往后|移动|移)))",
    re.IGNORECASE,
)
_FOCUSER_CTX = re.compile(r"电调|调焦|焦距|焦点|调焦器|focuser", re.IGNORECASE)
_CFW_CTX = re.compile(r"滤镜|滤光片|滤镜轮|filter\s*wheel|cfw", re.IGNORECASE)
_CFW_GOTO_RE = re.compile(
    r"(?:切换|换|切|改用|使用|调到|转到|旋到|旋至)"
    r"(?:到|为|成|至|去)?\s*(?P<name>.+?)(?:滤镜|滤光片|片)?\s*(?:[。.！!？?]|$)"
)
_CFW_SLOT_RE = re.compile(
    r"(?:切换|换|切|改用|使用|调到|转到|旋到|旋至)?"
    r"(?:到|为|成|至|去)?\s*(?:第)?(?P<slot>\d+)\s*号?\s*(?:槽|位|格|孔)?"
    r"(?:滤镜|滤光片|片)?\s*(?:[。.！!？?]|$)"
)
_FILTER_CN_TO_TOKEN: dict[str, str] = {
    "红": "red",
    "红色": "red",
    "绿": "green",
    "绿色": "green",
    "蓝": "blue",
    "蓝色": "blue",
    "哈": "ha",
    "ha": "ha",
    "氢阿尔法": "ha",
    "氢α": "ha",
    "hα": "ha",
    "硫": "sii",
    "氧": "oiii",
    "宽带": "lpr",
    "光害": "lpr",
}
_FOCUSER_STEPS_RE = re.compile(
    r"(?:移动|移|走|调)\s*(\d+)|(\d+)\s*(?:步|单位|格)"
)

# Chinese common names → Skyfield/ephem_body keys (see ephem_body._body aliases)
BODY_CN_TO_EN: dict[str, str] = {
    "木星": "jupiter",
    "火星": "mars",
    "土星": "saturn",
    "金星": "venus",
    "水星": "mercury",
    "天王星": "uranus",
    "海王星": "neptune",
    "月亮": "moon",
    "月球": "moon",
    "太阳": "sun",
}


def normalize_ephemeris_target(name: str) -> str:
    """中文太阳系天体名单独出现时转为 ephem_body / DE421 使用的英文键。"""
    t = name.strip()
    if not t:
        return t
    if t in BODY_CN_TO_EN:
        return BODY_CN_TO_EN[t]
    return t


_HELP_OBJ_BLOCKLIST = frozenset(
    {
        "你的功能",
        "你的能力",
        "你能做什么",
        "你都能做什么",
        "本系统的功能",
        "系统功能",
        "telbot的功能",
        "telbot功能",
        "使用方法",
        "使用说明",
        "功能",
        "能力",
        "用法",
    }
)

_HELP_RE = re.compile(
    r"(?:请(?:你)?)?(?:介绍|说说|讲讲)(?:一下)?(?:你的|本系统的|telbot的|系统的)?(?:功能|能力|用法|使用方法)"
    r"|你(?:能|会|可以)做什么"
    r"|有(?:什么|哪些)功能"
    r"|(?:怎么|如何)使用|使用说明|使用帮助"
    r"|^帮助$|^使用帮助$"
    r"|telbot(?:是|能|的)?.{0,10}(?:什么|干嘛|做什么|干什么)"
    r"|介绍一下(?:telbot|你)",
    re.IGNORECASE,
)


def _try_help(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if not _HELP_RE.search(text.strip()):
        return None
    return VoiceIntentV1(
        version=1,
        action="help",
        confidence=confidence,
        raw_text=raw_text,
    )


_DESCRIBE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:请(?:你)?)?(?:帮我)?(?:介绍一下|介绍|讲讲|说说|描述一下)\s*(?P<obj>.+?)(?:[。.！!？?]|$)"
    ),
    re.compile(r"(?P<obj>.+)\s*(?:是什么|是啥)(?:天体|星星|星云)?\s*[。.！!？?]*"),
)


def _try_describe(text: str, *, confidence: float) -> VoiceIntentV1 | None:
    raw = text.strip()
    if not raw:
        return None
    for i, pat in enumerate(_DESCRIBE_RES):
        if i == 1:
            m = pat.fullmatch(raw.strip())
        else:
            m = pat.search(raw)
        if not m:
            continue
        obj = re.sub(r"\s+", " ", m.group("obj").strip()).strip(' "\'「」')
        if len(obj) < 1:
            continue
        if obj.lower() in _HELP_OBJ_BLOCKLIST or obj in _HELP_OBJ_BLOCKLIST:
            continue
        nt = normalize_ephemeris_target(obj)
        return VoiceIntentV1(
            version=1,
            action="describe",
            target=nt,
            confidence=confidence,
            raw_text=raw,
        )
    return None


# Longer phrases first where helpful（勿单独用「停」作词：会误匹配「停车」归位）
ABORT_PHRASES: tuple[str, ...] = (
    "立刻停止",
    "立刻停",
    "马上停止",
    "马上停",
    "赶紧停",
    "快停",
    "停下",
    "停下来",
    "停住",
    "别动了",
    "别动",
    "中止",
    "急停",
    "停止跟踪",
    "暂停跟踪",
)
ABORT_WORDS: tuple[str, ...] = ("停止",)

# INDI 连接设备（CONNECTION.CONNECT=On；须在 park /「停车」子串之前匹配含「停车」的解除语）
CONNECT_PHRASES: tuple[str, ...] = (
    "连接望远镜",
    "连接赤道仪",
    "连上望远镜",
    "连上赤道仪",
    "连望远镜",
    "连赤道仪",
    "连接设备",
    "建立连接",
    "打开连接",
    "连一下望远镜",
    "连一下赤道仪",
    "indi连接",
    "连接indi",
    "连接 gemini",
    "连接gemini",
)

UNPARK_PHRASES: tuple[str, ...] = (
    "解除停车",
    "解锁停车",
    # 英文 ASR 常把 unpark 听成 on park / onpark
    "on park",
    "onpark",
    "un park",
)

# 校准 + 同步望远镜（须在普通 PLATESOLVE_PHRASES 之前匹配，避免「校准」子串抢先）
PLATESOLVE_SYNC_PHRASES: tuple[str, ...] = (
    "plate solve and sync",
    "platesolve and sync",
    "帮我校准并同步望远镜",
    "校准并同步望远镜",
    "校准后同步望远镜",
    "板校并同步望远镜",
    "解算并同步望远镜",
    "板校然后同步望远镜",
    "校准然后同步",
)

# 板解算 / 校准（须在 SNAP_PHRASES 与「拍N秒」解析之前，避免「校准拍5秒」误为 snap）
PLATESOLVE_PHRASES: tuple[str, ...] = (
    "plate solve",
    "plate-solve",
    "platesolve",
    "帮我板校一下",
    "帮我板校",
    "做一下板校",
    "做板校正",
    "板校正",
    "拍板校正",
    "天文图像校准",
    "天文校准",
    "望远镜校准",
    "校准一下望远镜",
    "校准一下",
    "图像校准",
    "帧校准",
    "天图校准",
    "做天图校准",
    "校准望远镜",
    "板校",
    "要校准",
    "校准",
)

# 须在 PARK_PHRASES 之前匹配（与 unpark 相同思路：先匹配更具体的拍照语）
SNAP_PHRASES: tuple[str, ...] = (
    "拍一张照片",
    "拍张照",
    "相机拍照",
    "开始拍照",
    "开始曝光",
    "拍一下照",
    "快门",
    "拍照",
)

PARK_PHRASES: tuple[str, ...] = (
    "回到初始",
    "初始位置",
    "归位",
    "停车",
    "回停车",
)

# 相对当前位置微移（赤经增大=向东/右，减小=向西/左；赤纬增大=向北/上）
# 带「转」的说法放前：ASR 常见「往左转一点」，子串不含「往左一点」。
NUDGE_PHRASES: tuple[tuple[str, NudgeDir], ...] = (
    ("往左转一点", "left"),
    ("向左转一点", "left"),
    ("左转一点", "left"),
    ("往右转一点", "right"),
    ("向右转一点", "right"),
    ("右转一点", "right"),
    ("往上转一点", "up"),
    ("向上转一点", "up"),
    ("上转一点", "up"),
    ("往下转一点", "down"),
    ("向下转一点", "down"),
    ("下转一点", "down"),
    ("再往左一点", "left"),
    ("再往右一点", "right"),
    ("再往上一点", "up"),
    ("再往下一点", "down"),
    ("往左一点", "left"),
    ("向左一点", "left"),
    ("左一点", "left"),
    ("往右一点", "right"),
    ("向右一点", "right"),
    ("右一点", "right"),
    ("往上一点", "up"),
    ("向上一点", "up"),
    ("上一点", "up"),
    ("往下一点", "down"),
    ("向下一点", "down"),
    ("下一点", "down"),
)


def _parse_snap_seconds(text: str) -> float | None:
    """从中文里解析曝光秒数，如「拍5秒」「曝光 3.5 秒」（勿匹配任意「数字+秒」以免误触）。"""
    m = re.search(r"(?:曝光|拍)\s*(\d+(?:\.\d+)?)\s*秒", text)
    if m:
        return float(m.group(1))
    return None


def _try_platesolve(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    """plate solve / 板校 / 校准 等 → action=platesolve（执行层：先曝光再 ASTAP）；可选同步对准。"""
    raw = text.strip()
    if not raw:
        return None
    tl = raw.lower()
    for phrase in PLATESOLVE_SYNC_PHRASES:
        if phrase in raw or phrase.lower() in tl:
            sec = _parse_snap_seconds(raw)
            return VoiceIntentV1(
                version=1,
                action="platesolve",
                exposure_seconds=sec,
                platesolve_align="sync",
                confidence=confidence,
                raw_text=raw_text,
            )
    if re.search(r"\b(platesolve|plate\s+solve)\b.*\bsync\b", tl) or re.search(r"\bsync\b.*\b(platesolve|plate\s+solve)\b", tl):
        sec = _parse_snap_seconds(raw)
        return VoiceIntentV1(
            version=1,
            action="platesolve",
            exposure_seconds=sec,
            platesolve_align="sync",
            confidence=confidence,
            raw_text=raw_text,
        )
    if re.search(r"\b(platesolve|plate-solve|plate\s+solve)\b", tl):
        sec = _parse_snap_seconds(raw)
        return VoiceIntentV1(
            version=1,
            action="platesolve",
            exposure_seconds=sec,
            confidence=confidence,
            raw_text=raw_text,
        )
    for phrase in PLATESOLVE_PHRASES:
        if phrase in raw:
            sec = _parse_snap_seconds(raw)
            return VoiceIntentV1(
                version=1,
                action="platesolve",
                exposure_seconds=sec,
                confidence=confidence,
                raw_text=raw_text,
            )
    return None


def _goto_hint_re(text: str) -> re.Match[str] | None:
    return re.search(
        r"(看|指向|去|到|对准|找|观测|GOTO|goto)",
        text,
        re.IGNORECASE,
    )


# 整句「连接」类：避免子串误匹配「断开连接」「网络连接」等
_CN_CONNECT_STANDALONE = re.compile(
    r"(请帮我|请麻烦|请|帮我|麻烦)?(连接|连上|连一下)",
)


def _intent_connect_standalone(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    """ASR 常见「连 接」带空格：去空白后再匹配整句。"""
    compact_zh = re.sub(r"\s+", "", text.strip().rstrip("。.！!？?，,"))
    if _CN_CONNECT_STANDALONE.fullmatch(compact_zh):
        return VoiceIntentV1(
            version=1,
            action="connect",
            confidence=confidence,
            raw_text=raw_text,
        )
    en = text.strip().rstrip("。.！!?")
    if re.fullmatch(r"connect(\s+please)?", en, re.IGNORECASE):
        return VoiceIntentV1(
            version=1,
            action="connect",
            confidence=confidence,
            raw_text=raw_text,
        )
    return None


def _find_body(text: str) -> str | None:
    """Return English body key if any known Chinese name appears in text."""
    for cn, en in BODY_CN_TO_EN.items():
        if cn in text:
            return en
    return None


def _parse_focuser_direction(text: str) -> FocuserDir | None:
    if re.search(r"向前|往前|往外|伸出|向外|outward|out\b", text, re.IGNORECASE):
        return "out"
    if re.search(r"向后|往后|往里|缩回|向内|inward|in\b", text, re.IGNORECASE):
        return "in"
    return None


def _parse_focuser_steps(text: str) -> int | None:
    m = _FOCUSER_STEPS_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n > 0 else None


def _try_focuser(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if _FOCUSER_AUTOFOCUS_RE.search(text):
        sec = _parse_snap_seconds(text)
        return VoiceIntentV1(
            version=1,
            action="focuser_autofocus",
            exposure_seconds=sec,
            confidence=confidence,
            raw_text=raw_text,
        )
    if not _FOCUSER_CTX.search(text):
        return None
    steps = _parse_focuser_steps(text)
    direction = _parse_focuser_direction(text)
    if steps is not None and direction is not None:
        return VoiceIntentV1(
            version=1,
            action="focuser_rel",
            focuser_direction=direction,
            focuser_steps=steps,
            confidence=confidence,
            raw_text=raw_text,
        )
    if re.search(
        r"(查询|查看|读取|读|告诉|报|查).{0,12}(位置|行程|焦距|焦点)"
        r"|(位置|行程|焦距).{0,8}(多少|几|是多少)"
        r"|当前.{0,6}(电调|调焦|焦距|焦点).{0,6}位置"
        r"|电调.{0,6}位置",
        text,
    ):
        return VoiceIntentV1(
            version=1,
            action="focuser_position",
            confidence=confidence,
            raw_text=raw_text,
        )
    return None


def _normalize_filter_target(raw: str) -> str:
    t = raw.strip()
    if not t:
        return t
    t = re.sub(r"(?:滤镜|滤光片|片)$", "", t).strip()
    if t in _FILTER_CN_TO_TOKEN:
        return _FILTER_CN_TO_TOKEN[t]
    if t.isascii():
        return t.lower()
    return t


def _parse_cfw_goto_target(text: str) -> str | None:
    m = _CFW_SLOT_RE.search(text)
    if m:
        return m.group("slot")
    m = _CFW_GOTO_RE.search(text)
    if m:
        name = _normalize_filter_target(m.group("name"))
        if name:
            return name
    m = re.search(
        r"(?P<name>[A-Za-z][A-Za-z0-9_\-]*|H[_\-]?Alpha|SII|OIII|LPR|Red|Green|Blue)"
        r"\s*(?:滤镜|滤光片|片)?\s*(?:[。.！!？?]|$)",
        text,
        re.IGNORECASE,
    )
    if m:
        return _normalize_filter_target(m.group("name"))
    return None


_PREFLIGHT_RE = re.compile(
    r"(设备就绪|就绪诊断|preflight|"
    r"检查.{0,8}(设备|连接|就绪)|"
    r"诊断.{0,8}设备|"
    r"设备.{0,6}(检查|诊断|就绪))",
    re.IGNORECASE,
)

_USB_DEVICES_RE = re.compile(
    r"(查询|查看|列出|告诉|报|查|有哪些|有什么)"
    r".{0,24}(连接|接上|插入|插在|连到|连接到|连在)"
    r".{0,16}(设备|硬件|usb|USB)"
    r"|"
    r"(设备|硬件|usb|USB).{0,16}(连接|接上|插入|插在|连到)"
    r"|"
    r"(树莓派|树莓|pi|raspberry).{0,20}(设备|硬件|usb|USB|连接)"
    r"|"
    r"(哪些|什么).{0,12}设备.{0,16}(连|接|在).{0,12}(pi|树莓派|树莓)?"
    r"|"
    r"当前.{0,12}(有哪些|有什么).{0,12}(设备|usb|USB)",
    re.IGNORECASE,
)


# 「可观测」中的「观测」不算动词
_OBSERVE_VERB = r"(?<![可])观测|观察"

_EXOPLANET_TRANSITS_RE = re.compile(
    r"(系外行星|exoplanet).{0,32}(凌星|凌日|transit)"
    r"|"
    r"(凌星|凌日).{0,20}(系外行星|exoplanet)"
    r"|"
    r"(今晚|今夜).{0,32}(系外行星|凌星|凌日)"
    r"|"
    r"(今晚|今夜).{0,20}(有哪些|有什么|查询|列出).{0,28}(系外行星|凌星|凌日|观测)"
    r"|"
    r"(有哪些|有什么|查询|列出).{0,16}(今晚|今夜).{0,28}(系外行星|凌星|凌日)"
    r"|"
    r"(查询|列出).{0,12}(今晚|今夜).{0,20}(系外行星|凌星|凌日)"
    r"|"
    r"(查询|列出).{0,12}(凌星|凌日).{0,16}(今晚|今夜|系外行星)"
    r"|"
    rf"(系外行星|凌星).{{0,16}}({_OBSERVE_VERB}).{{0,16}}(事件|机会|有哪些|今晚|今夜)"
    r"|"
    r"tonight.{0,24}(exoplanet|transit).{0,24}(event|observable|list)?",
    re.IGNORECASE,
)

_PLAN_EXOPLANET_TRANSIT_RE = re.compile(
    r"(?:帮我|请帮(?:我|忙)?|请)?\s*(?:规划|计划|安排)\s*"
    r"(?:第\s*[\d一二三四五六七八九十]+\s*个?|第一个|第二个|第三个|第四个|第五个)"
    r"|"
    r"(?:帮我|请帮(?:我|忙)?|请)?\s*(?:规划|计划|安排)\s*(?:今晚|今夜)?\s*(?:的)?\s*凌星"
    r"|"
    r"(规划|计划|安排).{0,24}(凌星|凌日|transit)"
    r"|"
    r"(凌星|凌日).{0,16}(规划|计划|观测计划)"
    r"|"
    rf"(今晚|今夜).{{0,16}}({_OBSERVE_VERB}).{{0,24}}(凌星|凌日|transit|系外行星)"
    r"|"
    r"plan.{0,12}(transit|exoplanet).{0,12}(observ|tonight|watch)"
    r"|"
    r"(帮我|请帮(?:我|忙)?|请).{0,10}(规划|计划).{0,28}"
    r"(第\s*[\d一二三四五六七八九十]+\s*个?|第一个|第二个|第三个|事件\s*[A-Z]|WASP|HD\s*\d|TOI\s*[-\d])",
    re.IGNORECASE,
)

_GOTO_CAPTURE_RE = re.compile(
    r"(?:请(?:你)?)?(?:帮(?:我|忙)?)?(?:把)?(?:望远镜|镜筒|赤道仪)?"
    r"(?:指向|对准|转到|转至|转去|转一下|去|到|看|观测|找(?:一下|下)?|GOTO|goto|带我去|看看?)"
    r"\s*"
    r"(?P<obj>"
    r"(?:HIP|HD|HR)\s*\d+|"
    r"(?:NGC|IC)\s*\d+[A-Za-z]?|"
    r"Messier\s*\d+|"
    r"M\s*\d+|"
    r"[\u4e00-\u9fff]{2,32}|"
    r"[^\s，。、]{1,48})",
    re.IGNORECASE,
)

_GOTO_WANT_RE = re.compile(
    r"(?:我要|我想)(?:看|观测)\s*"
    r"(?P<obj>[\u4e00-\u9fff]{1,12}|"
    r"(?:HIP|HD|HR)\s*\d+|(?:NGC|IC)\s*\d+[A-Za-z]?|Messier\s*\d+|M\s*\d+)",
    re.IGNORECASE,
)

_CATALOG_ID_GOTO_RE = re.compile(
    r"^(?:HIP|HD|HR)\s*\d+|(?:NGC|IC)\s*\d+[A-Za-z]?|Messier\s*\d+|M\s*\d+$",
    re.IGNORECASE,
)

_GOTO_TARGET_BLOCKLIST = frozenset(
    {
        "某个",
        "某个目标",
        "目标",
        "天体",
        "星星",
        "星体",
        "一下",
        "那个",
        "这个",
        "哪颗",
        "哪个",
        "什么",
    }
)

_GOTO_VAGUE_RE = re.compile(r"某个|哪(?:个|颗)|什么目标", re.IGNORECASE)

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _parse_event_index(text: str) -> int | None:
    ord_cn = {
        "第一个": 1,
        "第二个": 2,
        "第三个": 3,
        "第四个": 4,
        "第五个": 5,
    }
    for phrase, n in ord_cn.items():
        if phrase in text:
            return n
    m = re.search(r"第\s*(\d+)\s*个?", text)
    if m:
        return int(m.group(1))
    m = re.search(r"第\s*([一二三四五六七八九十]+)\s*个?", text)
    if m:
        s = m.group(1)
        if s == "十":
            return 10
        if len(s) == 2 and s[0] == "十" and s[1] in _CN_NUM:
            return 10 + _CN_NUM[s[1]]
        if len(s) == 2 and s[1] == "十" and s[0] in _CN_NUM:
            return _CN_NUM[s[0]] * 10
        return _CN_NUM.get(s)
    m = re.search(r"事件\s*([A-Z])\b", text, re.IGNORECASE)
    if m:
        return ord(m.group(1).upper()) - ord("A") + 1
    return None


def _parse_planet_name(text: str) -> str | None:
    for pat in (
        r"(WASP[-\s]?\d+\s*[a-z]?(?:\s*b)?)",
        r"(HD\s*\d+\s*[a-z]?(?:\s*b)?)",
        r"(TOI[-\s]?\d+\.?\d*\s*[a-z]?)",
        r"(KELT[-\s]?\d+\s*[a-z]?(?:\s*b)?)",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1).strip())
    return None


def _try_plan_exoplanet_transit(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if not _PLAN_EXOPLANET_TRANSIT_RE.search(text):
        return None
    has_plan_kw = bool(re.search(r"(规划|计划|安排|观测计划)", text, re.IGNORECASE))
    has_tonight_observe = bool(
        re.search(
            rf"(今晚|今夜).{{0,16}}({_OBSERVE_VERB}).{{0,32}}(凌星|凌日|transit|系外行星)",
            text,
            re.IGNORECASE,
        )
    )
    has_named_planet = _parse_planet_name(text) is not None
    if _EXOPLANET_TRANSITS_RE.search(text) and not (
        has_plan_kw or has_tonight_observe or has_named_planet
    ):
        return None
    idx = _parse_event_index(text)
    planet = _parse_planet_name(text)
    if idx is None and not planet:
        idx = 1
    return VoiceIntentV1(
        version=1,
        action="plan_exoplanet_transit",
        target=planet,
        event_index=idx,
        confidence=confidence,
        raw_text=raw_text,
    )


def _try_exoplanet_transits(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if not _EXOPLANET_TRANSITS_RE.search(text):
        return None
    return VoiceIntentV1(
        version=1,
        action="exoplanet_transits",
        confidence=confidence,
        raw_text=raw_text,
    )


def _try_preflight(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if not _PREFLIGHT_RE.search(text):
        return None
    if _USB_DEVICES_RE.search(text) and "就绪" not in text and "诊断" not in text:
        return None
    return VoiceIntentV1(
        version=1,
        action="preflight",
        confidence=confidence,
        raw_text=raw_text,
    )


def _try_usb_devices(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if re.search(r"望远镜|赤道仪|indi\s*connect|connect\s+the\s+mount", text, re.IGNORECASE):
        return None
    if not _USB_DEVICES_RE.search(text):
        return None
    return VoiceIntentV1(
        version=1,
        action="usb_devices",
        confidence=confidence,
        raw_text=raw_text,
    )


def _try_cfw(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    if not _CFW_CTX.search(text):
        return None
    if re.search(
        r"(查询|查看|读取|读|告诉|报|查).{0,12}(当前|现在|正在|目前).{0,8}(滤镜|滤光片|片)"
        r"|(当前|现在|正在|目前).{0,8}(滤镜|滤光片|片).{0,8}(是什么|哪个|几号|多少)"
        r"|(滤镜|滤光片).{0,8}(是什么|哪个|几号)",
        text,
    ):
        return VoiceIntentV1(
            version=1,
            action="cfw_current",
            confidence=confidence,
            raw_text=raw_text,
        )
    if re.search(
        r"(有哪些|有什么|列出|列表|全部|所有|可用).{0,12}(滤镜|滤光片)"
        r"|(滤镜|滤光片).{0,12}(有哪些|有什么|列表|清单)",
        text,
    ):
        return VoiceIntentV1(
            version=1,
            action="cfw_list",
            confidence=confidence,
            raw_text=raw_text,
        )
    if re.search(r"切换|换|切|改用|使用|调到|转到|旋到|旋至", text):
        target = _parse_cfw_goto_target(text)
        if target:
            return VoiceIntentV1(
                version=1,
                action="cfw_goto",
                target=target,
                confidence=confidence,
                raw_text=raw_text,
            )
    return None


def _parse_nudge(text: str, *, confidence: float) -> VoiceIntentV1 | None:
    for phrase, direction in NUDGE_PHRASES:
        if phrase in text:
            return VoiceIntentV1(
                version=1,
                action="nudge",
                nudge_direction=direction,
                confidence=confidence,
                raw_text=text,
            )
    return None


def _clean_goto_target(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw.strip()).strip("。，！？.!?、 ")
    t = re.sub(r"^(?:一下|下|那个|这个)\s*", "", t).strip()
    return t


def _normalize_catalog_target(name: str) -> str:
    """M31 / m 31 → M31；NGC7000 → NGC 7000（保留用户可识别的写法）。"""
    t = name.strip()
    m = re.fullmatch(r"m\s*(\d+)", t, re.IGNORECASE)
    if m:
        return f"M{m.group(1)}"
    m = re.fullmatch(r"(ngc|ic)\s*(\d+[a-z]?)", t, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}"
    m = re.fullmatch(r"(hip|hd|hr)\s*(\d+)", t, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}"
    return t


def _is_catalog_id_target(name: str) -> bool:
    return bool(_CATALOG_ID_GOTO_RE.match(_normalize_catalog_target(name)))


def _try_goto(text: str, *, confidence: float, raw_text: str) -> VoiceIntentV1 | None:
    """指向/转到某天体：太阳系中文名、星表编号、或 catalog.find_star 可解析的名称。"""
    if _GOTO_VAGUE_RE.search(text):
        return None

    body = _find_body(text)
    if body is not None and _goto_hint_re(text):
        return VoiceIntentV1(
            version=1,
            action="goto",
            target=body,
            confidence=confidence,
            raw_text=raw_text,
        )

    for pat in (_GOTO_CAPTURE_RE, _GOTO_WANT_RE):
        m = pat.search(text)
        if not m:
            continue
        name = _clean_goto_target(m.group("obj"))
        if not name or name in _GOTO_TARGET_BLOCKLIST:
            continue
        name = _normalize_catalog_target(name)
        if _is_catalog_id_target(name):
            return VoiceIntentV1(
                version=1,
                action="goto",
                target=name,
                confidence=confidence,
                raw_text=raw_text,
            )
        nt = normalize_ephemeris_target(name)
        if nt in BODY_CN_TO_EN.values():
            return VoiceIntentV1(
                version=1,
                action="goto",
                target=nt,
                confidence=confidence,
                raw_text=raw_text,
            )
        try:
            from telbot.catalog import find_star

            find_star(name)
        except FileNotFoundError:
            if re.fullmatch(r"[\u4e00-\u9fff]{2,32}", name):
                return VoiceIntentV1(
                    version=1,
                    action="goto",
                    target=name,
                    confidence=confidence,
                    raw_text=raw_text,
                )
            continue
        except KeyError:
            continue
        return VoiceIntentV1(
            version=1,
            action="goto",
            target=name,
            confidence=confidence,
            raw_text=raw_text,
        )
    return None


def _try_goto_star(text: str, *, confidence: float) -> VoiceIntentV1 | None:
    """Backward-compatible alias for tests."""
    return _try_goto(text, confidence=confidence, raw_text=text)


def parse_intent_zh(text: str, *, confidence: float = 0.95) -> VoiceIntentV1 | None:
    """
    Map Chinese user text to VoiceIntentV1, or None if unrecognized.

    Priority: abort → connect → unpark → platesolve → snap → park → focuser → cfw → plan_exoplanet_transit → exoplanet_transits → usb_devices → help → nudge → describe → goto → None
    """
    raw = text.strip()
    if not raw:
        return None

    t = raw
    # Abort before park ("停止" is broad — check phrases first)
    for phrase in ABORT_PHRASES:
        if phrase in t:
            return VoiceIntentV1(
                version=1,
                action="abort",
                confidence=confidence,
                raw_text=raw,
            )
    for w in ABORT_WORDS:
        if w in t:
            return VoiceIntentV1(
                version=1,
                action="abort",
                confidence=confidence,
                raw_text=raw,
            )

    conn_stand = _intent_connect_standalone(t, confidence=confidence, raw_text=raw)
    if conn_stand is not None:
        return conn_stand

    if re.search(
        r"\bconnect(\s+the)?\s+(telescope|mount|gemini|indi)\b",
        t,
        re.IGNORECASE,
    ) or re.search(r"\bindi\s+connect\b", t, re.IGNORECASE):
        return VoiceIntentV1(
            version=1,
            action="connect",
            confidence=confidence,
            raw_text=raw,
        )
    if re.search(r"\bconnect\b", t, re.IGNORECASE):
        return VoiceIntentV1(
            version=1,
            action="connect",
            confidence=confidence,
            raw_text=raw,
        )
    for phrase in CONNECT_PHRASES:
        if phrase in t:
            return VoiceIntentV1(
                version=1,
                action="connect",
                confidence=confidence,
                raw_text=raw,
            )

    tl = t.lower()
    if re.search(r"\bunpark\b", tl):
        return VoiceIntentV1(
            version=1,
            action="unpark",
            confidence=confidence,
            raw_text=raw,
        )
    for phrase in UNPARK_PHRASES:
        if phrase.lower() in tl:
            return VoiceIntentV1(
                version=1,
                action="unpark",
                confidence=confidence,
                raw_text=raw,
            )

    pl = _try_platesolve(t, confidence=confidence, raw_text=raw)
    if pl is not None:
        return pl

    snap_sec = _parse_snap_seconds(t)
    goto_hint = _goto_hint_re(t)
    if snap_sec is not None and not (goto_hint and _find_body(t) is not None):
        return VoiceIntentV1(
            version=1,
            action="snap",
            exposure_seconds=snap_sec,
            confidence=confidence,
            raw_text=raw,
        )
    if re.search(r"\b(take\s+(a\s+)?photo|snap(\s+a\s+)?picture)\b", tl) and not (
        goto_hint and _find_body(t) is not None
    ):
        return VoiceIntentV1(
            version=1,
            action="snap",
            exposure_seconds=snap_sec,
            confidence=confidence,
            raw_text=raw,
        )
    for phrase in SNAP_PHRASES:
        if phrase in t and not (goto_hint and _find_body(t) is not None):
            return VoiceIntentV1(
                version=1,
                action="snap",
                exposure_seconds=snap_sec,
                confidence=confidence,
                raw_text=raw,
            )

    for phrase in PARK_PHRASES:
        if phrase in t:
            return VoiceIntentV1(
                version=1,
                action="park",
                confidence=confidence,
                raw_text=raw,
            )

    foc = _try_focuser(t, confidence=confidence, raw_text=raw)
    if foc is not None:
        return foc

    cfw = _try_cfw(t, confidence=confidence, raw_text=raw)
    if cfw is not None:
        return cfw

    plan_tr = _try_plan_exoplanet_transit(t, confidence=confidence, raw_text=raw)
    if plan_tr is not None:
        return plan_tr

    exo = _try_exoplanet_transits(t, confidence=confidence, raw_text=raw)
    if exo is not None:
        return exo

    pre = _try_preflight(t, confidence=confidence, raw_text=raw)
    if pre is not None:
        return pre

    usb_dev = _try_usb_devices(t, confidence=confidence, raw_text=raw)
    if usb_dev is not None:
        return usb_dev

    help_intent = _try_help(t, confidence=confidence, raw_text=raw)
    if help_intent is not None:
        return help_intent

    nudge = _parse_nudge(t, confidence=confidence)
    if nudge is not None:
        return nudge

    describe = _try_describe(t, confidence=confidence)
    if describe is not None:
        return describe

    goto = _try_goto(t, confidence=confidence, raw_text=raw)
    if goto is not None:
        return goto

    return None
