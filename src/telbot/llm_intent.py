"""Cloud LLM (OpenAI-compatible, e.g. SiliconFlow + Qwen) → VoiceIntentV1."""

from __future__ import annotations

import json
import re
from typing import Any

from telbot.config import Settings
from telbot.models import VoiceIntentV1

INTENT_SYSTEM_PROMPT = """你是赤道仪/望远镜中文语音控制系统的意图解析器。用户输入来自语音识别或键盘。
你必须只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释或前后缀。

字段说明（必须满足 VoiceIntentV1 约束）：
- version: 固定整数 1
- action: 只能是 "goto" | "abort" | "park" | "nudge" | "connect" | "unpark" | "snap" | "platesolve" | "describe" | "focuser_position" | "focuser_rel" | "focuser_autofocus" | "cfw_current" | "cfw_list" | "cfw_goto" | "usb_devices" | "help" | "preflight" | "exoplanet_transits" | "plan_exoplanet_transit" 之一
- frame: 固定字符串 "JNOW"
- confidence: 0 到 1 之间的小数，表示你对该意图的把握

各 action 要求：
- goto：二选一 —— (A) 设 "target" 为要指向的天体标识字符串（英文行星用 jupiter, mars, moon, saturn, venus, mercury, uranus, neptune, sun；中文可说「木星」则 target 填「木星」；编号如 HD 224、NGC 7000、M31 保持原样）；(B) 或同时设 "ra_hours"（0≤值<24 小数时）与 "dec_deg"（-90≤值≤90）。不要同时给 target 又给 ra_hours/dec_deg。
- nudge：必须设 "nudge_direction" 为 "up"|"down"|"left"|"right"（上=赤纬增加，下=赤纬减少，左=赤经减少/西，右=赤经增加/东）。不要设 target、ra_hours、dec_deg。
- abort：急停、停止转动、别动了等。只设 action 与 version、frame、confidence。
- park：归位、停车、回到停车位置等。只设 action 与 version、frame、confidence。
- connect：连接望远镜/赤道仪/设备、连上望远镜、建立连接、打开连接、connect the telescope/mount/gemini、indi connect、用户只说 connect。对应 INDI CONNECTION.CONNECT=On。只设 action 与 version、frame、confidence。
- unpark：解除停车、unpark、解锁停车位；语音识别可能写成「on park」「onpark」也按 unpark。只设 action 与 version、frame、confidence。
- snap：拍照、快门、曝光、take a photo、snap a picture 等 CCD 单次曝光。可设可选字段 "exposure_seconds"（正数秒，如 5 或 0.5）；不说时长则省略该字段（由系统默认）。不要设 target、ra_hours、dec_deg、nudge_direction。
- platesolve：plate solve、板校、校准、天文校准、图像校准、解算当前图等：先 CCD 曝光再 ASTAP 解算（与 snap 不同，会跑解算）。可设可选 "exposure_seconds"；不要设 target、ra_hours、dec_deg、nudge_direction。若用户明确「同步望远镜 / plate solve and sync」等，加可选字段 "platesolve_align":"sync"（解算成功后 ON_COORD_SET.SYNC）；「 GOTO 到解算位置」类可设 "platesolve_align":"slew"。仅 platesolve 可带 platesolve_align。
- describe：让用户「介绍 / 了解一下某天体」（不涉及转动赤道仪）。必须设非空 "target"（天体名：木星、moon、M31、北极星、NGC 7000 等，写法与用户语句一致即可）。不要设 ra_hours、dec_deg、nudge_direction、exposure_seconds。
- focuser_position：查询当前电调/调焦位置（句中含电调、调焦、焦距、焦点等）。只设 action 与 version、frame、confidence。不要设 focuser_direction、focuser_steps、target、ra_hours、dec_deg。
- focuser_rel：电调相对移动。必须设 "focuser_direction" 为 "in" 或 "out"（向前/往外/伸出→"out"；向后/往里/缩回→"in"），以及正整数 "focuser_steps"。不要设 target、ra_hours、dec_deg、nudge_direction。
- focuser_autofocus：自动对焦（V 曲线扫描 CCD 图像 HFR）。如「帮我自动对焦」「自动调焦」。可设可选 "exposure_seconds"（每次采样曝光秒数）。不要设 focuser_direction、focuser_steps、target、ra_hours、dec_deg。
- cfw_current：查询当前滤镜轮槽位/正在使用的滤镜（句中含滤镜、滤光片、滤镜轮等）。只设 action 与 version、frame、confidence。
- cfw_list：列出所有可用滤镜槽与名称。只设 action 与 version、frame、confidence。
- cfw_goto：切换到指定滤镜。必须设非空 "target"（槽号如 "4" 或名称如 "red"、"H_Alpha"、"ha"、中文「红」可写 target 为「红」）。不要设 ra_hours、dec_deg、nudge_direction、focuser_*。
- usb_devices：查询树莓派上当前已连接的、登记表中的天文 USB 设备（赤道仪/CCD/滤镜轮/电调等）。只设 action 与 version、frame、confidence。不要设 target、ra_hours、dec_deg、focuser_*。
- help：用户想了解 Telbot 自身能做什么、支持哪些设备、怎么用（如「请介绍一下你的功能」「你能做什么」「帮助」）。只设 action 与 version、frame、confidence。不要设 target（天体名 describe 才用 target）。
- preflight：检查设备是否就绪（INDI、赤道仪/CCD/电调连接、.env、保存目录）。如「检查设备」「设备就绪」。只设 action 与 version、frame、confidence。不要设 target、focuser_*。
- exoplanet_transits：查询今晚/今夜可观测的系外行星凌星事件列表（如「今晚有哪些系外行星凌星」「今晚可观测的系外行星事件有哪些」）。只设 action 与 version、frame、confidence。不要设 target、ra_hours、dec_deg、focuser_*、event_index。
- plan_exoplanet_transit：为选定凌星事件生成观测计划 JSON（如「规划第 2 个凌星」「今晚观测 WASP-12 b 凌星」）。设 "event_index"（1 起整数）或 "target"（行星全名如 WASP-12 b）；可两者兼有（优先 event_index）。不要设 ra_hours、dec_deg、focuser_*。

若完全无法映射为以上任一合法意图，输出仅此一行 JSON：
{"unparseable":true}

示例（用户 -> 你输出的 JSON）：
- 我要看木星 -> {"version":1,"action":"goto","target":"木星","frame":"JNOW","confidence":0.95}
- 找 M31 -> {"version":1,"action":"goto","target":"M31","frame":"JNOW","confidence":0.9}
- 往左转一点 -> {"version":1,"action":"nudge","nudge_direction":"left","frame":"JNOW","confidence":0.9}
- 立刻停止 -> {"version":1,"action":"abort","frame":"JNOW","confidence":0.95}
- 归位 -> {"version":1,"action":"park","frame":"JNOW","confidence":0.95}
- connect -> {"version":1,"action":"connect","frame":"JNOW","confidence":0.95}
- 连上望远镜 -> {"version":1,"action":"connect","frame":"JNOW","confidence":0.95}
- connect the mount -> {"version":1,"action":"connect","frame":"JNOW","confidence":0.95}
- 解除停车 -> {"version":1,"action":"unpark","frame":"JNOW","confidence":0.95}
- on park（听写错误） -> {"version":1,"action":"unpark","frame":"JNOW","confidence":0.9}
- 拍一张照片 -> {"version":1,"action":"snap","frame":"JNOW","confidence":0.95}
- 介绍一下木星 -> {"version":1,"action":"describe","target":"木星","frame":"JNOW","confidence":0.9}
- M31是什么天体 -> {"version":1,"action":"describe","target":"M31","frame":"JNOW","confidence":0.9}
- 校准并同步望远镜 -> {"version":1,"action":"platesolve","platesolve_align":"sync","frame":"JNOW","confidence":0.95}
- plate solve and sync -> {"version":1,"action":"platesolve","platesolve_align":"sync","frame":"JNOW","confidence":0.9}
- plate solve -> {"version":1,"action":"platesolve","frame":"JNOW","confidence":0.9}
- 查询当前电调位置 -> {"version":1,"action":"focuser_position","frame":"JNOW","confidence":0.95}
- 把电调向前移动50 -> {"version":1,"action":"focuser_rel","focuser_direction":"out","focuser_steps":50,"frame":"JNOW","confidence":0.9}
- 帮我自动对焦 -> {"version":1,"action":"focuser_autofocus","frame":"JNOW","confidence":0.92}
- 电调向后移动100步 -> {"version":1,"action":"focuser_rel","focuser_direction":"in","focuser_steps":100,"frame":"JNOW","confidence":0.9}
- 查询当前滤镜 -> {"version":1,"action":"cfw_current","frame":"JNOW","confidence":0.95}
- 有哪些滤镜可以用 -> {"version":1,"action":"cfw_list","frame":"JNOW","confidence":0.9}
- 切换到红色滤镜 -> {"version":1,"action":"cfw_goto","target":"红","frame":"JNOW","confidence":0.9}
- 换成Ha滤镜 -> {"version":1,"action":"cfw_goto","target":"ha","frame":"JNOW","confidence":0.9}
- 当前有哪些设备连接到pi -> {"version":1,"action":"usb_devices","frame":"JNOW","confidence":0.9}
- 树莓派上连了哪些设备 -> {"version":1,"action":"usb_devices","frame":"JNOW","confidence":0.9}
- 请介绍一下你的功能 -> {"version":1,"action":"help","frame":"JNOW","confidence":0.95}
- 你能做什么 -> {"version":1,"action":"help","frame":"JNOW","confidence":0.9}
- 今晚可观测的系外行星事件有哪些 -> {"version":1,"action":"exoplanet_transits","frame":"JNOW","confidence":0.92}
- 今晚有哪些凌星 -> {"version":1,"action":"exoplanet_transits","frame":"JNOW","confidence":0.88}
- 规划第 2 个凌星 -> {"version":1,"action":"plan_exoplanet_transit","event_index":2,"frame":"JNOW","confidence":0.9}
- 今晚观测 WASP-12 b 凌星 -> {"version":1,"action":"plan_exoplanet_transit","target":"WASP-12 b","frame":"JNOW","confidence":0.88}
"""


