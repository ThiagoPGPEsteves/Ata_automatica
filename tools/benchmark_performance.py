"""
Ferramenta CLI de Benchmark de Desempenho e Recursos (Fase P4)
Mede cientificamente o Fator de Tempo Real (RTF), tempo de inferência,
velocidade de descarregamento e consumo consolidado de memória RAM (App + Ollama).
"""

import sys
import os
import time
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
from src.transcription.whisper_engine import WhisperEngine
from src.utils.telemetry import SystemMemoryAuditor, RTFEstimator, has_speech_activity
from src.pipeline.session import SessionStore


def run_benchmark(wav_path: Path, models_to_test: list):
    print("\n" + "=" * 88)
    print("  BENCHMARK DE DESEMPENHO E AUDITORIA DE RECURSOS (Fase P4)")
    print(f"  Arquivo: {wav_path.resolve()}")
    print("=" * 88)

    if not wav_path.exists():
        print(f"\n[ERRO] Arquivo não encontrado: {wav_path}")
        return

    mic, loop, sr = split_dual_channel_audio(wav_path)
    dur_sec = len(mic) / sr if sr > 0 else 0.1

    print(f"\n• Especificações do Áudio de Teste:")
    print(f"  - Duração total: {dur_sec:.2f}s ({len(mic)} amostras a {sr}Hz)")
    print(f"  - Atividade vocal Mic (Você): {'Sim' if has_speech_activity(mic) else 'Não (Silencioso)'}")
    print(f"  - Atividade vocal Teams: {'Sim' if has_speech_activity(loop) else 'Não (Silencioso)'}")

    auditor = SystemMemoryAuditor()
    init_mem = auditor.get_total_pipeline_ram_mb()
    print(f"\n• Estado Inicial de Memória:")
    print(f"  - RAM App Python: {init_mem['app_mb']:.1f} MB")
    print(f"  - RAM Ollama daemon: {init_mem['ollama_mb']:.1f} MB")
    print(f"  - RAM Total Pipeline: {init_mem['total_pipeline_mb']:.1f} MB")
    print(f"  - RAM Livre no Windows: {init_mem['system_available_mb']:.1f} MB ({init_mem['system_used_pct']}% em uso)")

    results = []

    # Testa até 60 segundos de áudio para um benchmark ágil
    test_len = min(len(loop), sr * 60)
    audio_sample = loop[:test_len]
    test_dur_sec = len(audio_sample) / sr

    print(f"\n• Executando inferência com amostra de {test_dur_sec:.1f}s...")

    for model_name in models_to_test:
        print(f"\n  [Testando faster-whisper '{model_name}']...")
        try:
            with WhisperEngine(model_size=model_name) as engine:
                t0 = time.time()
                mem_loaded = auditor.get_total_pipeline_ram_mb()

                segments = engine.transcribe(
                    audio_sample,
                    channel_label=f"benchmark_{model_name}",
                )
                elapsed = max(0.001, time.time() - t0)
                rtf = elapsed / test_dur_sec

            # Após descarregamento (with statement fez unload)
            mem_after = auditor.get_total_pipeline_ram_mb()

            results.append({
                "model": model_name,
                "audio_sec": test_dur_sec,
                "elapsed_sec": elapsed,
                "rtf": rtf,
                "segments": len(segments),
                "peak_app_mb": mem_loaded["app_mb"],
                "ollama_mb": mem_loaded["ollama_mb"],
                "total_mb": mem_loaded["total_pipeline_mb"],
            })
        except Exception as e:
            print(f"    [ERRO] Falha ao testar modelo '{model_name}': {e}")

    # Exibe tabela comparativa
    print("\n" + "=" * 88)
    print(f"{'Modelo':<16} | {'Duração':<9} | {'Tempo Proc.':<12} | {'RTF':<7} | {'App RAM':<10} | {'Ollama RAM':<11} | {'Total RAM':<10}")
    print("-" * 88)
    for r in results:
        print(
            f"{r['model']:<16} | "
            f"{r['audio_sec']:>6.1f}s   | "
            f"{r['elapsed_sec']:>9.2f}s   | "
            f"{r['rtf']:>5.2f}x | "
            f"{r['peak_app_mb']:>7.1f} MB | "
            f"{r['ollama_mb']:>8.1f} MB | "
            f"{r['total_mb']:>7.1f} MB"
        )
    print("=" * 88)
    print("  Nota: RTF < 1.0x indica processamento mais rápido que o tempo real de fala.\n")


def main():
    parser = argparse.ArgumentParser(description="Benchmark de Desempenho e Recursos (Fase P4)")
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Arquivo WAV a ser utilizado como base para o benchmark.",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="small,large-v3-turbo",
        help="Modelos a testar separados por vírgula (padrão: small,large-v3-turbo).",
    )
    args = parser.parse_args()

    if args.file:
        wav_path = Path(args.file)
    else:
        store = SessionStore()
        latest = store.get_latest_session()
        if latest and latest.has_audio():
            wav_path = latest.audio_path
        else:
            from src.config import DEFAULT_RECORDING_PATH
            wav_path = DEFAULT_RECORDING_PATH

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    run_benchmark(wav_path, models)


if __name__ == "__main__":
    main()
