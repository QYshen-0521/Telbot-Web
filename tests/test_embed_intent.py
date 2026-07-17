import numpy as np

from telbot.embed_intent import cosine_best, resolve_semantic_model_ref


def test_cosine_best_aligned() -> None:
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    i, s = cosine_best(q, matrix)
    assert i == 0
    assert s > 0.99


def test_resolve_semantic_hub_id_unchanged() -> None:
    assert resolve_semantic_model_ref("paraphrase-multilingual-MiniLM-L12-v2") == (
        "paraphrase-multilingual-MiniLM-L12-v2"
    )


def test_cosine_best_orthogonal() -> None:
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    q = np.array([0.0, 1.0], dtype=np.float32)
    i, s = cosine_best(q, matrix)
    assert i == 1
