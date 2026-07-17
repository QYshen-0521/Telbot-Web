"""
Semantic intent (route B): multilingual sentence embeddings + nearest training example.

Requires: pip install -e ".[semantic]"
First run downloads the model (~420MB for MiniLM) into HuggingFace cache.

SentenceTransformer is loaded once per process per model_ref and reused (rebuild_cache + match share it).
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from telbot.models import VoiceIntentV1

CACHE_DIR = Path.home() / ".cache" / "telbot" / "semantic"
CACHE_META = "cache_meta.json"
CACHE_EMB = "train_embeddings.npy"
CACHE_LABELS = "train_labels.json"

# Process-local singleton: avoid loading the same ST model twice in one telbot invocation
_st_resolved_ref: str | None = None
_st_model: Any = None


def _examples_raw() -> bytes:
    return resources.files("telbot.data").joinpath("intent_examples_zh.jsonl").read_bytes()


def load_training_rows() -> list[tuple[str, dict[str, Any]]]:
    """Load (text, voice dict) from packaged JSONL."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for line in _examples_raw().decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        rows.append((obj["text"], obj["voice"]))
    return rows


def _examples_fingerprint() -> str:
    return hashlib.sha256(_examples_raw()).hexdigest()


def resolve_semantic_model_ref(model_name: str) -> str:
    """
    If model_name points to a local directory with HF/ST layout, return absolute path.
    Otherwise return model_name (Hugging Face Hub id).
    """
    raw = model_name.strip()
    p = Path(raw).expanduser()
    if not p.is_dir():
        return raw
    if (p / "config.json").is_file() or (p / "modules.json").is_file():
        return str(p.resolve())
    return raw


def _load_sentence_transformer_once(model_ref: str) -> Any:
    """Construct a new SentenceTransformer (no caching)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "需要 sentence-transformers：pip install -e '.[semantic]'"
        ) from e
    try:
        return SentenceTransformer(model_ref)
    except OSError as e:
        if getattr(e, "errno", None) == -3 or "name resolution" in str(e).lower():
            raise RuntimeError(
                "无法访问 huggingface.co（DNS/网络失败）。请在本机联网下载模型快照后拷贝到树莓派，"
                "并在 .env 设置 TELBOT_SEMANTIC_MODEL=/绝对路径/到模型目录。详见 README「句向量离线」。"
            ) from e
        raise
    except Exception as e:
        err = str(e).lower()
        if "closed" in err or "resolution" in err or "connection" in err:
            raise RuntimeError(
                "句向量模型加载失败（多为网络无法访问 Hugging Face）。"
                "请使用本地模型目录：TELBOT_SEMANTIC_MODEL=/path/to/snapshot，见 README「句向量离线」。"
            ) from e
        raise


def get_sentence_transformer_singleton(model_name: str) -> Any:
    """
    Return a shared SentenceTransformer for resolved model_ref.
    Reused across rebuild_cache and match_intent_semantic in the same process.
    """
    global _st_resolved_ref, _st_model
    resolved = resolve_semantic_model_ref(model_name)
    if _st_model is not None and _st_resolved_ref == resolved:
        return _st_model
    _st_model = _load_sentence_transformer_once(resolved)
    _st_resolved_ref = resolved
    return _st_model


def clear_sentence_transformer_singleton() -> None:
    """Drop cached model (e.g. tests or switching model in same interpreter)."""
    global _st_resolved_ref, _st_model
    _st_resolved_ref = None
    _st_model = None


def _cache_model_ref_matches(meta: dict[str, Any], settings_name: str) -> bool:
    resolved = resolve_semantic_model_ref(settings_name)
    if meta.get("model_ref") == resolved:
        return True
    if meta.get("model_name") == settings_name and "model_ref" not in meta:
        return True
    return False


def _encode_batch(model: Any, texts: list[str]) -> np.ndarray:
    emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(emb, dtype=np.float32)


def cosine_best(query: np.ndarray, matrix: np.ndarray) -> tuple[int, float]:
    """query (d,), matrix (n,d), L2-normalized rows."""
    q = query.astype(np.float32)
    q = q / (np.linalg.norm(q) + 1e-12)
    m = matrix.astype(np.float32)
    m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)
    sims = m @ q
    i = int(np.argmax(sims))
    return i, float(sims[i])


def rebuild_cache(model_name: str) -> Path:
    """Embed all training lines and save under ~/.cache/telbot/semantic/."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_training_rows()
    texts = [t for t, _ in rows]
    model = get_sentence_transformer_singleton(model_name)
    matrix = _encode_batch(model, texts)
    labels = [v for _, v in rows]
    np.save(CACHE_DIR / CACHE_EMB, matrix)
    (CACHE_DIR / CACHE_LABELS).write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    resolved = resolve_semantic_model_ref(model_name)
    meta = {
        "model_name": model_name,
        "model_ref": resolved,
        "examples_sha256": _examples_fingerprint(),
        "n": len(texts),
    }
    (CACHE_DIR / CACHE_META).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return CACHE_DIR


def _cache_valid(model_name: str) -> bool:
    meta_path = CACHE_DIR / CACHE_META
    emb_path = CACHE_DIR / CACHE_EMB
    lab_path = CACHE_DIR / CACHE_LABELS
    if not (meta_path.is_file() and emb_path.is_file() and lab_path.is_file()):
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not _cache_model_ref_matches(meta, model_name):
        return False
    if meta.get("examples_sha256") != _examples_fingerprint():
        return False
    return True


def _load_cache() -> tuple[np.ndarray, list[dict[str, Any]]]:
    matrix = np.load(CACHE_DIR / CACHE_EMB)
    labels = json.loads((CACHE_DIR / CACHE_LABELS).read_text(encoding="utf-8"))
    return matrix, labels


def _ensure_cache(model_name: str) -> tuple[np.ndarray, list[dict[str, Any]]]:
    if not _cache_valid(model_name):
        rebuild_cache(model_name)
    return _load_cache()


def match_intent_semantic(
    text: str,
    *,
    model_name: str,
    threshold: float,
) -> tuple[VoiceIntentV1 | None, float, str]:
    """
    Return (VoiceIntentV1 or None if below threshold), best cosine similarity, matched training text.
    """
    matrix, labels = _ensure_cache(model_name)
    rows = load_training_rows()
    train_texts = [t for t, _ in rows]
    model = get_sentence_transformer_singleton(model_name)
    q_vec = _encode_batch(model, [text.strip()])[0]
    idx, score = cosine_best(q_vec, matrix)
    if score < threshold:
        return None, score, train_texts[idx]
    base = VoiceIntentV1.model_validate(labels[idx])
    conf = float(max(0.0, min(1.0, score)))
    intent = base.model_copy(update={"raw_text": text.strip(), "confidence": conf})
    return intent, score, train_texts[idx]
