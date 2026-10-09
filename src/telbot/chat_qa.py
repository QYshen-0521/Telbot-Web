"""Project-aware astronomy Q&A for the Web console.

Command/control still goes through VoiceIntentV1.  This module answers general
questions without moving hardware, and can optionally call an OpenAI-compatible
chat model when TELBOT_LLM_API_KEY or TELBOT_OPENAI_API_KEY is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from telbot.config import Settings
from telbot.health_devices import build_health_devices


@dataclass(frozen=True)
class QaTopic:
    keywords: tuple[str, ...]
    title: str
    answer: str


PROJECT_CONTEXT = (
    "Telbot 是一个树莓派/本机上的天文设备控制项目。网页是静态壳：没有后端时只能浏览介绍；"
    "检测到 GET /health 成功后，同一页面才启用控制。"
    "FastAPI 后端提供 HTTP API；后端通过 INDI 连接赤道仪、相机、滤镜轮和电调。"
    "核心功能包括自然语言控制、GOTO 指向、拍照、plate solve、对焦、滤镜、边拍边叠、校准帧、"
    "系外行星凌星计划、设备健康检查和安全的干跑/真机执行切换。"
)


TOPICS: tuple[QaTopic, ...] = (
    QaTopic(
        ("telbot", "你是谁", "能做什么", "功能", "网站", "web", "companion", "前端", "后端"),
        "Telbot 项目整体框架",
        (
            "Telbot 可以理解成“天文设备的大脑和遥控台”。网站在树莓派离线时仍可浏览介绍；"
            "GET /health 成功后，才能在网页里打字、说话或点拍照。"
            "FastAPI 后端接收请求；后端把自然语言变成结构化意图；真正控制硬件时，再通过 INDI 给赤道仪、"
            "相机、滤镜轮、电调等设备下命令。默认是干跑模式，不会真的动设备。"
        ),
    ),
    QaTopic(
        ("indi", "indiserver", "indi_getprop", "indi_setprop", "驱动", "driver"),
        "INDI 是什么",
        (
            "INDI 是天文设备的通用驱动协议和服务层。你可以把它想成“天文设备的翻译官”：Telbot 不需要直接懂"
            "每个厂家的私有协议，而是通过 INDI 读写属性。indi_getprop 用来读状态，indi_setprop 用来下发连接、"
            "GOTO、曝光、滤镜切换等命令。"
        ),
    ),
    QaTopic(
        ("树莓派", "raspberry", "pi", "部署", "systemd", "开机", "后台", "powershell", "服务器"),
        "树莓派和本地服务器",
        (
            "开发时你在电脑上运行 telbot serve，相当于临时启动一个网站服务器。部署到树莓派后，通常用 systemd "
            "让 Telbot 开机自动在后台运行。浏览器访问树莓派地址，网页请求后端，后端再控制本地连接的天文设备。"
        ),
    ),
    QaTopic(
        ("赤道仪", "望远镜", "mount", "goto", "转动", "指向", "跟踪", "追踪", "park", "unpark"),
        "赤道仪 / GOTO / 跟踪",
        (
            "赤道仪负责转动望远镜并抵消地球自转，让目标尽量停在画面里。GOTO 是让赤道仪转到指定天体或坐标；"
            "park 是回到停车位，unpark 是解除停车。真实执行前要确认镜筒、线缆、人员和周围环境安全。"
        ),
    ),
    QaTopic(
        ("ra", "dec", "赤经", "赤纬", "坐标", "jnow", "j2000", "高度角", "方位角", "alt", "az"),
        "天球坐标怎么理解",
        (
            "RA/Dec 是天球坐标，类似地球经纬度。RA 赤经常用小时表示，Dec 赤纬用角度表示。J2000 是一个标准"
            "参考历元，JNOW 是考虑岁差等因素后的当前视位置。高度角/方位角是从你所在地点看天空的位置：高度角"
            "越高越适合观测，方位角表示目标在东南西北哪个方向。"
        ),
    ),
    QaTopic(
        ("太阳系", "行星", "水星", "金星", "地球", "火星", "木星", "土星", "天王星", "海王星", "月亮", "月球", "彗星"),
        "太阳系目标",
        (
            "太阳系目标包括月亮、行星、彗星和太阳等。它们相对恒星的位置会明显变化，所以需要用星历计算当前坐标。"
            "月亮和行星通常较亮，适合短曝光或视频幸运成像；彗星亮度变化大，常需要查实时星历和曝光测试。"
        ),
    ),
    QaTopic(
        ("恒星", "双星", "变星", "北极星", "天狼星", "织女星", "参宿四", "星等", "视星等"),
        "恒星和星等",
        (
            "恒星看起来像点光源。视星等表示天体看起来有多亮，数值越小越亮，负数非常亮。双星适合检验望远镜分辨率，"
            "变星适合长期测光。Telbot 的星表能力可以把常见恒星名或编号解析成坐标，再用于指向或介绍。"
        ),
    ),
    QaTopic(
        ("深空", "星云", "星团", "星系", "dso", "messier", "梅西耶", "ngc", "ic", "m31", "m42", "m13"),
        "深空天体是什么",
        (
            "深空天体通常指太阳系外的星云、星团和星系。它们大多比行星暗得多，拍摄时需要稳定跟踪、较长总曝光、"
            "暗场/平场等校准帧，以及后期叠加。M 编号来自梅西耶表，NGC/IC 是更大的深空天体星表编号。"
        ),
    ),
    QaTopic(
        ("拍照", "曝光", "相机", "ccd", "cmos", "fits", "照片", "preview", "增益", "gain", "binning"),
        "相机拍照和曝光",
        (
            "天文相机拍照本质上是控制曝光时间、增益、保存格式和读出。FITS 是天文原始图常用格式，保留线性数据，"
            "适合后期分析和叠加；网页预览一般会转成 JPEG/PNG 方便查看。行星通常短曝光，深空通常长时间累计曝光。"
        ),
    ),
    QaTopic(
        ("怎么拍", "如何拍", "拍摄建议", "曝光多久", "能拍到", "能看到", "适合拍", "观测建议"),
        "观测和拍摄建议",
        (
            "拍摄建议通常看四件事：目标亮度、目标高度、月光影响、设备焦距/相机视场。初学时可以先用月亮、木星、"
            "土星或 M31/M42 练习。深空目标优先选择高度高、远离月亮、云少、风小的时段；先短曝光测试，再决定总曝光。"
        ),
    ),
    QaTopic(
        ("plate", "solve", "platesolve", "astap", "板解", "解算", "校准", "sync", "slew", "指向误差"),
        "Plate Solve 板解",
        (
            "Plate solve 是拍一张星图后识别星点，反推出望远镜真实指向。它能解决“赤道仪以为指到了，但画面其实偏了”"
            "的问题。解算成功后可以 sync 校准赤道仪坐标，或 slew 让赤道仪转到解算位置。Telbot 当前使用 ASTAP。"
        ),
    ),
    QaTopic(
        ("对焦", "调焦", "电调", "focuser", "autofocus", "hfr", "焦点", "v曲线"),
        "对焦 / 电调 / 自动对焦",
        (
            "对焦决定星点是否锐利。电调是电动调焦器，可以让 Telbot 读取位置或移动步数。自动对焦通常会拍多张图，"
            "测量星点 HFR/FWHM，找到最小值附近的焦点。温度变化、滤镜切换、镜筒姿态变化都可能让焦点漂移。"
        ),
    ),
    QaTopic(
        ("滤镜", "滤镜轮", "cfw", "lrgb", "ha", "oiii", "sii", "窄带", "宽带"),
        "滤镜和滤镜轮",
        (
            "滤镜轮负责切换不同滤镜。宽带 LRGB 适合真实色彩或普通深空拍摄；窄带 Ha/OIII/SII 常用于发射星云，"
            "能减轻光污染和月光影响。不同滤镜厚度可能改变焦点，所以切换滤镜后常要重新对焦。"
        ),
    ),
    QaTopic(
        ("bias", "dark", "flat", "light", "校准帧", "暗场", "平场", "偏置", "叠加", "stack", "live stack"),
        "校准帧和叠加",
        (
            "Light 是正式目标照片；Dark 暗场用于扣除热噪声；Bias 偏置记录相机读出偏置；Flat 平场修正暗角和灰尘。"
            "叠加是把多张照片对齐后合成，提高信噪比。边拍边叠可以让你在拍摄过程中实时看到画面逐渐变清楚。"
        ),
    ),
    QaTopic(
        ("月相", "月光", "天气", "云", "风", "透明度", "视宁度", "seeing", "transparency", "光污染"),
        "天气、月光和观测条件",
        (
            "观测质量不只看有没有云。透明度影响暗弱天体，视宁度影响星点和行星细节，风会影响跟踪稳定，月光会压低"
            "深空目标对比度。满月附近适合月面、行星、双星或窄带；新月附近更适合暗弱星云和星系。"
        ),
    ),
    QaTopic(
        ("系外行星", "凌星", "transit", "wasp", "hat-p", "toi", "测光", "光变曲线"),
        "系外行星凌星观测",
        (
            "凌星是系外行星从恒星前方经过，让恒星亮度出现轻微下降。Telbot 里有凌星列表、计划生成和执行流程。"
            "这种观测更像科学测量：需要稳定曝光、准确时间、合适滤镜、不要过曝，并尽量覆盖凌星前后的基线。"
        ),
    ),
    QaTopic(
        ("干跑", "真机", "execute", "危险", "安全", "为什么不动", "真的会动吗"),
        "干跑与真机执行",
        (
            "Telbot 默认干跑，这是安全保护：网页会展示它准备做什么，但不会真的转动望远镜或触发相机。打开真机执行后，"
            "危险操作还会二次确认。第一次接硬件测试时，先确认 INDI 已连接、线缆不会缠绕、镜筒不会撞到支架。"
        ),
    ),
    QaTopic(
        ("语音", "麦克风", "录音", "listen", "说话", "stt", "whisper", "转文字"),
        "语音输入",
        (
            "网页语音会录音并上传到 /listen/audio。后端先做语音转文字，再走和文字输入相同的意图解析。"
            "如果没有配置云端转写 API，语音功能可能不可用，但文字控制和文字问答仍可使用。"
        ),
    ),
    QaTopic(
        ("报错", "错误", "500", "no_intent", "sentence", "transformers", "semantic", "openai", "api key"),
        "常见报错怎么理解",
        (
            "no_intent 表示这句话没有被识别成控制命令，网页会转去问答。sentence-transformers 是可选句向量模块，"
            "不装也可以使用规则解析。OpenAI/API Key 相关报错通常影响语音转写或大模型问答，不影响基础干跑控制。"
        ),
    ),
)


OBJECT_DESCRIPTIONS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "mercury": (("水星", "mercury"), "水星是什么", "水星是离太阳最近的行星，角距离太阳很近，通常只在日出前或日落后短时间低空可见。"),
    "venus": (("金星", "venus"), "金星是什么", "金星非常明亮，常被称为晨星或昏星。它有明显相位变化，但云层覆盖使表面细节难以直接看到。"),
    "mars": (("火星", "mars"), "火星是什么", "火星是太阳系第四颗行星，表面富含氧化铁而呈红色。冲日前后更接近地球，更适合观测和拍摄。"),
    "jupiter": (("木星", "jupiter"), "木星是什么", "木星是太阳系最大的行星，条纹云带、大红斑和伽利略卫星都很适合业余望远镜观测。"),
    "saturn": (("土星", "saturn"), "土星是什么", "土星以明亮的行星环著名，是最适合展示望远镜效果的行星之一。"),
    "uranus": (("天王星", "uranus"), "天王星是什么", "天王星是遥远的冰巨星，亮度较暗，小望远镜里多呈小而淡的蓝绿色圆点。"),
    "neptune": (("海王星", "neptune"), "海王星是什么", "海王星是太阳系最远的主要行星，亮度很暗，通常需要准确 GOTO、星图核对和较长焦距确认。"),
    "moon": (("月亮", "月球", "moon"), "月亮是什么", "月亮是地球唯一的天然卫星，明亮且细节丰富，适合练习对焦、短曝光和相机预览。"),
    "sun": (("太阳", "sun"), "太阳是什么", "太阳是离我们最近的恒星。观测太阳必须使用合格太阳滤镜，绝不能用普通望远镜直接看太阳。"),
    "m31": (("m31", "仙女座", "andromeda"), "M31 / 仙女座星系是什么", "M31 是仙女座星系，距离约 250 万光年，适合用较宽视场和多张长曝光叠加拍摄。"),
    "m42": (("m42", "猎户座大星云", "orion nebula"), "M42 / 猎户座大星云是什么", "M42 是明亮的发射星云，目标大且亮，非常适合深空摄影入门。"),
    "m13": (("m13", "武仙座球状星团"), "M13 / 武仙座球状星团是什么", "M13 是北天著名球状星团，由大量古老恒星组成，适合检验跟踪、对焦和分辨率。"),
    "polaris": (("北极星", "polaris"), "北极星是什么", "北极星靠近北天极，常用于理解极轴和赤道仪对极轴，但它并不是天空中最亮的恒星。"),
    "sirius": (("天狼星", "sirius"), "天狼星是什么", "天狼星是夜空最亮恒星，亮度高但低空时容易受大气扰动影响而闪烁。"),
    "vega": (("织女星", "vega"), "织女星是什么", "织女星是夏季大三角成员之一，明亮、容易找到，也常被用于对焦或校准测试。"),
}


def _norm(text: str) -> str:
    return text.strip().lower().replace(" ", "")


def _score_topic(q: str, topic: QaTopic) -> int:
    score = 0
    for kw in topic.keywords:
        nkw = _norm(kw)
        if nkw and nkw in q:
            score += max(1, len(nkw))
    return score


def _health_summary(s: Settings) -> str:
    try:
        h = build_health_devices(s)
    except Exception:
        return "当前无法读取完整设备状态。"
    parts: list[str] = []
    for key, label in (("mount", "赤道仪"), ("camera", "相机"), ("focuser", "电调")):
        dev = h.get(key)
        if not isinstance(dev, dict):
            continue
        name = dev.get("name") or dev.get("device") or "未配置"
        connected = dev.get("connected")
        if connected is True:
            state = "已连接"
        elif connected is False:
            state = "未连接"
        else:
            state = "状态未知"
        parts.append(f"{label}：{name}（{state}）")
    return "；".join(parts) if parts else "当前没有可展示的设备状态。"


def _looks_astronomy_or_project(q: str) -> bool:
    hints = (
        "天文",
        "望远镜",
        "赤道仪",
        "相机",
        "拍摄",
        "曝光",
        "星",
        "月",
        "太阳",
        "行星",
        "星云",
        "星系",
        "星团",
        "凌星",
        "坐标",
        "观测",
        "telbot",
        "indi",
        "fits",
        "plate",
        "solve",
        "m",
        "ngc",
        "ic",
    )
    return any(h in q for h in hints)


def _find_known_object(q: str) -> tuple[str, str, str] | None:
    for canonical, (aliases, title, answer) in OBJECT_DESCRIPTIONS.items():
        if any(_norm(alias) in q for alias in aliases):
            return canonical, title, answer
    return None


def _extract_catalog_target(question: str) -> str | None:
    text = question.strip()
    m = re.search(r"(?<![A-Za-z0-9])((?:m|ngc|ic|hip|hd|hr)\s*\d+[a-z]?)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper().replace(" ", "")
    for name in ("北极星", "天狼星", "织女星", "参宿四", "五车二", "南河三", "老人星"):
        if name in text:
            return name
    return None


def _advice_for_question(question: str) -> str:
    q = _norm(question)
    lines: list[str] = []
    if any(h in q for h in ("怎么拍", "如何拍", "拍摄", "曝光", "适合拍", "能拍到")):
        if any(h in q for h in ("星云", "星系", "星团", "m31", "m42", "m13", "ngc", "ic", "深空")):
            lines.append(
                "拍摄建议：深空目标优先看高度角和月光，先用短曝光试拍确认构图与对焦，再累计多张曝光叠加。"
                "建议拍 Light，同时准备 Dark、Flat、Bias 等校准帧。"
            )
        elif any(h in q for h in ("月亮", "月球", "太阳", "木星", "火星", "土星", "金星", "行星")):
            lines.append(
                "拍摄建议：月亮和行星通常很亮，先用短曝光避免过曝；行星更常用视频或多张短曝光叠加，"
                "关键是对焦、视宁度和目标高度。"
            )
        else:
            lines.append(
                "拍摄建议：先短曝光测试画面亮度、对焦和跟踪，再根据目标亮度增加单张曝光或总曝光时间。"
                "深空目标更依赖叠加和校准帧，行星/月亮更依赖短曝光与清晰对焦。"
            )
    if any(h in q for h in ("能看到", "能观测", "适合看", "现在能看", "今晚能看")):
        lines.append(
            "观测建议：能不能看主要取决于目标是否在地平线上方、高度角是否足够高、云量、月光、光污染和遮挡。"
            "一般高度角超过 30° 会舒服很多，越接近地平大气影响越明显。"
        )
    if any(h in q for h in ("曝光多久", "曝光时间", "多少秒")):
        lines.append(
            "曝光时间没有固定答案：月亮/行星常从很短曝光开始，深空可从 5-30 秒试拍，跟踪稳定后再加长。"
            "如果星点拖线就缩短曝光或检查极轴/跟踪；如果背景太亮就缩短曝光或降低增益。"
        )
    return "\n\n" + "\n".join(lines) if lines else ""


def _object_position_appendix(s: Settings, target: str) -> str:
    try:
        from telbot.object_intro import build_object_introduction

        payload = build_object_introduction(s, target)
    except Exception:
        return ""

    intro = payload.get("intro") or {}
    lines: list[str] = []
    alt = intro.get("altitude_deg")
    az = intro.get("azimuth_deg")
    if alt is not None and az is not None:
        lines.append(f"按当前设置的观测地点估算：现在高度角约 {alt}°，方位角约 {az}°。")
    ra = intro.get("ra_hours_now")
    dec = intro.get("dec_deg_now")
    if ra is not None and dec is not None:
        lines.append(f"当前视赤道坐标约 RA {ra} h，Dec {dec}°。")
    vm = intro.get("visual_magnitude")
    if vm is not None:
        lines.append(f"视星等约 {vm}，数值越小看起来越亮。")
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines)


def _answer_known_object(question: str, s: Settings) -> tuple[str, str, int] | None:
    q = _norm(question)
    known = _find_known_object(q)
    if known is not None:
        target, title, answer = known
        return title, answer + _advice_for_question(question) + _object_position_appendix(s, target), 50

    target = _extract_catalog_target(question)
    if not target:
        return None
    appendix = _object_position_appendix(s, target)
    base = (
        f"{target} 是一个可被 Telbot 尝试解析的天体或星表编号。"
        "如果星表数据完整，Telbot 可以把它解析成坐标，用于介绍、判断当前高度，或在真机模式下执行 GOTO。"
        "若它是深空目标，通常需要较长总曝光和叠加；若是恒星，则更适合对焦、校准或测光。"
    )
    return f"{target} 是什么", base + _advice_for_question(question) + appendix, 35


def _answer_from_topics(question: str) -> tuple[str, str, int]:
    q = _norm(question)
    scored = sorted(((_score_topic(q, topic), topic) for topic in TOPICS), key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score > 0:
        return best.title, best.answer, best_score

    if _looks_astronomy_or_project(q):
        return (
            "天文助手回答",
            (
                "这个问题属于 Telbot 的天文/观测范围。你可以把它拆成三类来想："
                "第一，目标是什么，比如行星、星云、星系、星团或恒星；第二，当前是否适合观测，主要看高度角、月光、天气、"
                "光污染和设备视场；第三，怎样拍，通常要决定曝光、对焦、滤镜、校准帧和是否叠加。"
                "如果你问具体目标，例如“M31 怎么拍”“NGC7000 能看到吗”“什么是暗场”，我会给更具体的建议。"
            ),
            1,
        )

    return (
        "可以这样问我",
        (
            "我主要负责回答这个项目相关的天文、望远镜控制和拍摄问题。你可以问：什么是 INDI、赤道仪怎么指向、"
            "M31 怎么拍、暗场和平场有什么区别、plate solve 是什么、今晚凌星观测是什么意思。"
            "你也可以直接发控制命令：检查设备、拍5秒、归位、帮我指向木星。"
        ),
        0,
    )


def _effective_llm_key(s: Settings) -> str:
    return (s.llm_api_key or "").strip() or (s.openai_api_key or "").strip()


def _effective_llm_base_url(s: Settings) -> str:
    return (s.llm_base_url or "").strip() or (s.openai_base_url or "").strip() or "https://api.siliconflow.cn/v1"


def _answer_with_llm(question: str, s: Settings, health_line: str) -> tuple[str, str] | None:
    api_key = _effective_llm_key(s)
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI(api_key=api_key, base_url=_effective_llm_base_url(s), timeout=12)
    model = (s.llm_model or "").strip() or "Qwen/Qwen2.5-7B-Instruct"
    system = (
        "你是 Telbot 网站里的中文天文助手。只回答与 Telbot 项目、天文观测、望远镜、INDI、相机拍摄、"
        "天体知识、星表、观测计划、校准、对焦、滤镜、天气和安全相关的问题。不要声称已经真实控制硬件；"
        "涉及硬件动作时提醒用户使用网页按钮或明确控制命令，并遵守干跑/真机安全确认。"
        "回答要通俗、具体、适合初学者，必要时给步骤。"
    )
    user = (
        f"项目上下文：{PROJECT_CONTEXT}\n"
        f"当前设备概况：{health_line}\n"
        f"用户问题：{question.strip()}"
    )
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.35,
            max_tokens=900,
        )
    except Exception:
        return None
    choice = completion.choices[0] if completion.choices else None
    content = choice.message.content.strip() if choice and choice.message and choice.message.content else ""
    if not content:
        return None
    return "天文助手", content


def answer_telbot_question(question: str, s: Settings) -> dict[str, Any]:
    sentence = question.strip()
    health_line = _health_summary(s)

    local_object = _answer_known_object(sentence, s)
    if local_object is not None:
        title, answer, score = local_object
        source = "local_object"
    else:
        llm_answer = _answer_with_llm(sentence, s, health_line)
        if llm_answer is not None:
            title, answer = llm_answer
            score = 100
            source = "llm"
        else:
            title, answer, score = _answer_from_topics(sentence)
            source = "local_topics"

    full = f"{answer}\n\n当前设备概况：{health_line}"
    return {
        "ok": True,
        "mode": "qa",
        "question": question,
        "title": title,
        "answer": full,
        "matched_score": score,
        "source": source,
    }
