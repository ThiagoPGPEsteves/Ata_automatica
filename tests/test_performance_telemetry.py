"""
Testes Automatizados para a Fase P4:
- SystemMemoryAuditor: medicao de RAM do processo Python, processos filhos e Ollama
- RTFEstimator: calculo de Fator de Tempo Real e projecao de ETA
- has_speech_activity: deteccao de atividade vocal e pulo de canais silenciosos
- WhisperEngine: integracao do callback de progresso com telemetria ao vivo
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

# Garante raiz do projeto no sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.utils.telemetry import (
    SystemMemoryAuditor,
    RTFEstimator,
    has_speech_activity,
    format_duration,
)
from src.transcription.whisper_engine import WhisperEngine


def test_format_duration():
    assert format_duration(0) == "00:00"
    assert format_duration(5) == "00:05"
    assert format_duration(65) == "01:05"
    assert format_duration(3600) == "01:00:00"
    assert format_duration(3665) == "01:01:05"


def test_has_speech_activity():
    sr = 16000
    # 1. Silencio absoluto
    silence = np.zeros(sr * 2, dtype=np.float32)
    assert not has_speech_activity(silence, sample_rate=sr)

    # 2. Ruido muito baixo (piso de ruído eletrico)
    low_noise = (np.random.rand(sr * 2) * 0.001).astype(np.float32)
    assert not has_speech_activity(low_noise, sample_rate=sr)

    # 3. Audio com fala clara
    t = np.linspace(0, 2.0, sr * 2, endpoint=False)
    speech = (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    assert has_speech_activity(speech, sample_rate=sr)


def test_rtf_estimator_projection():
    total_audio_sec = 60.0
    estimator = RTFEstimator(total_audio_sec)

    # Simula 20 segundos de áudio processados em 5 segundos de relógio
    estimator.start_wall_time = time.time() - 5.0
    prog_pct, rtf, eta_str = estimator.update(processed_audio_sec=20.0)

    # Progresso esperado: 20/60 = 33.3%
    assert abs(prog_pct - 33.3) <= 0.5
    # RTF esperado: 5s / 20s = 0.25x
    assert abs(rtf - 0.25) <= 0.05
    # ETA esperado: 40s restantes * 0.25 = 10s ("00:10")
    assert eta_str == "00:10"


def test_system_memory_auditor_accounting():
    auditor = SystemMemoryAuditor(warning_threshold_mb=2500.0)

    app_ram = auditor.get_app_ram_mb()
    assert app_ram > 0.0, "App RAM deve ser maior que zero"

    ollama_ram = auditor.get_ollama_ram_mb()
    assert ollama_ram >= 0.0, "Ollama RAM deve ser não-negativo"

    telemetry = auditor.get_total_pipeline_ram_mb()
    assert "app_mb" in telemetry
    assert "ollama_mb" in telemetry
    assert "total_pipeline_mb" in telemetry
    assert "system_available_mb" in telemetry
    # Verifica consistência interna da soma (tolerando pequenas flutuações entre chamadas)
    assert telemetry["total_pipeline_mb"] == round(telemetry["app_mb"] + telemetry["ollama_mb"], 2)
    assert telemetry["app_mb"] > 0.0
    assert telemetry["ollama_mb"] >= 0.0

    # Teste de emissão de checkpoint sem exceções
    logged_stats = auditor.log_memory_checkpoint("Teste Unitário")
    assert "total_pipeline_mb" in logged_stats
    assert logged_stats["total_pipeline_mb"] == round(logged_stats["app_mb"] + logged_stats["ollama_mb"], 2)


def test_whisper_engine_progress_eta_callback():
    """Valida que o WhisperEngine emite mensagens com ETA e RTF durante a transcrição."""
    engine = WhisperEngine(model_size="base")
    engine._is_loaded = True
    engine._model = MagicMock()

    class FakeSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    fake_segments = [
        FakeSegment(0.0, 5.0, "Primeiro segmento"),
        FakeSegment(5.0, 10.0, "Segundo segmento"),
    ]
    fake_info = MagicMock()
    fake_info.duration = 10.0
    fake_info.language = "pt"
    fake_info.language_probability = 0.99

    engine._model.transcribe.return_value = (fake_segments, fake_info)

    captured_updates = []

    def on_progress(msg, pct):
        captured_updates.append((msg, pct))

    dummy_audio = np.zeros(16000 * 10, dtype=np.float32)
    results = engine.transcribe(
        dummy_audio,
        progress_callback=on_progress,
        channel_label="teste",
    )

    assert len(results) == 2
    assert len(captured_updates) == 2
    # Verifica que a mensagem contém as palavras-chave ETA e RTF
    assert "ETA:" in captured_updates[0][0]
    assert "RTF:" in captured_updates[0][0]
    assert captured_updates[-1][1] > captured_updates[0][1]
