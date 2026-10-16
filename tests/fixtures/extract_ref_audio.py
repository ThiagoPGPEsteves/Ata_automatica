"""
Script utilitário para extrair uma amostra de referência de 3 minutos (180s)
do áudio real da reunião gravada (sessions/2026-10-16_114213/audio.wav)
para testes reprodutíveis e benchmarks de precisão (Fase P5).
"""

import sys
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SOURCE_WAV = ROOT_DIR / "sessions" / "2026-10-16_114213" / "audio.wav"
TARGET_DIR = ROOT_DIR / "tests" / "fixtures"
TARGET_WAV = TARGET_DIR / "reference_meeting_3min.wav"


def extract_sample(duration_seconds: float = 180.0):
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    if not SOURCE_WAV.exists():
        print(f"[AVISO] Arquivo de origem não encontrado: {SOURCE_WAV}")
        print("Criando áudio de referência sintético estéreo de fallback...")
        import numpy as np
        sr = 16000
        n = int(sr * duration_seconds)
        t = np.linspace(0, duration_seconds, n, endpoint=False)
        mic = (0.2 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)
        loop = (0.2 * np.sin(2 * np.pi * 400 * t)).astype(np.int16)
        stereo = np.column_stack((mic, loop))

        with wave.open(str(TARGET_WAV), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(stereo.tobytes())
        print(f"Áudio sintético gerado em: {TARGET_WAV}")
        return

    with wave.open(str(SOURCE_WAV), "rb") as wf_in:
        n_channels = wf_in.getnchannels()
        sampwidth = wf_in.getsampwidth()
        framerate = wf_in.getframerate()
        total_frames = wf_in.getnframes()

        frames_to_read = min(total_frames, int(framerate * duration_seconds))
        frames_data = wf_in.readframes(frames_to_read)

    with wave.open(str(TARGET_WAV), "wb") as wf_out:
        wf_out.setnchannels(n_channels)
        wf_out.setsampwidth(sampwidth)
        wf_out.setframerate(framerate)
        wf_out.writeframes(frames_data)

    dur_actual = frames_to_read / framerate
    print(f"Sucesso! Amostra extraída com {dur_actual:.1f}s salva em:")
    print(f"  {TARGET_WAV}")


if __name__ == "__main__":
    extract_sample()
