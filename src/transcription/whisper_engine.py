"""
Motor de Transcrição Local com faster-whisper
Executa em CPU com quantização int8, seleção dinâmica de modelo por disponibilidade
de RAM e descarregamento ativo de memória imediatamente após o uso.
"""

import gc
import os
import psutil
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import numpy as np

from src.config import (
    WHISPER_DEFAULT_MODEL,
    WHISPER_FALLBACK_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CPU_THREADS,
    WHISPER_LANGUAGE,
    MIN_FREE_RAM_FOR_SMALL_MODEL_MB,
)

logger = logging.getLogger(__name__)


def get_available_ram_mb() -> float:
    """Retorna a quantidade de memória RAM física disponível em Megabytes."""
    return psutil.virtual_memory().available / (1024 * 1024)


def get_process_ram_mb() -> float:
    """Retorna o consumo de memória RAM do processo atual em Megabytes."""
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def select_optimal_model_size(preferred_model: Optional[str] = None) -> str:
    """
    Seleciona o tamanho de modelo ideal avaliando a memória RAM livre no Windows.
    Se a RAM livre for >= 1500 MB, usa 'small' (alta fidelidade a termos técnicos corporativos).
    Caso contrário, faz fallback automático para 'base' (~250 MB de RAM).
    """
    if preferred_model:
        return preferred_model

    free_ram = get_available_ram_mb()
    logger.info("Memória RAM disponível para transcrição: %.2f MB", free_ram)

    if free_ram >= MIN_FREE_RAM_FOR_SMALL_MODEL_MB:
        selected = WHISPER_DEFAULT_MODEL  # "small"
        logger.info("RAM suficiente detectada. Modelo selecionado: '%s'", selected)
    else:
        selected = WHISPER_FALLBACK_MODEL  # "base"
        logger.warning(
            "RAM livre abaixo de %d MB. Ativando fallback automático para o modelo leve: '%s'",
            MIN_FREE_RAM_FOR_SMALL_MODEL_MB,
            selected,
        )
    return selected


class WhisperEngine:
    """
    Gerencia o ciclo de vida do modelo faster-whisper.
    Projetado com garantia de Zero-Overlap Memory: pode ser usado como context manager
    ('with WhisperEngine() as engine:') para descarregar os pesos da RAM automaticamente.
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        language: str = WHISPER_LANGUAGE,
        compute_type: str = WHISPER_COMPUTE_TYPE,
        cpu_threads: int = WHISPER_CPU_THREADS,
    ):
        self.language = language
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.model_size = select_optimal_model_size(model_size)

        self._model = None
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def load(self):
        """Carrega os pesos do modelo na memória RAM."""
        if self._is_loaded:
            return

        ram_before = get_process_ram_mb()
        logger.info(
            "Carregando faster-whisper ('%s', %s, %s threads)... RAM antes: %.2f MB",
            self.model_size,
            self.compute_type,
            self.cpu_threads,
            ram_before,
        )

        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_size,
            device=WHISPER_DEVICE,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )
        self._is_loaded = True

        ram_after = get_process_ram_mb()
        logger.info(
            "Modelo '%s' carregado com sucesso. RAM após carga: %.2f MB (+%.2f MB)",
            self.model_size,
            ram_after,
            ram_after - ram_before,
        )

    def transcribe(
        self,
        audio_input: Union[str, Path, np.ndarray],
        beam_size: int = 3,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = "Reunião de negócios corporativa no Microsoft Teams com ata e decisões.",
    ) -> List[Dict[str, Any]]:
        """
        Transcreve o áudio (arquivo no disco ou array numpy mono 16kHz float32/int16).
        Retorna uma lista de dicionários contendo start, end e text.
        """
        if not self._is_loaded:
            self.load()

        logger.info("Iniciando transcrição de áudio...")

        # faster-whisper aceita np.ndarray em float32 normalizado entre -1.0 e 1.0
        if isinstance(audio_input, np.ndarray):
            if audio_input.dtype == np.int16:
                audio_input = audio_input.astype(np.float32) / 32768.0
            elif audio_input.dtype != np.float32:
                audio_input = audio_input.astype(np.float32)

        segments_generator, info = self._model.transcribe(
            audio_input,
            language=self.language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters=dict(min_silence_duration_ms=400),
            initial_prompt=initial_prompt,
        )

        logger.info(
            "Idioma detectado: '%s' com probabilidade %.2f%%. Duração: %.2fs",
            info.language,
            info.language_probability * 100,
            info.duration,
        )

        results = []
        for segment in segments_generator:
            text = segment.text.strip()
            if text:
                results.append(
                    {
                        "start": round(segment.start, 2),
                        "end": round(segment.end, 2),
                        "text": text,
                    }
                )

        logger.info("Transcrição concluída: %d segmentos identificados.", len(results))
        return results

    def unload(self):
        """
        Descarrega explicitamente o modelo da memória RAM e força o Garbage Collector.
        Garante que a memória volte para o estado inicial (~45 MB).
        """
        if not self._is_loaded:
            return

        ram_before = get_process_ram_mb()
        logger.info("Descarregando modelo faster-whisper da memória RAM... RAM antes: %.2f MB", ram_before)

        del self._model
        self._model = None
        self._is_loaded = False

        # Força coleta de lixo no Python
        gc.collect()

        ram_after = get_process_ram_mb()
        logger.info(
            "Modelo descarregado com sucesso. RAM pós-liberação: %.2f MB (-%.2f MB liberados)",
            ram_after,
            ram_before - ram_after,
        )

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
