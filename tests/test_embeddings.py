import numpy as np
import pytest

from app.services import embedding_service


class FakeEmbeddingModel:
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        values = [texts] if isinstance(texts, str) else texts
        vectors = []
        for value in values:
            vectors.append([float(len(value)), float(sum(ord(char) for char in value) % 101)])
        return np.asarray(vectors[0] if isinstance(texts, str) else vectors, dtype="float32")


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    monkeypatch.setattr(embedding_service, "_get_model", lambda: FakeEmbeddingModel())


def test_embedding_normal_string() -> None:
    embedding = embedding_service.embed_text("  Python   backend  ")

    assert len(embedding) == 2
    assert all(isinstance(value, float) for value in embedding)


def test_empty_embedding_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        embedding_service.embed_text("  ")
    with pytest.raises(ValueError, match="must not be empty"):
        embedding_service.embed_texts([])


def test_embedding_dimensions_are_consistent() -> None:
    embeddings = embedding_service.embed_texts(["Python", "FastAPI"])

    assert len(embeddings) == 2
    assert len(embeddings[0]) == len(embeddings[1])


def test_same_input_produces_same_embedding() -> None:
    first = embedding_service.embed_text("same input")
    second = embedding_service.embed_text("  same   input ")

    assert first == second
