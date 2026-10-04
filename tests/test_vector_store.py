from pathlib import Path

from app.services.vector_store import FAISSVectorStore


def test_add_search_and_metadata_mapping(tmp_path: Path) -> None:
    store = FAISSVectorStore(tmp_path / "candidates.faiss")
    store.add_document([1.0, 0.0], "candidate", 1)
    store.add_document([0.0, 1.0], "candidate", 2)

    results = store.search([0.9, 0.1], limit=2)

    assert [result["entity_id"] for result in results] == [1, 2]
    assert results[0]["entity_type"] == "candidate"
    assert results[0]["score"] > results[1]["score"]


def test_empty_index_returns_empty_results(tmp_path: Path) -> None:
    store = FAISSVectorStore(tmp_path / "empty.faiss")

    assert store.search([1.0, 0.0]) == []


def test_save_and_load_preserves_index_and_metadata(tmp_path: Path) -> None:
    index_path = tmp_path / "saved.faiss"
    store = FAISSVectorStore(index_path)
    store.add_document([1.0, 0.0], "job", 7)
    store.save()

    loaded = FAISSVectorStore(index_path)
    results = loaded.search([1.0, 0.0])

    assert loaded.size == 1
    assert results[0]["entity_type"] == "job"
    assert results[0]["entity_id"] == 7


def test_repeated_entity_indexing_replaces_without_duplicates(tmp_path: Path) -> None:
    store = FAISSVectorStore(tmp_path / "replace.faiss")
    store.add_document([1.0, 0.0], "candidate", 1)
    store.add_document([0.0, 1.0], "candidate", 1)

    results = store.search([0.0, 1.0], limit=10)

    assert store.size == 1
    assert len(results) == 1
    assert results[0]["entity_id"] == 1


def test_rebuild_replaces_all_documents(tmp_path: Path) -> None:
    store = FAISSVectorStore(tmp_path / "rebuild.faiss")
    store.add_document([1.0, 0.0], "candidate", 1)
    store.rebuild([([0.0, 1.0], "job", 2)])

    assert store.size == 1
    assert store.search([0.0, 1.0])[0]["entity_id"] == 2
