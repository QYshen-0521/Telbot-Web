"""Cloud speech-to-text (OpenAI Whisper-compatible transcription API)."""

from __future__ import annotations

from pathlib import Path


def transcribe_whisper_compatible(
    wav_path: Path,
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    language: str,
) -> str:
    """
    Upload WAV to POST /v1/audio/transcriptions (OpenAI or compatible gateway).
    wav: mono 16-bit PCM recommended; 16 kHz works well for Whisper.
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("缺少 API Key：请在 .env 设置 TELBOT_OPENAI_API_KEY")

    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("需要 openai：pip install -e '.[voice]'") from e

    kwargs: dict = {"api_key": key}
    if base_url and str(base_url).strip():
        kwargs["base_url"] = str(base_url).strip()

    client = OpenAI(**kwargs)
    with wav_path.open("rb") as f:
        resp = client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language or None,
        )
    text = getattr(resp, "text", None) or ""
    return str(text).strip()
