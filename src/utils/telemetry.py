"""
Módulo de Telemetria de Desempenho e Recursos (Fase P4)
Fornece monitoramento integrado de memória RAM (Processo + Ollama + Sistema),
estimativa dinâmica de Fator de Tempo Real (RTF / ETA) e detecção de atividade de voz (VAD).
"""

import os
import sys
import time
import logging
from typing import Dict, Any, Tuple, Optional, Callable
import numpy as np
import psutil

logger = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """Converte segundos em formato MM:SS ou HH:MM:SS."""
    total_sec = max(0, int(round(seconds)))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def has_speech_activity(
    audio_signal: np.ndarray,
    sample_rate: int = 16000,
    frame_ms: float = 50.0,
    energy_threshold: float = 0.005,
    min_active_frames_pct: float = 0.5,
) -> bool:
    """
    Detecta se o sinal de áudio mono float32 contém atividade vocal mínima acima do piso de ruído.
    Se o canal for puro silêncio ou tiver apenas ruído estático de fundo (RMS < threshold),
    retorna False, permitindo pular a inferência pesada do Whisper.
    """
    if len(audio_signal) == 0:
        return False

    frame_size = int(sample_rate * (frame_ms / 1000.0))
    if frame_size <= 0:
        return True

    num_frames = len(audio_signal) // frame_size
    if num_frames == 0:
        return float(np.sqrt(np.mean(audio_signal**2))) > energy_threshold

    # Analisa energia RMS por quadro
    active_frames = 0
    for i in range(num_frames):
        chunk = audio_signal[i * frame_size : (i + 1) * frame_size]
        rms = float(np.sqrt(np.mean(chunk**2)))
        if rms >= energy_threshold:
            active_frames += 1

    active_pct = (active_frames / num_frames) * 100.0
    return active_pct >= min_active_frames_pct


class RTFEstimator:
    """
    Calcula dinamicamente o Real Time Factor (RTF = tempo_computacional / tempo_áudio)
    e projeta o tempo restante (ETA) para a conclusão da transcrição.
    """

    def __init__(self, total_audio_sec: float):
        self.total_audio_sec = max(0.1, total_audio_sec)
        self.start_wall_time = time.time()
        self.last_rtf = 1.0

    def update(self, processed_audio_sec: float) -> Tuple[float, float, str]:
        """
        Atualiza o progresso com base nos segundos de áudio já transcritos.
        Retorna (progress_pct [0-100], rtf, eta_formatado_str).
        """
        elapsed_audio = max(0.01, min(self.total_audio_sec, processed_audio_sec))
        elapsed_wall = max(0.01, time.time() - self.start_wall_time)

        # RTF = segundos de processador por segundo de áudio gravado
        rtf = elapsed_wall / elapsed_audio
        self.last_rtf = rtf

        remaining_audio = max(0.0, self.total_audio_sec - elapsed_audio)
        eta_seconds = remaining_audio * rtf

        progress_pct = (elapsed_audio / self.total_audio_sec) * 100.0
        eta_str = format_duration(eta_seconds)

        return round(progress_pct, 1), round(rtf, 2), eta_str


class SystemMemoryAuditor:
    """
    Auditor centralizado de memória RAM que consolida:
    1. Consumo do processo Python da aplicação e subprocessos filhos.
    2. Consumo de processos externos vinculados do Ollama (ollama.exe / ollama_llama_server.exe).
    3. Memória disponível e percentual de uso global do sistema operacional.
    """

    def __init__(self, warning_threshold_mb: float = 2500.0):
        self.process = psutil.Process(os.getpid())
        self.warning_threshold_mb = warning_threshold_mb

    def get_app_ram_mb(self) -> float:
        """Retorna a memória RSS da aplicação Python principal e subprocessos filhos em MB."""
        try:
            total_rss = self.process.memory_info().rss
            for child in self.process.children(recursive=True):
                try:
                    total_rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return total_rss / (1024 * 1024)
        except Exception:
            return 0.0

    def get_ollama_ram_mb(self) -> float:
        """
        Varre a tabela de processos do Windows somando o RSS de instâncias ativas do Ollama.
        """
        ollama_rss = 0
        try:
            for p in psutil.process_iter(["name", "memory_info"]):
                try:
                    name = (p.info.get("name") or "").lower()
                    if "ollama" in name or "llama_server" in name:
                        mem = p.info.get("memory_info")
                        if mem:
                            ollama_rss += mem.rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.debug("Não foi possível enumerar processos do Ollama: %s", e)
        return ollama_rss / (1024 * 1024)

    def get_total_pipeline_ram_mb(self) -> Dict[str, float]:
        """
        Retorna dicionário completo com a telemetria consolidada de RAM.
        """
        app_mb = round(self.get_app_ram_mb(), 2)
        ollama_mb = round(self.get_ollama_ram_mb(), 2)
        total_pipeline_mb = round(app_mb + ollama_mb, 2)

        vm = psutil.virtual_memory()
        system_avail_mb = round(vm.available / (1024 * 1024), 2)
        system_total_mb = round(vm.total / (1024 * 1024), 2)
        system_used_pct = round(vm.percent, 1)

        return {
            "app_mb": app_mb,
            "ollama_mb": ollama_mb,
            "total_pipeline_mb": total_pipeline_mb,
            "system_available_mb": system_avail_mb,
            "system_total_mb": system_total_mb,
            "system_used_pct": system_used_pct,
        }

    def log_memory_checkpoint(
        self,
        stage_name: str,
        custom_logger: Optional[logging.Logger] = None,
    ) -> Dict[str, float]:
        """
        Registra um checkpoint formal de memória nos logs e emite aviso se o teto for excedido.
        """
        log = custom_logger or logger
        stats = self.get_total_pipeline_ram_mb()

        msg = (
            f"[TELEMETRIA RAM] {stage_name:<30} | "
            f"App: {stats['app_mb']:>7.2f} MB | "
            f"Ollama: {stats['ollama_mb']:>7.2f} MB | "
            f"Pipeline Total: {stats['total_pipeline_mb']:>7.2f} MB | "
            f"Livre no Windows: {stats['system_available_mb']:>7.2f} MB ({stats['system_used_pct']}% em uso)"
        )

        if stats["total_pipeline_mb"] > self.warning_threshold_mb:
            log.warning(
                "%s | ⚠️ ALERTA: Consumo do pipeline excedeu teto planejado de %.0f MB!",
                msg,
                self.warning_threshold_mb,
            )
        else:
            log.info(msg)

        return stats
