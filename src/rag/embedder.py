"""
Módulo de Geração de Embeddings Locais via Ollama
Gera representações vetoriais densas utilizando o endpoint /api/embed do Ollama local
(modelo nomic-embed-text) com normalização L2 e descarregamento imediato da RAM (keep_alive='0s').
"""

import abc
import logging
from typing import List, Optional, Union
import numpy as np
import requests

from src.config import OLLAMA_URL, OLLAMA_EMBED_MODEL, OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT
from src.minutes.ollama_client import OllamaConnectionError, OllamaModelNotFoundError

logger = logging.getLogger(__name__)


class BaseEmbedder(abc.ABC):
    """Interface abstrata base para provedores de embedding."""

    @abc.abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        """
        Calcula os embeddings normalizados para uma lista de textos.

        Args:
            texts: Lista de strings a serem vetorizadas.

        Returns:
            np.ndarray de formato (len(texts), dimensão) e dtype float32, normalizado (norma L2 = 1.0).
        """
        pass


class OllamaEmbedder(BaseEmbedder):
    """
    Provedor de embeddings 100% offline utilizando Ollama local.
    Transmite sempre 'keep_alive': '0s' para garantir o descarregamento imediato
    do modelo da memória RAM, cumprindo o princípio Zero-Overlap.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = OLLAMA_EMBED_MODEL,
        keep_alive: str = OLLAMA_KEEP_ALIVE,
        timeout: float = OLLAMA_TIMEOUT,
        batch_size: int = 16,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        self.timeout = timeout
        self.batch_size = max(1, batch_size)

    def embed(self, texts: List[str]) -> np.ndarray:
        """
        Gera vetores para os textos informados em lotes com normalização L2.
        """
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        all_embeddings: List[List[float]] = []

        # Processamento sequencial em lotes para evitar requisições gigantescas e estouro de RAM
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embs = self._embed_batch(batch)
            all_embeddings.extend(batch_embs)

        vecs = np.array(all_embeddings, dtype=np.float32)

        # Normalização L2 (essencial para que o produto escalar seja equivalente à similaridade de cosseno)
        norms = np.linalg.norm(vecs, axis=-1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        normalized_vecs = vecs / norms

        return normalized_vecs.astype(np.float32)

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        payload = {
            "model": self.model,
            "input": batch,
            "keep_alive": self.keep_alive,
        }

        url = f"{self.base_url}/api/embed"
        try:
            logger.debug(
                "Chamando Ollama Embed ('%s', lote com %d itens, keep_alive='%s')...",
                self.model,
                len(batch),
                self.keep_alive,
            )
            response = requests.post(url, json=payload, timeout=self.timeout)

            if response.status_code == 404:
                raise OllamaModelNotFoundError(
                    f"Modelo de embedding '{self.model}' não encontrado no Ollama. "
                    f"Instale-o executando no terminal: ollama pull {self.model}"
                )

            response.raise_for_status()
            data = response.json()

            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(batch):
                raise ValueError(
                    f"Quantidade de embeddings retornados ({len(embeddings)}) difere do lote enviado ({len(batch)})."
                )

            return embeddings

        except requests.exceptions.ConnectionError as conn_err:
            raise OllamaConnectionError(
                f"Não foi possível conectar ao Ollama em {self.base_url}. "
                "Verifique se o serviço local do Ollama está em execução."
            ) from conn_err
        except requests.exceptions.Timeout as timeout_err:
            raise TimeoutError(
                f"Tempo limite ({self.timeout}s) excedido ao gerar embeddings no Ollama."
            ) from timeout_err