def _effective_llm_key(s: Settings) -> str:
    k = (s.llm_api_key or "").strip()
    if k:
        return k
    return (s.openai_api_key or "").strip()


def _effective_llm_base_url(s: Settings) -> str:
    u = (s.llm_base_url or "").strip()
    if u:
        return u.rstrip("/")
    u2 = (s.openai_base_url or "").strip()
    if u2:
        return u2.rstrip("/")
    return "https://api.siliconflow.cn/v1"


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", t, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return t


def _parse_llm_json(content: str) -> dict[str, Any]:
    raw = _strip_json_fences(content)
    return json.loads(raw)


def resolve_intent_llm(sentence: str, s_cfg: Settings) -> VoiceIntentV1 | None:
    """
    Call chat completions (SiliconFlow / OpenAI-compatible). Returns None on skip, reject, or failure.
    """
    api_key = _effective_llm_key(s_cfg)
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("需要 openai：pip install -e '.[llm]' 或 '.[voice]'") from e

    base_url = _effective_llm_base_url(s_cfg)
    model = (s_cfg.llm_model or "").strip() or "Qwen/Qwen2.5-7B-Instruct"

    client = OpenAI(api_key=api_key, base_url=base_url)
    user_msg = f"用户说：{sentence.strip()}"

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }
    try:
        completion = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        completion = client.chat.completions.create(**kwargs)

    choice = completion.choices[0] if completion.choices else None
    if not choice or not choice.message or not choice.message.content:
        return None
    content = choice.message.content.strip()

    try:
        data = _parse_llm_json(content)
    except (json.JSONDecodeError, TypeError):
        return None

    if data.get("unparseable") is True:
        return None

    data.pop("unparseable", None)
    if "raw_text" not in data or data.get("raw_text") is None:
        data["raw_text"] = sentence.strip()

    try:
        return VoiceIntentV1.model_validate(data)
    except ValueError:
        return None
