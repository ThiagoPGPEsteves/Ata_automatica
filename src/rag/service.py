"""
Módulo de Orquestração do Serviço RAG (RagService)
Implementa o fluxo de trabalho 'Zero-Overlap': executa o Embedder, descarrega-o da RAM,
recupera trechos no VectorStore SQLite, carrega o LLM, sintetiza a resposta com citações
e descarrega o LLM imediatamente, mantendo o consumo estritamente dentro do orçamento de 4GB.
"""

import logging
import time
from typing import Dict, Any, List, Optional

from src.pipeline.session import MeetingSession, SessionStore
from src.rag.chunker import SessionChunker, compute_session_content_hash
from src.rag.embedder import BaseEmbedder, OllamaEmbedder
from src.rag.store import VectorStore
from src.rag.retriever import RagRetriever
from src.rag.answerer import RagAnswerer, RagAnswer
from src.utils.telemetry import SystemMemoryAuditor

logger = logging.getLogger(__name__)


class RagService:
    """
    Serviço principal de RAG do Ata Automática.
    """

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        store: Optional[VectorStore] = None,
        answerer: Optional[RagAnswerer] = None,
    ):
        self.store = store or VectorStore()
        self.embedder = embedder or OllamaEmbedder()
        self.retriever = RagRetriever(embedder=self.embedder, store=self.store)
        self.answerer = answerer or RagAnswerer()
        self.chunker = SessionChunker()
        self.auditor = SystemMemoryAuditor()

    def index_session(
        self,
        session: MeetingSession,
        force: bool = False,
    ) -> bool:
        """
        Indexa uma sessão de reunião de forma incremental.

        Args:
            session: Instância da sessão com transcript.json e/ou minutes.json.
            force: Se True, reprocessa mesmo que o hash de conteúdo não tenha mudado.

        Returns:
            True se a sessão foi indexada, False se foi ignorada (já atualizada) ou vazia.
        """
        if not session.exists():
            logger.warning("Sessão '%s' não existe no disco.", session.session_id)
            return False

        content_hash = compute_session_content_hash(session)
        if not content_hash:
            logger.info("Sessão '%s' não possui transcrição ou ata para indexar.", session.session_id)
            return False

        if not force and self.store.is_session_indexed(session.session_id, content_hash):
            logger.info("Sessão '%s' já está indexada com conteúdo idêntico. Pulando.", session.session_id)
            return False

        self.auditor.log_memory_checkpoint(f"Pré-Indexação RAG ({session.session_id})")

        # 1. Segmentação em Chunks
        chunks = self.chunker.chunk_session(session)
        if not chunks:
            logger.info("Nenhum chunk textual gerado para a sessão '%s'.", session.session_id)
            return False

        texts = [c.text for c in chunks]

        # 2. Geração de Embeddings em Lote (com keep_alive='0s')
        t0 = time.time()
        logger.info(
            "Vetorizando %d chunks da sessão '%s' com %s...",
            len(chunks),
            session.session_id,
            getattr(self.embedder, "model", "embedder"),
        )
        embeddings = self.embedder.embed(texts)
        elapsed_embed = time.time() - t0

        self.auditor.log_memory_checkpoint(f"Pós-Embedding RAG ({session.session_id})")

        # 3. Persistência Atômica no SQLite
        success = self.store.upsert_session(
            session_id=session.session_id,
            content_hash=content_hash,
            chunks=chunks,
            embeddings=embeddings,
        )

        logger.info(
            "Sessão '%s' concluída: %d chunks indexados em %.2fs.",
            session.session_id,
            len(chunks),
            elapsed_embed,
        )
        return success

    def index_all_pending(
        self,
        sessions: Optional[List[MeetingSession]] = None,
    ) -> Dict[str, Any]:
        """
        Varre todas as sessões e indexa as que forem novas ou tiverem sido alteradas.
        """
        if sessions is None:
            store = SessionStore()
            sessions = store.list_sessions()

        indexed_count = 0
        skipped_count = 0
        failed_count = 0

        for s in sessions:
            try:
                content_hash = compute_session_content_hash(s)
                if not content_hash:
                    skipped_count += 1
                    continue

                if self.store.is_session_indexed(s.session_id, content_hash):
                    skipped_count += 1
                    continue

                res = self.index_session(s)
                if res:
                    indexed_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                logger.warning("Falha ao indexar sessão '%s': %s", s.session_id, e)

        return {
            "total_inspected": len(sessions),
            "indexed": indexed_count,
            "skipped": skipped_count,
            "failed": failed_count,
        }

    def ask(
        self,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 6,
        min_similarity: float = 0.35,
    ) -> RagAnswer:
        """
        Orquestra a consulta com arquitetura Zero-Overlap e rastreabilidade total de fontes.
        """
        self.auditor.log_memory_checkpoint("Pré-Consulta RAG (Início)")

        # 1. Recuperação: Embedder entra na RAM, calcula vetor da query e sai imediatamente (keep_alive='0s')
        search_results = self.retriever.retrieve(
            query=query,
            k=top_k,
            session_id=session_id,
            min_similarity=min_similarity,
        )

        self.auditor.log_memory_checkpoint("Pós-Recuperação RAG (Embedder Descarregado)")

        if not search_results:
            return RagAnswer(
                answer="Não encontrei isso nas reuniões indexadas.",
                citations=[],
                found=False,
                sources=[],
            )

        # 2. Síntese: LLM entra na RAM, formula a resposta fundamentada com citações e sai imediatamente
        answer = self.answerer.answer(query=query, results=search_results)

        self.auditor.log_memory_checkpoint("Pós-Síntese RAG (LLM Descarregado)")
        return answer

    def forget_session(self, session_id: str) -> bool:
        """Expurga todos os dados da sessão do índice vetorial (LGPD)."""
        return self.store.delete_session(session_id)

    def stats(self) -> Dict[str, Any]:
        """Estatísticas do índice vetorial."""
        return self.store.stats()
