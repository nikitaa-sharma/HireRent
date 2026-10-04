"""Lazy local sentence-transformer embedding service."""

from __future__ import annotations

from functools import lru_cache
import re

from app.config import EMBEDDING_MODEL_NAME


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        raise ValueError("Text to embed must not be empty")
    return cleaned


@lru_cache(maxsize=1)
def _get_model():
    """Load the local model once, on the first embedding request."""

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    """Return a normalized embedding for one non-empty text value."""

    cleaned = _clean_text(text)
    embedding = _get_model().encode(
        cleaned,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embedding.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return normalized embeddings for a non-empty list of text values."""

    if not texts:
        raise ValueError("Texts to embed must not be empty")
    cleaned_texts = [_clean_text(text) for text in texts]
    embeddings = _get_model().encode(
        cleaned_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embeddings.tolist()
