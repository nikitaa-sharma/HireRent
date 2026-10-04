"""Small persistent FAISS stores for local cosine-similarity search."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from app.config import VECTOR_STORE_DIR
from app.services.embedding_service import embed_text


class FAISSVectorStore:
    """A cosine-similarity FAISS index with JSON entity metadata."""

    def __init__(self, index_path: Path, metadata_path: Path | None = None) -> None:
        self.index_path = index_path
        self.metadata_path = metadata_path or index_path.with_suffix(".json")
        self._faiss = None
        self._index = None
        self._metadata: list[dict[str, Any]] = []
        self._load_if_present()

    @property
    def dimension(self) -> int | None:
        return self._index.d if self._index is not None else None

    @property
    def size(self) -> int:
        return self._index.ntotal if self._index is not None else 0

    def _load_if_present(self) -> None:
        if not self.index_path.exists() or not self.metadata_path.exists():
            return
        faiss = self._get_faiss()
        self._index = faiss.read_index(str(self.index_path))
        with self.metadata_path.open("r", encoding="utf-8") as metadata_file:
            payload = json.load(metadata_file)
        self._metadata = payload.get("items", [])
        if len(self._metadata) != self._index.ntotal:
            raise ValueError("FAISS index and metadata are out of sync")

    def _get_faiss(self):
        if self._faiss is None:
            import faiss

            self._faiss = faiss
        return self._faiss

    def _ensure_index(self, dimension: int) -> None:
        if self._index is None:
            self._index = self._get_faiss().IndexFlatIP(dimension)
        elif self._index.d != dimension:
            raise ValueError("Vector dimension does not match the existing index")

    def add_document(
        self,
        vector: list[float],
        entity_type: str,
        entity_id: int,
    ) -> None:
        """Add or replace one entity vector without creating duplicates."""

        if not vector:
            raise ValueError("Vector must not be empty")
        if entity_type not in {"candidate", "job"}:
            raise ValueError("Entity type must be 'candidate' or 'job'")

        self._ensure_index(len(vector))
        existing_index = next(
            (
                index
                for index, item in enumerate(self._metadata)
                if item["entity_type"] == entity_type and item["entity_id"] == entity_id
            ),
            None,
        )
        if existing_index is not None:
            vectors = self._index.reconstruct_n(0, self._index.ntotal)
            vectors[existing_index] = vector
            metadata = [item for index, item in enumerate(self._metadata) if index != existing_index]
            vectors = [row for index, row in enumerate(vectors) if index != existing_index]
            vectors.append(vector)
            metadata.append({"entity_type": entity_type, "entity_id": entity_id})
            self._rebuild(vectors, metadata)
            return

        import numpy as np

        vector_array = np.asarray([vector], dtype="float32")
        self._get_faiss().normalize_L2(vector_array)
        self._index.add(vector_array)
        self._metadata.append({"entity_type": entity_type, "entity_id": entity_id})

    def _rebuild(self, vectors: list[Any], metadata: list[dict[str, Any]]) -> None:
        import numpy as np

        self._index = self._get_faiss().IndexFlatIP(len(vectors[0]))
        vector_array = np.asarray(vectors, dtype="float32")
        self._get_faiss().normalize_L2(vector_array)
        self._index.add(vector_array)
        self._metadata = metadata

    def rebuild(self, documents: list[tuple[list[float], str, int]]) -> None:
        """Replace the entire index with the supplied vector documents."""

        if not documents:
            self._index = None
            self._metadata = []
            return
        dimension = len(documents[0][0])
        self._ensure_index(dimension)
        self._rebuild(
            [vector for vector, _entity_type, _entity_id in documents],
            [
                {"entity_type": entity_type, "entity_id": entity_id}
                for _vector, entity_type, entity_id in documents
            ],
        )

    def search(
        self,
        vector: list[float],
        limit: int = 10,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search normalized vectors and return metadata with cosine scores."""

        if limit < 1:
            raise ValueError("Search limit must be at least 1")
        if self._index is None or self._index.ntotal == 0:
            return []
        if len(vector) != self._index.d:
            raise ValueError("Vector dimension does not match the existing index")

        import numpy as np

        query = np.asarray([vector], dtype="float32")
        self._get_faiss().normalize_L2(query)
        scores, indexes = self._index.search(query, min(limit, self._index.ntotal))
        results = []
        for score, index in zip(scores[0], indexes[0]):
            if index < 0:
                continue
            metadata = self._metadata[index]
            if entity_type is not None and metadata["entity_type"] != entity_type:
                continue
            results.append({**metadata, "score": float(score)})
        return results

    def save(self) -> None:
        """Persist the FAISS index and metadata JSON side by side."""

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        if self._index is None:
            self._index = self._get_faiss().IndexFlatIP(1)
        self._get_faiss().write_index(self._index, str(self.index_path))
        with self.metadata_path.open("w", encoding="utf-8") as metadata_file:
            json.dump({"items": self._metadata}, metadata_file, indent=2)


@lru_cache(maxsize=2)
def _get_store(entity_type: str) -> FAISSVectorStore:
    return FAISSVectorStore(
        VECTOR_STORE_DIR / f"{entity_type}s.faiss",
        VECTOR_STORE_DIR / f"{entity_type}s.json",
    )


def index_candidate(candidate_id: int, text: str) -> None:
    store = _get_store("candidate")
    store.add_document(embed_text(text), "candidate", candidate_id)
    store.save()


def index_job(job_id: int, text: str) -> None:
    store = _get_store("job")
    store.add_document(embed_text(text), "job", job_id)
    store.save()


def search_candidates(query: str, limit: int = 10) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError("Search query must not be empty")
    return _get_store("candidate").search(embed_text(query), limit, entity_type="candidate")
