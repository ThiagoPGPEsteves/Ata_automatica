"""
Cliente HTTP para o Ollama Local com Descarregamento Imediato de RAM
Comunica com o Ollama em http://localhost:11434 garantindo o envio estrito
de 'keep_alive': '0s' para purgar o modelo da memória RAM logo após a resposta.
"""

import json
import logging
from typing import Optional, List, Dict, Any, Callable
import requests

from src.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)


class OllamaConnectionError(Exception):
    """Lançada quando o servidor do Ollama não está acessível em localhost."""
    pass


class OllamaModelNotFoundError(Exception):
    """Lançada quando o modelo solicitado não está instalado no Ollama."""
    pass


class OllamaClient:
    """
    Cliente REST leve para o Ollama local.
    Garante que a diretiva 'keep_alive': '0s' seja sempre transmitida
    para respeitar a restrição de no máximo 4GB de RAM.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        default_model: str = OLLAMA_MODEL,
        keep_alive: str = OLLAMA_KEEP_ALIVE,
        timeout: float = OLLAMA_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.keep_alive = keep_alive
        self.timeout = timeout

    def is_available(self) -> bool:
        """Verifica se o daemon do Ollama está rodando e respondendo em localhost."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2.5)
            return resp.status_code == 200
        except Exception:
            return False

    def list_installed_models(self) -> List[str]:
        """Retorna a lista de modelos atualmente baixados e disponíveis no Ollama."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return [m for m in models if m]
            return []
        except requests.exceptions.ConnectionError:
            raise OllamaConnectionError(
                f"Não foi possível conectar ao Ollama em {self.base_url}. "
                "Verifique se o Ollama está instalado e em execução (execute 'ollama serve' no terminal)."
            )

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        keep_alive: Optional[str] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        on_chunk_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Envia prompt para o modelo gerar a ata de reunião.
        Parâmetro 'keep_alive': '0s' é enviado obrigatoriamente para descarregar a RAM.
        Suporta stream_callback ou on_chunk_callback para streaming de tokens.
        """
        callback = stream_callback or on_chunk_callback
        selected_model = model or self.default_model
        active_keep_alive = keep_alive if keep_alive is not None else self.keep_alive

        payload: Dict[str, Any] = {
            "model": selected_model,
            "prompt": prompt,
            "stream": callback is not None,
            "keep_alive": active_keep_alive,  # <-- OBRIGATÓRIO: '0s' libera a memória imediatamente
        }
        if system:
            payload["system"] = system

        logger.info(
            "Chamando Ollama ('%s', keep_alive='%s')...",
            selected_model,
            active_keep_alive,
        )

        try:
            if callback:
                # Modo streaming: emite tokens à medida que chegam
                full_text = []
                with requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=self.timeout,
                ) as response:
                    if response.status_code == 404:
                        raise OllamaModelNotFoundError(
                            f"Modelo '{selected_model}' não encontrado no Ollama. "
                            f"Instale-o executando: ollama pull {selected_model}"
                        )
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if line:
                            chunk = json.loads(line.decode("utf-8"))
                            token = chunk.get("response", "")
                            full_text.append(token)
                            callback(token)
                            if chunk.get("done", False):
                                break

                output = "".join(full_text)
            else:
                # Modo síncrono direto
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Modelo '{selected_model}' não encontrado no Ollama. "
                        f"Instale-o executando: ollama pull {selected_model}"
                    )
                response.raise_for_status()
                data = response.json()
                output = data.get("response", "")

            logger.info(
                "Resposta do Ollama recebida com sucesso (%d caracteres). Modelo configurado para descarregar.",
                len(output),
            )
            return output

        except requests.exceptions.ConnectionError:
            raise OllamaConnectionError(
                f"Não foi possível conectar ao Ollama em {self.base_url}. "
                "Verifique se o Ollama está rodando no computador."
            )
        except requests.exceptions.Timeout:
            raise TimeoutError(f"Tempo limite ({self.timeout}s) excedido ao aguardar resposta do Ollama.")
