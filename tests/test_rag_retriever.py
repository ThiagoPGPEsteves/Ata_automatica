"""
Testes Unitários do RagRetriever (pytest marker: unit)
Valida a recuperação de chunks com embedder determinístico simulado sem rede.
"""

from pathlib import Path
from typing import List
import numpy as np
import pytest

from src.rag.embedder import BaseEmbedder
from src.rag.store import VectorStore
from src.rag.chunker import DocumentChunk
from src.rag.retriever import RagRetriever


class DeterministicMockEmbedder(BaseEmbedder):
    """Embedder determinístico baseado em termos-chave para testes unitários."""

    VOCAB = ["prazo", "projeto", "orçamento", "contratação", "reunião", "teams", "ata", "segurança"]

    def embed(self, texts: List[str]) -> np.ndarray:
        vecs = []
        for text in texts:
            t_lower = text.lower()
            vec = np.zeros(len(self.VOCAB), dtype=np.float32)
            for idx, word in enumerate(self.VOCAB):
                if word in t_lower:
                    vec[idx] += 1.0

            norm = np.linalg.norm(vec)
            if norm > 1e-9:
                vec = vec / norm
            else:
                # Vetor padrão de fundo
                vec = np.ones(len(self.VOCAB), dtype=np.float32) / np.sqrt(len(self.VOCAB))
            vecs.append(vec)

        return np.array(vecs, dtype=np.float32)


@pytest.fixture
def mock_retriever(tmp_path: Path) -> RagRetriever:
    db_file = tmp_path / "test_retriever.sqlite"
    store = VectorStore(db_path=db_file)
    embedder = DeterministicMockEmbedder()

    # Indexa 3 chunks conhecidos
    c1 = DocumentChunk(
        chunk_id="s1_c1",
        session_id="2026-10-15_100000",
        source="transcript",
        start_sec=10.0,
        end_sec=20.0,
        speakers=["Thiago"],
        text="Discutimos o prazo final do projeto de migração.",
    )
    c2 = DocumentChunk(
        chunk_id="s1_c2",
        session_id="2026-10-15_100000",
        source="minutes",
        start_sec=30.0,
        end_sec=30.0,
        speakers=["Diretoria"],
        text="Aprovação do orçamento anual da equipe.",
    )
    c3 = DocumentChunk(
        chunk_id="s2_c1",
        session_id="2026-10-20_140000",
        source="minutes",
        start_sec=0.0,
        end_sec=0.0,
        speakers=["RH"],
        text="Decisão sobre contratação de desenvolvedor pleno.",
    )

    chunks = [c1, c2, c3]
    embeddings = embedder.embed([c.text for c in chunks])

    store.upsert_session("2026-10-15_100000", "h1", [c1, c2], embeddings[:2])
    store.upsert_session("2026-10-20_140000", "h2", [c3], embeddings[2:])

    return RagRetriever(embedder=embedder, store=store, default_min_similarity=0.2)


@pytest.mark.unit
def test_retriever_finds_expected_chunk(mock_retriever: RagRetriever):
    # Consulta sobre "prazo" e "projeto" deve recuperar c1 como top 1
    results = mock_retriever.retrieve("Qual o prazo do projeto?", k=2)

    assert len(results) > 0
    top_result = results[0]
    assert top_result.chunk.chunk_id == "s1_c1"
    assert "prazo final do projeto" in top_result.chunk.text
    assert top_result.score > 0.5


@pytest.mark.unit
def test_retriever_respects_session_filter(mock_retriever: RagRetriever):
    # Busca por algo geral filtrando apenas a sessão s2
    results = mock_retriever.retrieve("contratação", session_id="2026-10-20_140000")

    assert len(results) == 1
    assert results[0].chunk.session_id == "2026-10-20_140000"
    assert results[0].chunk.chunk_id == "s2_c1"


@pytest.mark.unit
def test_retriever_empty_for_unrelated_query_with_high_threshold(mock_retriever: RagRetriever):
    # Query sem termos em comum com limiar rigoroso deve retornar lista vazia
    results = mock_retriever.retrieve("astronomia e telescópios", min_similarity=0.99)
    assert len(results) == 0
