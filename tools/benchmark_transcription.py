"""
Ferramenta Científica de Benchmark de Precisão de Transcrição (Fase P5)
Avalia sistematicamente Word Error Rate (WER), Character Error Rate (CER),
Fator de Tempo Real (RTF) e consumo consolidado de RAM entre diferentes
configurações de modelo, filtros DSP e vocabulário corporativo (hotwords).
"""

import sys
import time
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

# Garante a raiz do projeto no sys.path
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
from src.utils.telemetry import SystemMemoryAuditor, has_speech_activity
from src.utils.text_metrics import compute_wer, compute_cer, format_alignment_diff


def run_transcription_benchmark(
    audio_path: Path,
    ground_truth_path: Path,
    models: List[str],
    dsp_modes: List[bool],
    hotwords_list: Optional[str] = None,
    max_duration_sec: Optional[float] = None,
    show_diff: bool = False,
    output_report_path: Optional[Path] = None,
):
    print("\n" + "=" * 94)
    print("  BENCHMARK CIENTÍFICO DE PRECISÃO DE TRANSCRIÇÃO (Fase P5)")
    print(f"  Áudio de Teste: {audio_path.resolve()}")
    print(f"  Ground Truth:   {ground_truth_path.resolve()}")
    print("=" * 94)

    if not audio_path.exists():
        print(f"\n[ERRO] Arquivo de áudio não encontrado: {audio_path}")
        return

    if not ground_truth_path.exists():
        print(f"\n[ERRO] Arquivo de Ground Truth não encontrado: {ground_truth_path}")
        return

    ground_truth_text = ground_truth_path.read_text(encoding="utf-8").strip()

    mic, loop, sr = split_dual_channel_audio(audio_path)
    total_audio_sec = len(loop) / sr if sr > 0 else 0.1

    if max_duration_sec and max_duration_sec > 0:
        limit_samples = int(sr * max_duration_sec)
        mic = mic[:limit_samples]
        loop = loop[:limit_samples]
        total_audio_sec = min(total_audio_sec, max_duration_sec)

    # Identifica o canal com fala principal (geralmente o loopback em reuniões de alinhamento)
    if has_speech_activity(loop):
        active_audio = loop
        active_label = "Teams (Loopback)"
    else:
        active_audio = mic
        active_label = "Microfone"

    print(f"\n• Especificações da Amostra:")
    print(f"  - Duração sob teste: {total_audio_sec:.1f} segundos")
    print(f"  - Canal avaliado:    {active_label}")
    print(f"  - Palavras no GT:    {len(ground_truth_text.split())} palavras")

    auditor = SystemMemoryAuditor()
    init_mem = auditor.get_total_pipeline_ram_mb()
    print(f"\n• Telemetria Inicial de Memória:")
    print(f"  - RAM Aplicação:     {init_mem['app_mb']:.1f} MB")
    print(f"  - RAM Ollama Daemon: {init_mem['ollama_mb']:.1f} MB")
    print(f"  - RAM Livre Windows: {init_mem['system_available_mb']:.1f} MB")

    results = []
    best_result = None
    min_wer = float("inf")

    # Matriz de teste: Modelos x Modos DSP x Hotwords
    test_runs = []
    for model_name in models:
        for dsp_on in dsp_modes:
            # Caso sem hotwords
            test_runs.append((model_name, dsp_on, None))
            # Caso com hotwords (se especificado)
            if hotwords_list:
                test_runs.append((model_name, dsp_on, hotwords_list))

    print(f"\n• Iniciando bateria com {len(test_runs)} variações...")

    for idx, (m_name, dsp_flag, hw) in enumerate(test_runs, 1):
        hw_desc = f"'{hw}'" if hw else "Nenhum"
        print(f"\n  [{idx}/{len(test_runs)}] Testando: Modelo='{m_name}' | DSP={'Ativo' if dsp_flag else 'Desativado'} | Hotwords={hw_desc}")

        try:
            import src.transcription.whisper_engine as we_mod
            we_mod.AUDIO_DSP_ENABLED = dsp_flag

            with WhisperEngine(model_size=m_name) as engine:
                t0 = time.time()
                mem_loaded = auditor.get_total_pipeline_ram_mb()

                # Hotwords ou prompt
                custom_prompt = f"Termos e participantes: {hw}" if hw else None

                segments = engine.transcribe(
                    active_audio,
                    initial_prompt=custom_prompt,
                    hotwords=hw,
                    channel_label="benchmark_wer",
                )
                elapsed = max(0.001, time.time() - t0)
                rtf = elapsed / total_audio_sec

            # Junta texto transcrito
            hyp_parts = []
            for s in segments:
                t_str = s["text"].strip() if isinstance(s, dict) else getattr(s, "text", "").strip()
                if t_str:
                    hyp_parts.append(t_str)
            hyp_text = " ".join(hyp_parts)

            # Calcula WER e CER
            metrics = compute_wer(ground_truth_text, hyp_text, normalize=True)
            cer = compute_cer(ground_truth_text, hyp_text, normalize=True)

            run_data = {
                "model": m_name,
                "dsp": dsp_flag,
                "hotwords": hw,
                "elapsed_sec": round(elapsed, 2),
                "rtf": round(rtf, 2),
                "wer_pct": metrics["wer_pct"],
                "cer_pct": round(cer * 100.0, 2),
                "substitutions": metrics["substitutions"],
                "deletions": metrics["deletions"],
                "insertions": metrics["insertions"],
                "hits": metrics["hits"],
                "peak_app_mb": mem_loaded["app_mb"],
                "total_ram_mb": mem_loaded["total_pipeline_mb"],
                "hypothesis_text": hyp_text,
            }
            results.append(run_data)

            if metrics["wer_pct"] < min_wer:
                min_wer = metrics["wer_pct"]
                best_result = run_data

        except Exception as e:
            print(f"    [ERRO] Falha na execução da variação: {e}")

    # Exibe tabela comparativa de resultados
    print("\n" + "=" * 94)
    print(f"{'Modelo':<10} | {'DSP':<5} | {'Hotwords':<12} | {'WER (%)':<8} | {'CER (%)':<8} | {'Tempo':<8} | {'RTF':<6} | {'RAM Total':<10}")
    print("-" * 94)
    for r in results:
        hw_label = "Sim" if r["hotwords"] else "Não"
        dsp_label = "On" if r["dsp"] else "Off"
        print(
            f"{r['model']:<10} | "
            f"{dsp_label:<5} | "
            f"{hw_label:<12} | "
            f"{r['wer_pct']:>6.2f}%  | "
            f"{r['cer_pct']:>6.2f}%  | "
            f"{r['elapsed_sec']:>6.2f}s  | "
            f"{r['rtf']:>5.2f}x | "
            f"{r['total_ram_mb']:>7.1f} MB"
        )
    print("=" * 94)

    if best_result:
        print(f"\n🏆 MELHOR CONFIGURAÇÃO: Modelo='{best_result['model']}', Hotwords={'Sim' if best_result['hotwords'] else 'Não'}")
        print(f"   Taxa de Erro de Palavras (WER): {best_result['wer_pct']}% (Acertos: {best_result['hits']})")

        if show_diff:
            print("\n" + "-" * 40 + " ALINHAMENTO VISUAL DO MELHOR RESULTADO " + "-" * 40)
            diff_str = format_alignment_diff(ground_truth_text, best_result["hypothesis_text"])
            print(diff_str)
            print("-" * 94)

    if output_report_path:
        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "audio_tested": str(audio_path),
                    "ground_truth_file": str(ground_truth_path),
                    "audio_duration_sec": total_audio_sec,
                    "runs_count": len(results),
                    "best_run": best_result,
                    "all_runs": results,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\n[OK] Relatório completo exportado para: {output_report_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Científico de Precisão de Transcrição (Fase P5)")
    parser.add_argument(
        "--audio",
        type=str,
        default=str(ROOT_DIR / "tests" / "fixtures" / "reference_meeting_3min.wav"),
        help="Caminho do áudio WAV a avaliar.",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=str(ROOT_DIR / "tests" / "fixtures" / "reference_meeting_3min_ground_truth.txt"),
        help="Caminho do arquivo de transcrição anotada (Ground Truth).",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="small",
        help="Lista de modelos separados por vírgula (padrão: small).",
    )
    parser.add_argument(
        "--dsp",
        action="store_true",
        default=False,
        help="Testa variação com filtro DSP ativo.",
    )
    parser.add_argument(
        "--hotwords",
        type=str,
        default="Cássio,Bastian,Daniel,Francisco,Itaú,Transfer Family,TBM,AGF",
        help="Termos corporativos chave para guiar o Whisper.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Duração máxima em segundos da amostra sob teste (padrão: 60s para agilidade).",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        default=False,
        help="Exibe o alinhamento visual de diferenças no terminal.",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default=None,
        help="Caminho do arquivo JSON para salvar o relatório de métricas.",
    )

    args = parser.parse_args()

    audio_p = Path(args.audio)
    gt_p = Path(args.ground_truth)
    models_list = [m.strip() for m in args.models.split(",") if m.strip()]
    dsp_list = [False, True] if args.dsp else [False]
    report_p = Path(args.output_report) if args.output_report else None

    run_transcription_benchmark(
        audio_path=audio_p,
        ground_truth_path=gt_p,
        models=models_list,
        dsp_modes=dsp_list,
        hotwords_list=args.hotwords,
        max_duration_sec=args.duration,
        show_diff=args.show_diff,
        output_report_path=report_p,
    )


if __name__ == "__main__":
    main()
