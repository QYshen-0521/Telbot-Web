"""Natural-language → VoiceIntentV1 (rules + star catalog + optional semantic + optional LLM)."""

from __future__ import annotations

from rich.console import Console

from telbot.config import Settings
from telbot.models import VoiceIntentV1
from telbot.text_intent import parse_intent_zh


def resolve_intent_from_sentence(
    sentence: str,
    s_cfg: Settings,
    *,
    console: Console | None = None,
    no_semantic: bool,
    semantic_only: bool,
    no_llm: bool = False,
) -> VoiceIntentV1 | None:
    """
    Order (when not --semantic-only):
    1) Rules + star catalog (parse_intent_zh)
    2) Sentence-embedding match to training examples (unless --no-semantic)
    3) Cloud LLM if TELBOT_INTENT_USE_LLM (unless --no-llm)
    Returns None if no intent matched.
    """
    sentence = str(sentence).strip()
    if not sentence:
        return None

    if semantic_only:
        try:
            from telbot.embed_intent import match_intent_semantic
        except ImportError as e:
            raise RuntimeError(
                "句向量依赖未安装：pip install -e '.[semantic]'（体积较大，含 PyTorch）"
            ) from e
        sem_intent, score, nearest = match_intent_semantic(
            sentence,
            model_name=s_cfg.semantic_model,
            threshold=s_cfg.semantic_threshold,
        )
        if console is not None:
            console.print(
                f"[dim]semantic: score={score:.3f} threshold={s_cfg.semantic_threshold} "
                f"nearest={nearest!r}[/dim]"
            )
        return sem_intent

    intent = parse_intent_zh(sentence)
    if intent is not None:
        if not no_semantic and console is not None:
            console.print("[dim]semantic: skipped（已由规则/星表命中）[/dim]")
        return intent

    if not no_semantic:
        try:
            from telbot.embed_intent import match_intent_semantic
        except ImportError:
            pass
        else:
            sem_intent, score, nearest = match_intent_semantic(
                sentence,
                model_name=s_cfg.semantic_model,
                threshold=s_cfg.semantic_threshold,
            )
            intent = sem_intent
            if console is not None:
                console.print(
                    f"[dim]semantic: score={score:.3f} threshold={s_cfg.semantic_threshold} "
                    f"nearest={nearest!r}[/dim]"
                )

    if intent is not None:
        return intent

    if s_cfg.intent_use_llm and not no_llm:
        try:
            from telbot.llm_intent import resolve_intent_llm

            llm_intent = resolve_intent_llm(sentence, s_cfg)
            if llm_intent is not None:
                m = (s_cfg.llm_model or "").strip() or "llm"
                if console is not None:
                    console.print(f"[dim]llm: {m}（云端意图）[/dim]")
                return llm_intent
        except ImportError as e:
            raise RuntimeError(str(e)) from e
        except Exception as e:
            if console is not None:
                console.print(f"[yellow]llm 调用失败：{e}[/yellow]")

    return None
