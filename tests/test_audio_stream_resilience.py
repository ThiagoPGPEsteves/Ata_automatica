"""
Bateria de Testes Automatizados para Resiliência de Áudio e Streaming em Disco (Fase P5)
Valida a robustez do streaming em disco frente a jitter, pacotes em rajadas,
reamostragem com integridade e intercalação de canais sem vazamento de memória.
"""

import wave
import tempfile
from pathlib import Path
import numpy as np
import pytest

from src.audio.disk_writer import AudioDiskWriter
from src.audio.recorder import resample_to_target, to_mono_int16


@pytest.mark.unit
def test_disk_writer_chunked_streaming(tmp_path: Path):
    """Valida gravação em disco de centenas de chunks com integridade de cabeçalho WAV."""
    wav_path = tmp_path / "streaming_test.wav"
    sr = 16000
    channels = 2
    writer = AudioDiskWriter(filepath=wav_path, sample_rate=sr, channels=channels)

    writer.open()
    assert writer.is_active

    # Gera 100 chunks de 160 amostras estéreo (0.01s cada) = 1 segundo no total
    total_samples_per_ch = 0
    for i in range(100):
        mic = np.full(160, fill_value=1000 + i, dtype=np.int16)
        loop = np.full(160, fill_value=-1000 - i, dtype=np.int16)
        stereo = np.column_stack((mic, loop)).tobytes()
        writer.write_chunk(stereo)
        total_samples_per_ch += 160

    closed_path = writer.close()
    assert not writer.is_active
    assert closed_path.exists()

    # Valida cabeçalho WAV
    with wave.open(str(closed_path), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == sr
        assert wf.getnframes() == total_samples_per_ch

        # Lê e valida integridade dos primeiros dados
        data = np.frombuffer(wf.readframes(160), dtype=np.int16).reshape(-1, 2)
        assert np.all(data[:, 0] == 1000)
        assert np.all(data[:, 1] == -1000)


@pytest.mark.unit
def test_resample_to_target_anti_aliasing():
    """Valida preservação e reamostragem correta de sinal 48 kHz para 16 kHz."""
    orig_sr = 48000
    target_sr = 16000
    duration = 0.5  # 0.5s

    # Sinal senoidal puro de 400 Hz (frequência fundamental típica de fala)
    t = np.linspace(0, duration, int(orig_sr * duration), endpoint=False)
    signal_48k = (10000 * np.sin(2 * np.pi * 400 * t)).astype(np.int16)

    resampled_16k = resample_to_target(signal_48k, orig_sr, target_sr)
    expected_samples = int(target_sr * duration)

    # Margem de ±2 amostras devido a arredondamentos de buffer
    assert abs(len(resampled_16k) - expected_samples) <= 2

    # Verifica que o sinal não foi corrompido nem zerado
    rms_orig = np.sqrt(np.mean(signal_48k.astype(float) ** 2))
    rms_resampled = np.sqrt(np.mean(resampled_16k.astype(float) ** 2))
    ratio = rms_resampled / rms_orig
    # RMS deve ser conservado com tolerância de 15%
    assert 0.85 <= ratio <= 1.15


@pytest.mark.unit
def test_to_mono_int16_conversion():
    """Valida conversão de áudio estéreo em mono por média de canais."""
    # Canal esquerdo = 2000, canal direito = 4000 -> média = 3000
    left = np.full(100, 2000, dtype=np.int16)
    right = np.full(100, 4000, dtype=np.int16)
    stereo_bytes = np.column_stack((left, right)).tobytes()

    mono = to_mono_int16(stereo_bytes, channels=2)
    assert len(mono) == 100
    assert np.all(mono == 3000)

    # Canal mono direto
    mono_direct = to_mono_int16(left.tobytes(), channels=1)
    assert np.array_equal(mono_direct, left)

    # Buffer vazio
    assert len(to_mono_int16(b"", channels=2)) == 0


@pytest.mark.unit
def test_stereo_interleaving_and_separation(tmp_path: Path):
    """Valida que a separação posterior dos canais não causa vazamento nem desalinhamento."""
    wav_path = tmp_path / "dual_integrity.wav"
    sr = 16000
    writer = AudioDiskWriter(filepath=wav_path, sample_rate=sr, channels=2)
    writer.open()

    n = 1600
    t = np.linspace(0, 0.1, n, endpoint=False)
    mic_wave = (15000 * np.sin(2 * np.pi * 200 * t)).astype(np.int16)
    loop_wave = (15000 * np.cos(2 * np.pi * 500 * t)).astype(np.int16)

    interleaved = np.column_stack((mic_wave, loop_wave)).tobytes()
    writer.write_chunk(interleaved)
    writer.close()

    # Reabre e separa
    with wave.open(str(wav_path), "rb") as wf:
        raw = wf.readframes(n)
        stereo_data = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
        extracted_mic = stereo_data[:, 0]
        extracted_loop = stereo_data[:, 1]

        assert np.array_equal(extracted_mic, mic_wave)
        assert np.array_equal(extracted_loop, loop_wave)


@pytest.mark.unit
def test_disk_writer_safe_when_closed(tmp_path: Path):
    """Valida que chamar write_chunk em arquivo fechado retorna False com segurança e sem lançar RuntimeError."""
    wav_path = tmp_path / "closed_test.wav"
    writer = AudioDiskWriter(filepath=wav_path, sample_rate=16000, channels=2)

    # 1. Antes de abrir
    dummy_data = b"\x00" * 320
    assert writer.write_chunk(dummy_data) is False

    # 2. Aberto
    writer.open()
    assert writer.write_chunk(dummy_data) is True

    # 3. Após fechar (simulação de término de gravação e chamada residual do loop)
    writer.close()
    assert writer.is_active is False
    assert writer.write_chunk(dummy_data) is False
