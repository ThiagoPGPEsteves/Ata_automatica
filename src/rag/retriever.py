"""
Módulo de Recuperação Semântica (Retriever) para RAG
Converte perguntas em linguagem natural em vetores densos e busca os trechos
mais relevantes no VectorStore respeitando limiares de similaridade e filtros.
"""

import logging
from typing import List, Optional

import numpy as np

from src.rag.embedder import BaseEmbedder, OllamaEmbedder
from src.rag.store import VectorStore, SearchResult

logger = logging.getLogger(__name__)


class RagRetriever:
    """
    Recuperador semântico de trechos de reuniões.
    """

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        store: Optional[VectorStore] = None,
        default_min_similarity: float = 0.35,
    ):
        self.embedder = embedder or OllamaEmbedder()
        self.store = store or VectorStore()
        self.default_min_similarity = default_min_similarity

    def retrieve(
        self,
        query: str,
        k: int = 6,
        session_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_similarity: Optional[float] = None,
    ) -> List[SearchResult]:
        """
        Recupera os top-k trechos mais relevantes para a consulta informada.

        Args:
            query: Pergunta do usuário em linguagem natural.
            k: Número máximo de chunks a retornar (padrão: 6).
            session_id: Filtro opcional para buscar apenas em uma reunião específica.
            date_from: Data inicial (formato YYYY-MM-DD).
            date_to: Data final (formato YYYY-MM-DD).
            min_similarity: Limiar mínimo de similaridade de cosseno (padrão: 0.35).

        Returns:
            Lista de SearchResult ordenada descendentemente por relevância.
        """
        q_clean = query.strip()
        if not q_clean:
            return []

        threshold = min_similarity if min_similarity is not None else self.default_min_similarity

        # 1. Vetorização da pergunta (utiliza keep_alive='0s' no embedder)
        query_vectors = self.embedder.embed([q_clean])
        if len(query_vectors) == 0:
            return []

        query_vec = query_vectors[0]

        # 2. Busca exata de similaridade no banco vetorial
        session_filter = [session_id] if session_id else None
        candidates = self.store.search(
            query_vec=query_vec,
            k=k,
            session_ids=session_filter,
            date_from=date_from,
            date_to=date_to,
        )

        # 3. Filtragem pelo limiar de corte
        filtered_results: List[SearchResult] = [
            res for res in candidates if res.score >= threshold
        ]

        logger.info(
            "Recuperação RAG para '%s': %d candidatos encontrados, %d após limiar (>= %.2f).",
            q_clean[:40],
            len(candidates),
            len(filtered_results),
            threshold,
        )

        return filtered_results
