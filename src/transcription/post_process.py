"""
Módulo de Pós-Processamento e Separação de Locutores (Diarização Dual-Channel)
Separa o Canal 0 (Você) e Canal 1 (Participantes do Teams),
intercala os diálogos cronologicamente por timestamps e formata a transcrição.
"""

import json
import wave
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Union, Optional
import numpy as np

logger = logging.getLogger(__name__)


def format_timestamp(seconds: float) -> str:
    """Converte segundos em formato legível HH:MM:SS ou MM:SS."""
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def split_dual_channel_audio(wav_path: Union[str, Path]) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Lê o arquivo WAV gravado e separa os canais estéreo:
    - Canal 0: Microfone do usuário (Você)
    - Canal 1: Áudio do Teams (Participantes)
    Retorna (ch_mic, ch_teams, sample_rate) em arrays float32 normalizados.
    """
    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de áudio não encontrado: {path}")

    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_frames = wf.readframes(n_frames)

    audio_int16 = np.frombuffer(raw_frames, dtype=np.int16)

    if n_channels >= 2:
        # Reorganiza em matriz [frames, canais]
        usable_frames = (len(audio_int16) // n_channels) * n_channels
        audio_2d = audio_int16[:usable_frames].reshape(-1, n_channels)
        ch_mic = (audio_2d[:, 0].astype(np.float32)) / 32768.0
        ch_teams = (audio_2d[:, 1].astype(np.float32)) / 32768.0
    else:
        # Caso tenha sido gravado mono por alguma contingência
        mono = audio_int16.astype(np.float32) / 32768.0
        ch_mic = mono
        ch_teams = np.zeros_like(mono)

    logger.info(
        "Áudio WAV carregado e separado em 2 canais: %.2fs (%d amostras a %dHz)",
        len(ch_mic) / sample_rate if sample_rate > 0 else 0,
        len(ch_mic),
        sample_rate,
    )
    return ch_mic, ch_teams, sample_rate


def merge_channel_transcripts(
    user_segments: List[Dict[str, Any]],
    teams_segments: List[Dict[str, Any]],
    user_label: str = "Você",
    teams_label: str = "Participantes da Reunião",
) -> List[Dict[str, Any]]:
    """
    Mescla as duas listas de transcrições rotulando os locutores e ordenando
    cronologicamente pelo timestamp de início (start).
    Agrupa falas contíguas do mesmo locutor se o intervalo for curto (< 1.5s).
    """
    labeled_list: List[Dict[str, Any]] = []

    for seg in user_segments:
        labeled_list.append(
            {
                "speaker": user_label,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            }
        )

    for seg in teams_segments:
        labeled_list.append(
            {
                "speaker": teams_label,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            }
        )

    # Ordena cronologicamente pelo início da fala
    labeled_list.sort(key=lambda x: x["start"])

    # Agrupa falas consecutivas do mesmo interlocutor se o intervalo for curto
    merged: List[Dict[str, Any]] = []
    for item in labeled_list:
        if not merged:
            merged.append(item)
            continue

        prev = merged[-1]
        # Mesmo locutor e intervalo entre falas menor que 1.5 segundos: junta
        if prev["speaker"] == item["speaker"] and (item["start"] - prev["end"]) <= 1.5:
            prev["end"] = max(prev["end"], item["end"])
            prev["text"] = f"{prev['text']} {item['text']}"
        else:
            merged.append(item)

    logger.info("Mesclagem concluída: %d blocos de diálogo estruturados.", len(merged))
    return merged


def format_transcript_dialogue(merged_segments: List[Dict[str, Any]]) -> str:
    """
    Formata a lista de segmentos em texto corrido com timestamps e nomes de locutores:
    Exemplo:
    [00:00:05 - 00:00:18] [Você]: Olá a todos, vamos iniciar a revisão do projeto.
    [00:00:20 - 00:00:35] [Participantes da Reunião]: Bom dia, tudo pronto por aqui.
    """
    lines = []
    for seg in merged_segments:
        start_str = format_timestamp(seg["start"])
        end_str = format_timestamp(seg["end"])
        speaker = seg["speaker"]
        text = seg["text"]
        lines.append(f"[{start_str} - {end_str}] [{speaker}]: {text}")
    return "\n".join(lines)


def process_dual_recording(
    wav_path: Union[str, Path],
    whisper_engine,
    output_json_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Pipeline completo de pós-processamento de um arquivo WAV dual-channel:
    1. Separa Canal 0 (Você) e Canal 1 (Teams).
    2. Transcreve Canal 0 se tiver atividade sonora.
    3. Transcreve Canal 1 se tiver atividade sonora.
    4. Mescla cronologicamente e gera diálogo formatado.
    5. Salva estrutura em JSON se output_json_path for especificado.
    """
    ch_mic, ch_teams, sr = split_dual_channel_audio(wav_path)

    # Checa energia/atividade de áudio para evitar transcrever canal 100% mudo
    mic_rms = float(np.sqrt(np.mean(ch_mic ** 2)))
    teams_rms = float(np.sqrt(np.mean(ch_teams ** 2)))

    logger.info("Energia de áudio (RMS): Mic=%.4f, Teams=%.4f", mic_rms, teams_rms)

    user_segments = []
    if mic_rms > 0.001:
        logger.info("Transcrevendo Canal 0 (Microfone / Você)...")
        user_segments = whisper_engine.transcribe(ch_mic)
    else:
        logger.info("Canal 0 (Microfone) silencioso, pulando transcrição.")

    teams_segments = []
    if teams_rms > 0.001:
        logger.info("Transcrevendo Canal 1 (Áudio do Teams / Participantes)...")
        teams_segments = whisper_engine.transcribe(ch_teams)
    else:
        logger.info("Canal 1 (Teams) silencioso, pulando transcrição.")

    merged_dialogue = merge_channel_transcripts(user_segments, teams_segments)
    formatted_text = format_transcript_dialogue(merged_dialogue)

    duration_sec = len(ch_mic) / sr if sr > 0 else 0.0

    result_data = {
        "audio_file": str(wav_path),
        "duration_seconds": round(duration_sec, 2),
        "duration_formatted": format_timestamp(duration_sec),
        "total_segments": len(merged_dialogue),
        "dialogue_segments": merged_dialogue,
        "full_text": formatted_text,
    }

    if output_json_path:
        out_path = Path(output_json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        logger.info("Transcrição estruturada salva em: %s", out_path)

    return result_data
