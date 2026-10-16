"""
Gerador Escalável de Atas de Reunião com Arquitetura Map-Reduce & JSON Schema
Permite processar reuniões de qualquer duração mantendo num_ctx=4096 e baixo consumo de RAM.
Suporta saída estruturada nativa via Ollama JSON Schema com fallback para parsing Markdown.
"""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple, Callable

from src.minutes.ollama_client import OllamaClient
from src.minutes.parser import MeetingMinutes, ActionItem, MinutesParser
from src.minutes.prompts import (
    generate_structured_minutes_prompt,
    generate_map_chunk_prompt,
    generate_reduce_prompt,
    generate_meeting_minutes_prompt,
)
from src.config import OLLAMA_MODEL, OLLAMA_KEEP_ALIVE

logger = logging.getLogger(__name__)

# Schema JSON para a etapa Map (extração de notas por bloco de reunião)
CHUNK_NOTES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "details": {"type": "string"},
                },
                "required": ["topic", "details"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "evidence_ts": {"type": "string"},
                },
                "required": ["decision"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "owner": {"type": "string"},
                    "deadline": {"type": "string"},
                    "evidence_ts": {"type": "string"},
                },
                "required": ["action", "owner", "deadline"],
            },
        },
        "highlights": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["topics", "decisions", "action_items"],
}

# Schema JSON para a ata final completa (Single-pass ou Reduce)
MEETING_MINUTES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "participants": {
            "type": "array",
            "items": {"type": "string"},
        },
        "executive_summary": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "details": {"type": "string"},
                },
                "required": ["topic", "details"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "evidence_ts": {"type": "string"},
                },
                "required": ["decision"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "owner": {"type": "string"},
                    "deadline": {"type": "string"},
                    "evidence_ts": {"type": "string"},
                },
                "required": ["action", "owner", "deadline"],
            },
        },
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "executive_summary", "decisions", "action_items"],
}


def partition_transcript(
    transcript_text: str,
    max_chunk_chars: int = 5500,  # ~1.500-1.800 tokens
) -> List[str]:
    """
    Divide a transcrição em blocos contíguos de diálogo sem partir falas ao meio.
    Se o texto for menor ou igual a max_chunk_chars, retorna [transcript_text].
    """
    cleaned = transcript_text.strip()
    if not cleaned or len(cleaned) <= max_chunk_chars:
        return [cleaned] if cleaned else []

    lines = cleaned.split("\n")
    chunks: List[str] = []
    current_lines: List[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_chunk_chars and current_lines:
            chunks.append("\n".join(current_lines).strip())
            current_lines = [line]
            current_len = line_len
        else:
            current_lines.append(line)
            current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines).strip())

    return chunks


def minutes_to_markdown(m: MeetingMinutes) -> str:
    """Converte o objeto estruturado MeetingMinutes em um documento Markdown formatado."""
    md: List[str] = [f"# ATA DE REUNIÃO: {m.title}\n"]

    md.append("## 1. Informações Gerais")
    md.append(f"- Data: {m.date or 'Data da gravação'}")
    if m.participants:
        md.append(f"- Participantes: {', '.join(m.participants)}")
    else:
        md.append("- Participantes: Identificados por canal na transcrição")

    md.append("\n## 2. Resumo Executivo")
    md.append(m.executive_summary or "Resumo executivo não gerado.")

    md.append("\n## 3. Pautas Discutidas")
    if m.topics:
        for t in m.topics:
            md.append(f"### {t.get('topic', 'Pauta')}")
            if t.get("details"):
                md.append(t["details"])
    else:
        md.append("Pautas abordadas registradas no diálogo transcrito.")

    md.append("\n## 4. Decisões Tomadas")
    if m.decisions:
        for d in m.decisions:
            md.append(f"- {d}")
    else:
        md.append("- Nenhuma deliberação formal registrada.")

    md.append("\n## 5. Plano de Ação")
    if m.action_items:
        md.append("| Ação / O Quê | Responsável | Prazo | Evidência |")
        md.append("|---|---|---|---|")
        for a in m.action_items:
            ev = a.evidence_ts or "-"
            md.append(f"| {a.action} | {a.owner} | {a.deadline} | {ev} |")
    else:
        md.append("| Ação / O Quê | Responsável | Prazo |")
        md.append("|---|---|---|")
        md.append("| Revisar ata | Você | Imediato |")

    md.append("\n## 6. Próximos Passos e Pendências")
    if m.next_steps:
        for s in m.next_steps:
            md.append(f"- {s}")
    else:
        md.append("- Encaminhar ata final revisada para os participantes.")

    return "\n".join(md)


