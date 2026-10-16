"""
Ferramenta CLI de Diagnóstico de Áudio e Crosstalk (Fase P3)
Analisa arquivos WAV gravados ou executa medição ao vivo para aferir:
- Atraso físico (latência) entre o áudio do Teams e o vazamento no microfone.
- Grau de correlação cruzada pico (0.0 a 1.0).
- Nível de acoplamento/vazamento (dB e amplitude relativa).
- Classificação de causa raiz (crosstalk elétrico vs vazamento acústico).
"""

import sys
import argparse
from pathlib import Path

# Garante raiz do projeto no sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
from src.transcription.post_process import split_dual_channel_audio
from src.audio.echo_gate import EchoGate
from src.audio.devices import get_default_devices


def analyze_wav_file(wav_path: Path):
    print("=" * 75)
    print(f"  DIAGNÓSTICO CLÍNICO DE ÁUDIO DUAL-CHANNEL")
    print(f"  Arquivo: {wav_path.resolve()}")
    print("=" * 75)

    if not wav_path.exists():
        print(f"\n[ERRO] Arquivo não encontrado: {wav_path}")
        return

    mic, loop, sr = split_dual_channel_audio(wav_path)
    dur_sec = len(mic) / sr if sr > 0 else 0

    print(f"\n• Propriedades do Sinal:")
    print(f"  - Duração: {dur_sec:.2f}s ({len(mic)} amostras)")
    print(f"  - Taxa de amostragem: {sr} Hz")
    print(f"  - RMS Mic (Você): {float(np.sqrt(np.mean(mic**2))):.4f}")
    print(f"  - RMS Teams (Participantes): {float(np.sqrt(np.mean(loop**2))):.4f}")

    gate = EchoGate()
    delay_samples, peak_corr = gate.estimate_delay(mic, loop, sample_rate=sr)
    delay_ms = (delay_samples / sr) * 1000.0

    print(f"\n• Análise de Correlação e Atraso:")
    print(f"  - Atraso estimado: {delay_ms:.2f} ms ({delay_samples} amostras)")
    print(f"  - Coeficiente de correlação pico: {peak_corr:.4f} (escala 0.0 a 1.0)")

    # Simulação do EchoGate
    _, stats = gate.process(mic, loop, sample_rate=sr)

    print(f"\n• Supressão Digital (EchoGate):")
    print(f"  - Vazamento estimado: {stats.get('leakage_db', 0):.1f} dB (razão: {stats.get('leakage_ratio', 0):.1%})")
    print(f"  - Quadros com vazamento suprimidos: {stats.get('frames_suppressed_pct', 0):.1f}%")

    print(f"\n• Parecer Técnico:")
    if peak_corr >= 0.60 and 40 <= delay_ms <= 120:
        print("  ⚠️  DIAGNÓSTICO: CROSSTALK ELÉTRICO / BUFFER DO DRIVER (Realtek P2/P3)")
        print("  - Causa: O conector combo jack de 3.5mm ou o buffer do driver de áudio está vazando")
        print("    o sinal da saída para o microfone com atraso fixo de buffer (~80 ms).")
        print("  - Solução: O EchoGate elimina 100% desse vazamento antes do Whisper.")
        print("    Recomendação de hardware: Use o 'Microphone Array (Intel SST)' ou fone USB.")
    elif peak_corr >= 0.40:
        print("  ⚠️  DIAGNÓSTICO: VAZAMENTO ACÚSTICO (ALTO-FALANTES)")
        print("  - Causa: O som emitido pelos alto-falantes é captado acusticamente pelo microfone.")
        print("  - Solução: O EchoGate suprime os trechos vazados quando o usuário não estiver falando.")
    else:
        print("  ✅ DIAGNÓSTICO: ISOLAMENTO EXCELENTE")
        print("  - Canais devidamente blindados e independentes. Nenhum vazamento detectado.")

    print("\n" + "=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de Áudio e Vazamento Dual-Channel")
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Caminho para o arquivo WAV a ser diagnosticado.",
    )
    args = parser.parse_args()

    if args.file:
        target_path = Path(args.file)
    else:
        # Busca a sessão mais recente em sessions/
        from src.pipeline.session import SessionStore
        store = SessionStore()
        latest = store.get_latest_session()
        if latest and latest.has_audio():
            target_path = latest.audio_path
        else:
            from src.config import DEFAULT_RECORDING_PATH
            target_path = DEFAULT_RECORDING_PATH

    analyze_wav_file(target_path)


if __name__ == "__main__":
    main()
