"""
Módulo RAG ('Pergunte às suas atas') para Ata Automática
Fornece busca vetorial e síntese de respostas com citações 100% offline via Ollama.
"""

from src.rag.embedder import BaseEmbedder, OllamaEmbedder
from src.rag.chunker import DocumentChunk, SessionChunker, compute_session_content_hash
from src.rag.store import VectorStore, SearchResult
from src.rag.retriever import RagRetriever
from src.rag.answerer import RagAnswerer, RagAnswer, SourceCitation
from src.rag.service import RagService

__all__ = [
    "BaseEmbedder",
    "OllamaEmbedder",
    "DocumentChunk",
    "SessionChunker",
    "compute_session_content_hash",
    "VectorStore",
    "SearchResult",
    "RagRetriever",
    "RagAnswerer",
    "RagAnswer",
    "SourceCitation",
    "RagService",
]
