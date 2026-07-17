"""WAV → cloud STT → NLU pipeline (shared by telbot listen and HTTP /listen/audio)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from telbot.config import Settings
from telbot.models import VoiceIntentV1
from telbot.nl_pipeline import resolve_intent_from_sentence
from telbot.voice_cloud import transcribe_whisper_compatible


@dataclass(frozen=True)
class ListenFromWavResult:
    transcript: str
    intent: VoiceIntentV1 | None
    stt_seconds: float
    nlu_seconds: float


def listen_pipeline_from_wav(
    wav_path: Path,
    s_cfg: Settings,
    *,
    no_semantic: bool = False,
    semantic_only: bool = False,
    no_llm: bool = False,
    console: Console | None = None,
) -> ListenFromWavResult:
    """
    Read ``wav_path``, transcribe via Whisper-compatible API, resolve intent (same as telbot listen).
    Timings: ``stt_seconds`` / ``nlu_seconds`` are wall-clock durations for each stage.
    """
    t0 = time.perf_counter()
    base_url = (s_cfg.openai_base_url or "").strip() or None
    text_out = transcribe_whisper_compatible(
        wav_path,
        api_key=s_cfg.openai_api_key,
        base_url=base_url,
        model=s_cfg.openai_transcription_model,
        language=(s_cfg.speech_language or "").strip(),
    )
    t_stt = time.perf_counter()
    stt_seconds = t_stt - t0

    sentence = str(text_out).strip()
    if not sentence:
        return ListenFromWavResult("", None, stt_seconds, 0.0)

    intent = resolve_intent_from_sentence(
        sentence,
        s_cfg,
        console=console,
        no_semantic=no_semantic,
        semantic_only=semantic_only,
        no_llm=no_llm,
    )
    t_nlu = time.perf_counter()
    nlu_seconds = t_nlu - t_stt
    return ListenFromWavResult(sentence, intent, stt_seconds, nlu_seconds)
