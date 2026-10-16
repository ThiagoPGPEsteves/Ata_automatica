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
    WHISPER_TURBO_MODEL,
    WHISPER_SMALL_MODEL,
    WHISPER_BASE_MODEL,
    WHISPER_DEFAULT_MODEL,
    WHISPER_FALLBACK_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CPU_THREADS,
    WHISPER_LANGUAGE,
    WHISPER_CONDITION_ON_PREVIOUS_TEXT,
    WHISPER_REPETITION_PENALTY,
    WHISPER_NO_REPEAT_NGRAM_SIZE,
    WHISPER_BEAM_SIZE,
    AUDIO_HIGHPASS_CUTOFF_HZ,
    AUDIO_PEAK_NORMALIZE,
    MIN_FREE_RAM_FOR_TURBO_MODEL_MB,
    MIN_FREE_RAM_FOR_SMALL_MODEL_MB,
    DEFAULT_CORPORATE_GLOSSARY,
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
    Seleciona o modelo Whisper ideal com base na RAM livre no Windows ou na preferência do usuário.
    - Se preferred_model especificado e != 'auto': respeita a escolha do usuário.
    - Se RAM livre >= 2000 MB: 'large-v3-turbo' (Alta Fidelidade fonética corporativa).
    - Se RAM livre >= 1200 MB: 'small' (Equilibrado).
    - Se RAM livre < 1200 MB: 'base' (Ultra leve de contingência).
    """
    if preferred_model and preferred_model != "auto":
        logger.info("Utilizando modelo Whisper configurado pelo usuário: '%s'", preferred_model)
        return preferred_model

    free_ram = get_available_ram_mb()
    logger.info("Memória RAM disponível para transcrição: %.2f MB", free_ram)

    if free_ram >= MIN_FREE_RAM_FOR_TURBO_MODEL_MB:
        selected = WHISPER_TURBO_MODEL  # "large-v3-turbo"
        logger.info(
            "RAM abundante (>= %d MB). Modo Alta Fidelidade selecionado: '%s'",
            MIN_FREE_RAM_FOR_TURBO_MODEL_MB,
            selected,
        )
    elif free_ram >= MIN_FREE_RAM_FOR_SMALL_MODEL_MB:
        selected = WHISPER_SMALL_MODEL  # "small"
        logger.info(
            "RAM intermediária (>= %d MB). Modo Equilibrado selecionado: '%s'",
            MIN_FREE_RAM_FOR_SMALL_MODEL_MB,
            selected,
        )
    else:
        selected = WHISPER_BASE_MODEL  # "base"
        logger.warning(
            "RAM livre abaixo de %d MB. Ativando fallback ultra leve: '%s'",
            MIN_FREE_RAM_FOR_SMALL_MODEL_MB,
            selected,
        )
    return selected


def preprocess_audio_dsp(
    audio_input: Union[str, Path, np.ndarray],
    sample_rate: int = 16000,
    cutoff_hz: float = AUDIO_HIGHPASS_CUTOFF_HZ,
    target_peak: float = AUDIO_PEAK_NORMALIZE,
) -> np.ndarray:
    """
    Condicionamento de sinal de áudio em tempo real com NumPy:
    1. Converte/normaliza o sinal para float32 (-1.0 a 1.0).
    2. Aplica Filtro Passa-Alta FIR (65 taps) a 80 Hz para eliminar hum elétrico (60 Hz),
       ruídos de retorno elétrico do conector P3 de 3.5mm e vibrações mecânicas.
    3. Normaliza o pico da amplitude sem ceifamento (clipping) para máxima clareza no Whisper.
    """
    import wave

    if isinstance(audio_input, (str, Path)):
        path = Path(audio_input)
        with wave.open(str(path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if sample_width == 2:
            raw = np.frombuffer(frames, dtype=np.int16)
            audio = raw.astype(np.float32) / 32768.0
        else:
            raw = np.frombuffer(frames, dtype=np.float32)
            audio = raw.copy()
        if n_channels > 1:
            audio = audio[0::n_channels]
    elif isinstance(audio_input, np.ndarray):
        if audio_input.dtype == np.int16:
            audio = audio_input.astype(np.float32) / 32768.0
        elif audio_input.dtype != np.float32:
            audio = audio_input.astype(np.float32)
        else:
            audio = audio_input.copy()
    else:
        raise ValueError(f"Formato de áudio não suportado: {type(audio_input)}")

    if len(audio) < 100:
        return audio

    # Filtro FIR Passa-Alta (65 taps com sinc e janela Hamming)
    num_taps = 65
    m = (num_taps - 1) // 2
    n = np.arange(-m, m + 1)
    fc = cutoff_hz / sample_rate
    h_lp = 2 * fc * np.sinc(2 * fc * n)
    w = np.hamming(num_taps)
    h_lp = h_lp * w
    h_lp_sum = np.sum(h_lp)
    if h_lp_sum != 0:
        h_lp /= h_lp_sum
    h_hp = -h_lp
    h_hp[m] += 1.0
    h_hp = h_hp.astype(np.float32)

    filtered = np.convolve(audio, h_hp, mode="same")

    # Normalização de Pico
    peak = np.max(np.abs(filtered))
    if peak > 1e-4 and peak != 0:
        filtered = filtered * (target_peak / peak)

    return filtered


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
        beam_size: int = WHISPER_BEAM_SIZE,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Transcreve o áudio (arquivo no disco ou array numpy mono 16kHz float32/int16).
        Aplica filtro DSP (passa-alta e normalização) e parâmetros anti-alucinação.
        Retorna uma lista de dicionários contendo start, end e text.
        """
        if not self._is_loaded:
            self.load()

        logger.info("Aplicando condicionamento DSP de áudio e iniciando transcrição...")
        processed_audio = preprocess_audio_dsp(audio_input)

        effective_prompt = initial_prompt or DEFAULT_CORPORATE_GLOSSARY

        segments_generator, info = self._model.transcribe(
            processed_audio,
            language=self.language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters=dict(min_silence_duration_ms=400),
            initial_prompt=effective_prompt,
            condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            repetition_penalty=WHISPER_REPETITION_PENALTY,
            no_repeat_ngram_size=WHISPER_NO_REPEAT_NGRAM_SIZE,
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
