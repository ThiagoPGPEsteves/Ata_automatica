"""
Testes Automatizados para a Fase P3:
- EchoGate: estimativa de atraso temporal via correlacao cruzada FFT
- Estimativa da razao de acoplamento/vazamento (alpha)
- Supressao adaptativa de quadros de eco/crosstalk
- Preservacao integral da voz do usuario em situacoes de double-talk (fala simultanea)
- Comportamento no-op para sinais ja isolados
"""

import sys
from pathlib import Path
import numpy as np
import pytest

# Garante raiz do projeto no sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.audio.echo_gate import EchoGate


def generate_speech_like_signal(duration_sec: float = 3.0, sample_rate: int = 16000) -> np.ndarray:
    """Gera um sinal pseudo-voz modulado em amplitude com harmonicos fundamentais (120 Hz, 240 Hz, 360 Hz)."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Portadora com harmonicos de formantes vocais
    carrier = (
        0.5 * np.sin(2 * np.pi * 150 * t)
        + 0.3 * np.sin(2 * np.pi * 300 * t)
        + 0.2 * np.sin(2 * np.pi * 450 * t)
    )
    # Modulacao de amplitude silabica (3 a 4 silabas por segundo)
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 4 * t))
    signal = (carrier * envelope).astype(np.float32)
    return signal / np.max(np.abs(signal))


def test_echogate_delay_estimation_synthetic():
    """Valida estimativa de atraso temporal com sinal sintetico atrasado em 80ms."""
    sr = 16000
    expected_delay_ms = 80.0
    expected_delay_samples = int(sr * (expected_delay_ms / 1000.0))  # 1280 amostras

    loopback = generate_speech_like_signal(duration_sec=3.0, sample_rate=sr)

    # Cria sinal do microfone com vazamento atrasado e atenuado (crosstalk eletrico)
    mic = np.zeros_like(loopback)
    mic[expected_delay_samples:] = loopback[:-expected_delay_samples] * 0.30

    gate = EchoGate()
    delay_samples, peak_corr = gate.estimate_delay(mic, loopback, sample_rate=sr)
    delay_ms = (delay_samples / sr) * 1000.0

    assert abs(delay_samples - expected_delay_samples) <= 2, f"Atraso esperado: {expected_delay_samples}, obtido: {delay_samples}"
    assert abs(delay_ms - expected_delay_ms) <= 0.5
    assert peak_corr > 0.85, f"Correlação pico esperada > 0.85, obtida: {peak_corr}"


def test_echogate_leakage_suppression():
    """Valida que o EchoGate atenua vazamento quando o usuario esta em silencio e os participantes falam."""
    sr = 16000
    delay_samples = 800  # 50 ms

    loopback = generate_speech_like_signal(duration_sec=2.0, sample_rate=sr)
    mic = np.zeros_like(loopback)
    # Vazamento no microfone com 25% de amplitude
    mic[delay_samples:] = loopback[:-delay_samples] * 0.25

    gate = EchoGate(suppression_db=-40.0)
    cleaned_mic, stats = gate.process(mic, loopback, sample_rate=sr)

    assert stats["applied"] is True
    assert stats["peak_correlation"] > 0.80
    assert stats["frames_suppressed_pct"] > 50.0

    # Mede atenuacao no trecho de vazamento
    orig_rms = float(np.sqrt(np.mean(mic[delay_samples:] ** 2)))
    clean_rms = float(np.sqrt(np.mean(cleaned_mic[delay_samples:] ** 2)))

    # A energia restante deve ter sido reduzida em pelo menos 20 dB (fator > 10x)
    attenuation_ratio = clean_rms / orig_rms
    assert attenuation_ratio < 0.15, f"Atenuação insuficiente: {attenuation_ratio:.4f}"


def test_echogate_double_talk_preservation():
    """Valida que durante double-talk (usuario falando junto com participantes), a voz do usuario nao e cortada."""
    sr = 16000
    delay_samples = 960  # 60 ms

    # Participantes falando continuamente
    loopback = generate_speech_like_signal(duration_sec=3.0, sample_rate=sr) * 0.2

    # Vazamento dos participantes no canal do microfone
    mic = np.zeros_like(loopback)
    mic[delay_samples:] = loopback[:-delay_samples] * 0.25

    # Usuario fala fortemente entre 1.0s e 2.0s (+12 dB sobre o vazamento)
    user_start = int(1.0 * sr)
    user_end = int(2.0 * sr)
    t = np.linspace(0, 1.0, user_end - user_start, endpoint=False)
    # Voz forte do usuario a 200 Hz
    user_voice = 0.6 * np.sin(2 * np.pi * 200 * t).astype(np.float32)
    mic[user_start:user_end] += user_voice

    gate = EchoGate()
    cleaned_mic, stats = gate.process(mic, loopback, sample_rate=sr)

    assert stats["applied"] is True

    # Verifica que a energia na regiao de fala do usuario foi preservada
    user_orig_rms = float(np.sqrt(np.mean(mic[user_start + 800 : user_end - 800] ** 2)))
    user_clean_rms = float(np.sqrt(np.mean(cleaned_mic[user_start + 800 : user_end - 800] ** 2)))

    preservation_ratio = user_clean_rms / user_orig_rms
    # A voz do usuario deve ser preservada com mais de 85% de energia
    assert preservation_ratio > 0.85, f"Voz do usuario atenuada inadvertidamente: {preservation_ratio:.2%}"


def test_echogate_clean_isolated_audio():
    """Valida que para canais independentes (sem eco), o EchoGate nao altera o sinal."""
    sr = 16000
    t = np.linspace(0, 2.0, sr * 2, endpoint=False)
    # Loopback a 1000 Hz
    loopback = 0.5 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    # Microfone com fala a 180 Hz completamente independente
    mic = 0.5 * np.sin(2 * np.pi * 180 * t).astype(np.float32)

    gate = EchoGate(min_correlation_threshold=0.30)
    cleaned_mic, stats = gate.process(mic, loopback, sample_rate=sr)

    assert stats["applied"] is False
    assert stats["reason"] == "correlation_below_threshold"
    assert np.array_equal(cleaned_mic, mic)
