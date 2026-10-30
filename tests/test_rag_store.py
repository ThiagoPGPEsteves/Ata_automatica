"""
Testes Unitários do VectorStore SQLite do RAG (pytest marker: unit)
Valida operações de inserção atômica, hashing incremental, filtros e expurgo LGPD.
"""

from pathlib import Path
import numpy as np
import pytest

from src.rag.store import VectorStore, SearchResult
from src.rag.chunker import DocumentChunk


@pytest.fixture
def temp_store(tmp_path: Path) -> VectorStore:
    db_file = tmp_path / "test_rag.sqlite"
    return VectorStore(db_path=db_file)


@pytest.mark.unit
def test_vector_store_upsert_and_incremental_hash(temp_store: VectorStore):
    session_id = "2026-10-30_110000"
    content_hash = "hash_teste_123"

    chunk1 = DocumentChunk(
        chunk_id=f"{session_id}_tra_01",
        session_id=session_id,
        source="transcript",
        start_sec=10.0,
        end_sec=25.0,
        speakers=["Thiago"],
        text="Discussão sobre prazo do projeto de atas.",
    )
    chunk2 = DocumentChunk(
        chunk_id=f"{session_id}_min_dec_01",
        session_id=session_id,
        source="minutes",
        start_sec=15.0,
        end_sec=15.0,
        speakers=["Ata Executiva"],
        text="Decisão: O prazo final fica fixado em 15 de novembro.",
    )

    # Vetores de dimensão 4 normalizados
    embeddings = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ], dtype=np.float32)

    assert not temp_store.is_session_indexed(session_id, content_hash)

    success = temp_store.upsert_session(
        session_id=session_id,
        content_hash=content_hash,
        chunks=[chunk1, chunk2],
        embeddings=embeddings,
    )
    assert success is True

    # Agora a checagem incremental deve acusar que já está indexada
    assert temp_store.is_session_indexed(session_id, content_hash)
    assert not temp_store.is_session_indexed(session_id, "outro_hash_diferente")

    stats = temp_store.stats()
    assert stats["sessions_count"] == 1
    assert stats["chunks_count"] == 2
    assert stats["transcript_chunks"] == 1
    assert stats["minutes_chunks"] == 1


@pytest.mark.unit
def test_vector_store_cosine_search_and_filters(temp_store: VectorStore):
    s1 = "2026-10-15_100000"
    s2 = "2026-10-25_150000"

    chunks_s1 = [
        DocumentChunk(
            chunk_id=f"{s1}_c1",
            session_id=s1,
            source="transcript",
            start_sec=0.0,
            end_sec=10.0,
            speakers=["Alice"],
            text="Trecho sobre orçamento financeiro.",
        )
    ]
    emb_s1 = np.array([[0.9, 0.1, 0.0, 0.0]], dtype=np.float32)
    temp_store.upsert_session(s1, "hash_s1", chunks_s1, emb_s1)

    chunks_s2 = [
        DocumentChunk(
            chunk_id=f"{s2}_c1",
            session_id=s2,
            source="minutes",
            start_sec=5.0,
            end_sec=5.0,
            speakers=["Bob"],
            text="Decisão sobre contratação de pessoal.",
        )
    ]
    emb_s2 = np.array([[0.1, 0.9, 0.0, 0.0]], dtype=np.float32)
    temp_store.upsert_session(s2, "hash_s2", chunks_s2, emb_s2)

    # Consulta orientada ao tópico de Alice ([1, 0, 0, 0])
    q_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    results = temp_store.search(q_vec, k=2)

    assert len(results) == 2
    assert results[0].chunk.session_id == s1
    assert results[0].score > results[1].score

    # Filtro por session_id
    res_s2_only = temp_store.search(q_vec, k=2, session_ids=[s2])
    assert len(res_s2_only) == 1
    assert res_s2_only[0].chunk.session_id == s2

    # Filtro por data
    res_date = temp_store.search(q_vec, k=2, date_from="2026-10-20")
    assert len(res_date) == 1
    assert res_date[0].chunk.session_id == s2


@pytest.mark.unit
def test_vector_store_lgpd_deletion(temp_store: VectorStore):
    session_id = "2026-10-10_090000"
    chunk = DocumentChunk(
        chunk_id=f"{session_id}_c1",
        session_id=session_id,
        source="transcript",
        start_sec=0.0,
        end_sec=10.0,
        speakers=["Confidencial"],
        text="Dados sensíveis para expurgo LGPD.",
    )
    emb = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    temp_store.upsert_session(session_id, "hash_lgpd", [chunk], emb)

    assert temp_store.stats()["sessions_count"] == 1
    assert temp_store.stats()["chunks_count"] == 1

    deleted = temp_store.delete_session(session_id)
    assert deleted is True

    assert temp_store.stats()["sessions_count"] == 0
    assert temp_store.stats()["chunks_count"] == 0
    assert temp_store.is_session_indexed(session_id, "hash_lgpd") is False
