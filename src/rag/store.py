"""
Módulo de Armazenamento Vetorial Leve (VectorStore) sobre SQLite
Armazena embeddings e metadados com zero dependências externas pesadas,
suporte a indexação incremental por hash de conteúdo e expurgo LGPD.
"""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import List, Dict, Any, Optional

import numpy as np

from src.config import RAG_DB_PATH
from src.rag.chunker import DocumentChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Resultado de recuperação semântica associando um chunk ao seu score de similaridade."""

    chunk: DocumentChunk
    score: float


class VectorStore:
    """
    Banco vetorial embarcado construído sobre SQLite e NumPy.
    Garante busca por similaridade de cosseno exata para centenas de reuniões,
    com controle de transações ACID e persistência em sessions/rag_index.sqlite.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or RAG_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Cria as tabelas e índices se não existirem."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Tabela de controle de versão e hash das sessões (para indexação incremental)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions_index_control (
                    session_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    chunks_count INTEGER NOT NULL
                )
                """
            )

            # Tabela de armazenamento de chunks e embeddings densos (BLOB float32)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    start_sec REAL NOT NULL,
                    end_sec REAL NOT NULL,
                    speakers TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding BLOB NOT NULL
                )
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)"
            )
            conn.commit()

    def is_session_indexed(self, session_id: str, content_hash: str) -> bool:
        """
        Verifica se a sessão já foi indexada com exatamente o mesmo hash de conteúdo.
        Permite ignorar reprocessamento redundante em O(1).
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT content_hash FROM sessions_index_control WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return False
            return str(row["content_hash"]) == str(content_hash)

    def upsert_session(
        self,
        session_id: str,
        content_hash: str,
        chunks: List[DocumentChunk],
        embeddings: np.ndarray,
    ) -> bool:
        """
        Insere ou atualiza atomicamente os chunks e vetores de uma sessão.
        """
        if len(chunks) == 0:
            logger.info("Nenhum chunk gerado para a sessão '%s'. Ignorando inserção.", session_id)
            return False

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Tamanho incompatível entre chunks ({len(chunks)}) e embeddings ({len(embeddings)})."
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Remove dados anteriores da mesma sessão se houver
            cursor.execute("DELETE FROM chunks WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions_index_control WHERE session_id = ?", (session_id,))

            rows_to_insert = []
            for chunk, emb in zip(chunks, embeddings):
                # Converte vetor normalizado para bytes float32
                vec_float32 = emb.astype(np.float32)
                blob_bytes = vec_float32.tobytes()

                rows_to_insert.append((
                    chunk.chunk_id,
                    chunk.session_id,
                    chunk.source,
                    chunk.start_sec,
                    chunk.end_sec,
                    json.dumps(chunk.speakers, ensure_ascii=False),
                    chunk.text,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                    blob_bytes,
                ))

            cursor.executemany(
                """
                INSERT INTO chunks (
                    id, session_id, source, start_sec, end_sec,
                    speakers, text, metadata_json, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )

            indexed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            cursor.execute(
                """
                INSERT INTO sessions_index_control (
                    session_id, content_hash, indexed_at, chunks_count
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, content_hash, indexed_at, len(chunks)),
            )

            conn.commit()
            logger.info(
                "Sessão '%s' indexada com sucesso no VectorStore (%d chunks).",
                session_id,
                len(chunks),
            )
            return True

    def delete_session(self, session_id: str) -> bool:
        """
        Expurgo estrito de dados conforme LGPD:
        Remove permanentemente todos os vetores e textos indexados da sessão.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chunks WHERE session_id = ?", (session_id,))
            del_chunks = cursor.rowcount
            cursor.execute("DELETE FROM sessions_index_control WHERE session_id = ?", (session_id,))
            del_ctrl = cursor.rowcount
            conn.commit()

            removed = (del_chunks > 0) or (del_ctrl > 0)
            if removed:
                logger.info(
                    "[LGPD] Sessão '%s' removida do índice vetorial (%d chunks apagados).",
                    session_id,
                    del_chunks,
                )
            return removed

    def search(
        self,
        query_vec: np.ndarray,
        k: int = 6,
        session_ids: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Busca semântica exata por similaridade de cosseno (produto escalar de vetores L2-normalizados).
        """
        if k <= 0:
            return []

        q_vec = query_vec.astype(np.float32).flatten()
        norm = np.linalg.norm(q_vec)
        if norm > 1e-9:
            q_vec = q_vec / norm

        query_sql = "SELECT id, session_id, source, start_sec, end_sec, speakers, text, metadata_json, embedding FROM chunks WHERE 1=1"
        params: List[Any] = []

        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            query_sql += f" AND session_id IN ({placeholders})"
            params.extend(session_ids)

        if date_from:
            # session_id inicia com YYYY-MM-DD
            query_sql += " AND session_id >= ?"
            params.append(date_from)

        if date_to:
            query_sql += " AND session_id <= ?"
            params.append(date_to + "_999999")

        with self._get_connection() as conn:
            rows = conn.execute(query_sql, params).fetchall()

        if not rows:
            return []

        doc_chunks: List[DocumentChunk] = []
        matrix_list: List[np.ndarray] = []

        dim = len(q_vec)
        for r in rows:
            blob = r["embedding"]
            emb = np.frombuffer(blob, dtype=np.float32)
            if len(emb) != dim:
                continue

            matrix_list.append(emb)
            speakers = []
            try:
                speakers = json.loads(r["speakers"])
            except Exception:
                pass

            meta = {}
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                pass

            doc_chunks.append(
                DocumentChunk(
                    chunk_id=r["id"],
                    session_id=r["session_id"],
                    source=r["source"],
                    start_sec=float(r["start_sec"]),
                    end_sec=float(r["end_sec"]),
                    speakers=speakers,
                    text=r["text"],
                    metadata=meta,
                )
            )

        if not matrix_list:
            return []

        # Matriz (N, D) e produto escalar com vetor (D,)
        matrix = np.vstack(matrix_list)
        scores = np.dot(matrix, q_vec)

        # Seleciona os top-k índices
        top_k_indices = np.argsort(scores)[::-1][:k]

        results: List[SearchResult] = []
        for idx in top_k_indices:
            results.append(
                SearchResult(
                    chunk=doc_chunks[idx],
                    score=float(scores[idx]),
                )
            )

        return results

    def stats(self) -> Dict[str, Any]:
        """Retorna estatísticas consolidadas do índice vetorial."""
        with self._get_connection() as conn:
            sessions_count = conn.execute(
                "SELECT COUNT(*) FROM sessions_index_control"
            ).fetchone()[0]

            chunks_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

            tra_count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE source = 'transcript'"
            ).fetchone()[0]

            min_count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE source = 'minutes'"
            ).fetchone()[0]

        file_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        file_size_kb = file_size_bytes / 1024.0

        return {
            "db_path": str(self.db_path),
            "sessions_count": sessions_count,
            "chunks_count": chunks_count,
            "transcript_chunks": tra_count,
            "minutes_chunks": min_count,
            "file_size_bytes": file_size_bytes,
            "file_size_kb": round(file_size_kb, 1),
        }

    def get_indexed_session_ids(self) -> List[str]:
        """Retorna lista com IDs de todas as sessões indexadas."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT session_id FROM sessions_index_control ORDER BY session_id DESC").fetchall()
            return [r["session_id"] for r in rows]
