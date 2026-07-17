"""Tests for telbot.voice_listen pipeline."""

from pathlib import Path

from telbot.config import Settings
from telbot.models import VoiceIntentV1
from telbot.voice_listen import listen_pipeline_from_wav


def test_listen_pipeline_from_wav_empty_transcript(monkeypatch, tmp_path: Path) -> None:
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")

    monkeypatch.setattr(
        "telbot.voice_listen.transcribe_whisper_compatible",
        lambda *a, **k: "   ",
    )

    s = Settings()
    out = listen_pipeline_from_wav(wav, s)
    assert out.transcript == ""
    assert out.intent is None
    assert out.nlu_seconds == 0.0


def test_listen_pipeline_from_wav_resolves(monkeypatch, tmp_path: Path) -> None:
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"fake")

    monkeypatch.setattr(
        "telbot.voice_listen.transcribe_whisper_compatible",
        lambda *a, **k: "  park mount  ",
    )

    intent = VoiceIntentV1(version=1, action="park")
    monkeypatch.setattr(
        "telbot.voice_listen.resolve_intent_from_sentence",
        lambda *a, **k: intent,
    )

    s = Settings()
    out = listen_pipeline_from_wav(wav, s)
    assert out.transcript == "park mount"
    assert out.intent is intent
    assert out.stt_seconds >= 0.0
    assert out.nlu_seconds >= 0.0