class MinutesGenerator:
    """
    Gerador inteligente de atas de reunião executivas.
    Alterna de forma adaptativa entre chamada direta (para reuniões curtas)
    e Map-Reduce particionado (para reuniões longas de qualquer duração),
    respeitando estritamente o teto de 4GB de RAM via JSON Schema do Ollama.
    """

    def __init__(self, ollama_client: Optional[OllamaClient] = None):
        self.client = ollama_client or OllamaClient()

    def generate(
        self,
        transcript_text: str,
        meeting_title: Optional[str] = None,
        meeting_date: Optional[str] = None,
        meeting_duration: Optional[str] = None,
        user_speaker_name: str = "Você",
        progress_callback: Optional[Callable[[str, int], None]] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[MeetingMinutes, str]:
        """
        Gera a ata estruturada e retorna a tupla (MeetingMinutes, raw_markdown).
        """
        chunks = partition_transcript(transcript_text, max_chunk_chars=6000)

        # Rota 1: Reuniões curtas ou médias (1 único bloco)
        if len(chunks) <= 1:
            return self._generate_single_pass(
                transcript_text=transcript_text,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                meeting_duration=meeting_duration,
                user_speaker_name=user_speaker_name,
                progress_callback=progress_callback,
                token_callback=token_callback,
            )

        # Rota 2: Reuniões longas (Map-Reduce)
        return self._generate_map_reduce(
            chunks=chunks,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            meeting_duration=meeting_duration,
            user_speaker_name=user_speaker_name,
            progress_callback=progress_callback,
            token_callback=token_callback,
        )

    def _generate_single_pass(
        self,
        transcript_text: str,
        meeting_title: Optional[str],
        meeting_date: Optional[str],
        meeting_duration: Optional[str],
        user_speaker_name: str,
        progress_callback: Optional[Callable[[str, int], None]],
        token_callback: Optional[Callable[[str], None]],
    ) -> Tuple[MeetingMinutes, str]:
        """Geração em chamada direta estruturada via JSON Schema."""
        if progress_callback:
            progress_callback("Gerando ata executiva estruturada via IA...", 75)

        sys_p, usr_p = generate_structured_minutes_prompt(
            transcript_text=transcript_text,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            meeting_duration=meeting_duration,
            user_speaker_name=user_speaker_name,
        )

        try:
            raw_response = self.client.generate(
                prompt=usr_p,
                system=sys_p,
                model=OLLAMA_MODEL,
                keep_alive=OLLAMA_KEEP_ALIVE,
                response_format=MEETING_MINUTES_SCHEMA,
                stream_callback=token_callback,
            )

            data = json.loads(raw_response)
            minutes = MeetingMinutes.from_dict(data)
            if meeting_date and not minutes.date:
                minutes.date = meeting_date
            if meeting_title and minutes.title == "Ata de Reunião":
                minutes.title = meeting_title

            markdown_output = minutes_to_markdown(minutes)
            minutes.raw_markdown = markdown_output
            logger.info("Ata estruturada gerada com sucesso via JSON Schema (Single-pass).")
            return minutes, markdown_output

        except Exception as err:
            logger.warning("Falha na geração via JSON Schema (%s). Tentando fallback Markdown...", err)
            return self._fallback_markdown_generate(
                transcript_text=transcript_text,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                meeting_duration=meeting_duration,
                progress_callback=progress_callback,
                token_callback=token_callback,
            )

    def _generate_map_reduce(
        self,
        chunks: List[str],
        meeting_title: Optional[str],
        meeting_date: Optional[str],
        meeting_duration: Optional[str],
        user_speaker_name: str,
        progress_callback: Optional[Callable[[str, int], None]],
        token_callback: Optional[Callable[[str], None]],
    ) -> Tuple[MeetingMinutes, str]:
        """Geração escalável em duas etapas (Map sobre blocos -> Reduce consolidado)."""
        total = len(chunks)
        logger.info("Iniciando Map-Reduce para reunião longa (%d blocos temporais)...", total)

        # ETAPA MAP: extrai notas estruturadas por bloco
        chunk_notes_list: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            pct = 70 + int((idx / total) * 15)  # de 70% a 85%
            if progress_callback:
                progress_callback(f"Analisando bloco {idx}/{total} da reunião com IA...", pct)

            sys_p, usr_p = generate_map_chunk_prompt(
                chunk_text=chunk,
                chunk_index=idx,
                total_chunks=total,
                user_speaker_name=user_speaker_name,
            )

            try:
                raw_chunk = self.client.generate(
                    prompt=usr_p,
                    system=sys_p,
                    model=OLLAMA_MODEL,
                    keep_alive=OLLAMA_KEEP_ALIVE,
                    response_format=CHUNK_NOTES_SCHEMA,
                )
                chunk_data = json.loads(raw_chunk)
                chunk_notes_list.append(chunk_data)
                logger.info(
                    "Bloco %d/%d processado: %d tópicos, %d decisões, %d ações.",
                    idx,
                    total,
                    len(chunk_data.get("topics", [])),
                    len(chunk_data.get("decisions", [])),
                    len(chunk_data.get("action_items", [])),
                )
            except Exception as e:
                logger.warning("Erro ao processar bloco %d no Map (%s). Prosseguindo com os demais.", idx, e)

        # ETAPA REDUCE: consolida todas as notas na ata definitiva
        if progress_callback:
            progress_callback("Consolidando ata executiva e matriz de ações final...", 88)

        red_sys, red_usr = generate_reduce_prompt(
            chunk_notes=chunk_notes_list,
            meeting_date=meeting_date,
            meeting_duration=meeting_duration,
            user_speaker_name=user_speaker_name,
        )

        try:
            raw_final = self.client.generate(
                prompt=red_usr,
                system=red_sys,
                model=OLLAMA_MODEL,
                keep_alive=OLLAMA_KEEP_ALIVE,
                response_format=MEETING_MINUTES_SCHEMA,
                stream_callback=token_callback,
            )

            final_data = json.loads(raw_final)
            minutes = MeetingMinutes.from_dict(final_data)
            if meeting_date and not minutes.date:
                minutes.date = meeting_date
            if meeting_title and minutes.title == "Ata de Reunião":
                minutes.title = meeting_title

            markdown_output = minutes_to_markdown(minutes)
            minutes.raw_markdown = markdown_output
            logger.info("Map-Reduce finalizado com sucesso: '%s' gerada.", minutes.title)
            return minutes, markdown_output

        except Exception as e:
            logger.warning("Falha na consolidação Reduce (%s). Recorrendo a fallback consolidado.", e)
            return self._fallback_markdown_generate(
                transcript_text=chunks[0],  # Fallback com primeiro bloco
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                meeting_duration=meeting_duration,
                progress_callback=progress_callback,
                token_callback=token_callback,
            )

    def _fallback_markdown_generate(
        self,
        transcript_text: str,
        meeting_title: Optional[str],
        meeting_date: Optional[str],
        meeting_duration: Optional[str],
        progress_callback: Optional[Callable[[str, int], None]],
        token_callback: Optional[Callable[[str], None]],
    ) -> Tuple[MeetingMinutes, str]:
        """Geração clássica em texto Markdown com parsing resiliente via regex."""
        if progress_callback:
            progress_callback("Gerando ata executiva em modo de compatibilidade...", 85)

        sys_p, usr_p = generate_meeting_minutes_prompt(
            transcript_text=transcript_text,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            meeting_duration=meeting_duration,
        )

        raw_md = self.client.generate(
            prompt=usr_p,
            system=sys_p,
            model=OLLAMA_MODEL,
            keep_alive=OLLAMA_KEEP_ALIVE,
            stream_callback=token_callback,
        )
        parsed = MinutesParser.parse(raw_md)
        return parsed, raw_md
