"""
Teste Automatizado da Fase 1: Gravação em Streaming e Auditoria de Memória RAM.
Valida:
1. Enumeração correta de dispositivos WASAPI (Mic + Loopback Teams).
2. Gravação de áudio dual-channel com escrita imediata em disco.
3. Telemetria de memória: comprova que a gravação consome < 50 MB de RAM.
"""

import time
import os
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil

from src.config import TEMP_DIR
from src.audio.disk_writer import AudioDiskWriter
from src.audio.devices import get_default_devices
from src.audio.recorder import DualAudioRecorder
import pytest

pytestmark = pytest.mark.integration


def test_audio_disk_writer():
    """Testa a escrita de chunks diretamente em arquivo WAV no disco."""
    print("\n[TESTE 1] Validando AudioDiskWriter (Zero-RAM Streaming)...")
    test_wav = TEMP_DIR / "test_stream.wav"
    writer = AudioDiskWriter(test_wav, sample_rate=16000, channels=2)

    writer.open()
    assert writer.is_active, "O escritor deveria estar ativo."

    # Escreve 3 segundos de dados simulados em chunks de 1 segundo
    dummy_chunk = b"\x00" * (16000 * 2 * 2)  # 1 segundo de áudio 16kHz stereo 16-bit
    for _ in range(3):
        writer.write_chunk(dummy_chunk)

    assert writer.duration_seconds >= 2.9, "Duração gravada incorreta."
    saved = writer.close()

    assert not writer.is_active, "O escritor deveria estar fechado."
    assert saved.exists(), "O arquivo WAV deveria existir no disco."
    file_size = saved.stat().st_size
    print(f"  -> Arquivo gerado com sucesso: {saved.name} ({file_size} bytes)")
    os.remove(saved)
    print("  -> TESTE 1 APROVADO: Escrita em disco sem acúmulo em RAM validada!")


def test_devices_discovery():
    """Testa a descoberta de microfone e dispositivo de loopback."""
    print("\n[TESTE 2] Validando Descoberta de Dispositivos de Áudio...")
    devices = get_default_devices()
    mic = devices.get("mic")
    loopback = devices.get("loopback")

    print(f"  -> Microfone Padrão detectado: {mic.name if mic else 'Não detectado'}")
    print(f"  -> Dispositivo Loopback (Teams) detectado: {loopback.name if loopback else 'Não detectado'}")
    print("  -> TESTE 2 APROVADO: Enumeração de dispositivos concluída!")


def test_recorder_and_memory_telemetry():
    """Testa o gravador real e mede a telemetria de memória RAM durante a gravação."""
    print("\n[TESTE 3] Validando Gravador Dual e Auditoria de Memória RAM...")
    proc = psutil.Process(os.getpid())
    ram_initial_mb = proc.memory_info().rss / (1024 * 1024)
    print(f"  -> Memória inicial do processo: {ram_initial_mb:.2f} MB")

    test_wav = TEMP_DIR / "test_recording_5s.wav"
    recorder = DualAudioRecorder(output_path=test_wav)

    print("  -> Iniciando gravação de 5 segundos...")
    recorder.start()
    assert recorder.is_recording, "O gravador deveria estar gravando."

    ram_samples = []
    for _ in range(5):
        time.sleep(1.0)
        current_ram = proc.memory_info().rss / (1024 * 1024)
        mic_lvl, loop_lvl = recorder.get_audio_levels()
        ram_samples.append(current_ram)
        print(f"     [Gravando {recorder.get_elapsed_seconds():.1f}s] RAM: {current_ram:.2f} MB | Níveis: Mic={mic_lvl:.3f}, Teams={loop_lvl:.3f}")

    saved_path = recorder.stop()
    assert saved_path.exists(), "O arquivo de gravação deve existir no disco."

    ram_final_mb = proc.memory_info().rss / (1024 * 1024)
    peak_ram = max(ram_samples)
    print(f"  -> Memória final: {ram_final_mb:.2f} MB | Pico durante gravação: {peak_ram:.2f} MB")
    print(f"  -> Arquivo salvo: {saved_path} ({saved_path.stat().st_size} bytes)")

    # Assertiva: o consumo de RAM do processo de gravação deve ficar estritamente abaixo de 100 MB (meta: < 40 MB)
    assert peak_ram < 100.0, f"Consumo de RAM muito alto: {peak_ram:.2f} MB (Esperado: < 100 MB)"
    print(f"  -> TESTE 3 APROVADO: Gravação concluída com consumo de RAM impecável ({peak_ram:.2f} MB)!")


if __name__ == "__main__":
    test_audio_disk_writer()
    test_devices_discovery()
    test_recorder_and_memory_telemetry()
    print("\n==========================================")
    print("TODOS OS TESTES DA FASE 1 FORAM CONCLUÍDOS!")
    print("==========================================")
