"""
Módulo de Pós-Processamento e Separação de Locutores (Diarização Dual-Channel)
Separa o Canal 0 (Você) e Canal 1 (Participantes do Teams),
intercala os diálogos cronologicamente por timestamps e formata a transcrição.
"""

import json
import re
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


# Stopwords multilíngues (Português, Espanhol, Inglês) com 3+ caracteres para o filtro acústico de eco.
# Palavras com 1 ou 2 letras já são naturalmente ignoradas pelo regex \b\w{3,}\b.
ACOUSTIC_STOPWORDS: frozenset[str] = frozenset({
    # Português
    "que", "com", "para", "pra", "não", "nao", "uma", "umas", "este", "esta", "estas", "estes",
    "está", "estao", "estão", "estava", "estavam", "isso", "esse", "essa", "esses", "essas",
    "aquele", "aquela", "aqueles", "aquelas", "aquilo", "como", "por", "mais", "dos", "das",
    "ele", "ela", "eles", "elas", "você", "voce", "vocês", "voces", "mas", "nos", "tem", "ter",
    "temos", "tenho", "tinha", "tinham", "foi", "ser", "são", "sao", "era", "eram", "estar",
    "aqui", "pelo", "pela", "pelos", "pelas", "então", "entao", "depois", "ainda", "assim",
    "também", "tambem", "onde", "quando", "muito", "muita", "muitos", "muitas", "sobre",
    "entre", "mesmo", "mesma", "mesmos", "mesmas", "sempre", "nunca", "quase", "todo", "toda",
    "todos", "todas", "outro", "outra", "outros", "outras", "algo", "nada", "fazer", "feito",
    "pode", "podem", "poder",

    # Espanhol
    "los", "las", "les", "del", "uno", "una", "unos", "unas", "ella", "ellos", "ellas",
    "nosotros", "nosotras", "usted", "ustedes", "esto", "estos", "estas", "ese", "esa", "eso",
    "esos", "esas", "aquel", "aquella", "aquellos", "aquellas", "pero", "entonces", "porque",
    "cuando", "donde", "aunque", "sino", "pues", "mientras", "sin", "desde", "hasta", "hacia",
    "más", "mas", "muy", "bien", "bueno", "buena", "buenos", "buenas", "aquí", "allí", "alli",
    "ahora", "también", "tambien", "cada", "alguien", "nadie", "tanto", "tanta", "tantos", "tantas",
    "casi", "sido", "están", "estan", "tiene", "tienen", "tenemos", "había", "habia", "hay",
    "hubo", "hecho", "hace", "vamos",

    # Inglês corporativo comum
    "the", "and", "for", "that", "with", "this", "from", "have", "has", "had", "are", "you",
    "not", "but", "they", "all", "can", "will", "one", "about", "there", "their", "what",
    "when", "which", "been", "some", "more", "just", "like", "then", "into", "them", "your",
})


def clean_text_tokens(text: str) -> set:
    """Extrai palavras limpas em minúsculas para comparação de conjunto (filtrando stopwords)."""
    tokens = re.findall(r"\b\w{3,}\b", text.lower())
    return {w for w in tokens if w not in ACOUSTIC_STOPWORDS}


def filter_acoustic_echo_segments(
    user_segments: List[Dict[str, Any]],
    teams_segments: List[Dict[str, Any]],
    time_window: float = 6.0,
) -> List[Dict[str, Any]]:
    """
    Remove do canal do microfone (Você) trechos que são vazamento acústico (eco)
    do som que saiu pelos alto-falantes durante a fala dos participantes do Teams.
    Preserva 100% das falas genuínas do usuário.
    """
    import difflib

    clean_user_segments = []
    echo_suppressed = 0

    for u_seg in user_segments:
        u_tokens = clean_text_tokens(u_seg.get("text", ""))
        if not u_tokens:
            clean_user_segments.append(u_seg)
            continue

        u_start = u_seg["start"]
        u_end = u_seg["end"]
        is_echo = False

        for t_seg in teams_segments:
            t_start = t_seg["start"]
            t_end = t_seg["end"]

            # Janela de proximidade temporal com tolerância a latência acústica e VAD
            if (t_start - 1.5) <= u_start <= (t_end + time_window) or (u_start <= t_start and u_end >= t_start):
                t_tokens = clean_text_tokens(t_seg.get("text", ""))
                if not t_tokens:
                    continue

                inter = u_tokens.intersection(t_tokens)
                smaller = min(len(u_tokens), len(t_tokens))
                if smaller == 0:
                    continue

                overlap = len(inter) / smaller
                seq_ratio = difflib.SequenceMatcher(None, u_seg["text"].lower(), t_seg["text"].lower()).ratio()

                if (len(inter) >= 3 and overlap >= 0.35) or seq_ratio >= 0.50 or (len(inter) >= 2 and overlap >= 0.60):
                    is_echo = True
                    break

        if is_echo:
            echo_suppressed += 1
        else:
            clean_user_segments.append(u_seg)

    if echo_suppressed > 0:
        logger.info(
            "Filtro Acústico: %d segmentos de eco/vazamento dos alto-falantes suprimidos do microfone.",
            echo_suppressed,
        )

    return clean_user_segments


def merge_channel_transcripts(
    user_segments: List[Dict[str, Any]],
    teams_segments: List[Dict[str, Any]],
    user_label: str = "Você",
    teams_label: str = "Participantes da Reunião",
    filter_echo: bool = True,
) -> List[Dict[str, Any]]:
    """
    Mescla as duas listas de transcrições rotulando os locutores e ordenando
    cronologicamente pelo timestamp de início (start).
    Aplica filtro acústico para suprimir vazamento de alto-falantes no microfone.
    Agrupa falas contíguas do mesmo locutor se o intervalo for curto (< 1.5s).
    """
    if filter_echo and teams_segments and user_segments:
        user_segments = filter_acoustic_echo_segments(user_segments, teams_segments)

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
