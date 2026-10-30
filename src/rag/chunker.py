"""
Módulo de Segmentação de Documentos (Chunker) para RAG
Transforma artefatos de reuniões (transcript.json e minutes.json) em chunks semânticos
otimizados para recuperação densa com preservação de metadados temporais e de interlocutor.
"""

from dataclasses import dataclass, field, asdict
import hashlib
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.pipeline.session import MeetingSession
from src.utils.telemetry import format_duration


@dataclass
class DocumentChunk:
    """Representa um pedaço textual indexável com metadados para citação precisa."""

    chunk_id: str
    session_id: str
    source: str  # "transcript" | "minutes"
    start_sec: float
    end_sec: float
    speakers: List[str]
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def formatted_citation_header(self) -> str:
        """Retorna cabeçalho formatado para citação: [Sessão · 00:01:23 · Falante]."""
        time_str = format_duration(self.start_sec)
        speakers_str = ", ".join(self.speakers) if self.speakers else "Participantes"
        return f"{self.session_id} · {time_str} · {speakers_str}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_timestamp_str_to_seconds(ts_str: Optional[str]) -> float:
    """Converte strings no formato 'MM:SS' ou 'HH:MM:SS' para float em segundos."""
    if not ts_str:
        return 0.0
    ts_clean = str(ts_str).strip().replace("[", "").replace("]", "").replace("~", "")
    parts = ts_clean.split(":")
    try:
        if len(parts) == 3:
            return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))
        elif len(parts) == 2:
            return float(int(parts[0]) * 60 + float(parts[1]))
        elif len(parts) == 1 and parts[0].isdigit():
            return float(parts[0])
    except Exception:
        pass
    return 0.0


class SessionChunker:
    """
    Segmentador responsável por decompor transcrições e atas executivas em chunks
    semanticamente ricos com janela de 150 a 250 palavras e sobreposição.
    """

    def __init__(
        self,
        min_words: int = 150,
        max_words: int = 250,
        overlap_segments: int = 1,
    ):
        self.min_words = min_words
        self.max_words = max_words
        self.overlap_segments = overlap_segments

    def chunk_session(self, session: MeetingSession) -> List[DocumentChunk]:
        """
        Gera todos os chunks pertinentes a uma sessão (transcrição + ata estruturada).
        """
        chunks: List[DocumentChunk] = []

        # 1. Chunks da Transcrição
        if session.has_transcript():
            chunks.extend(self.chunk_transcript_file(session.session_id, session.transcript_path))

        # 2. Chunks da Ata Executiva
        if session.has_minutes():
            chunks.extend(self.chunk_minutes_file(session.session_id, session.minutes_path))

        return chunks

    def chunk_transcript_file(self, session_id: str, transcript_path: Path) -> List[DocumentChunk]:
        """Extrai chunks da transcrição estruturada."""
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        segments: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            segments = data.get("segments", [])
        elif isinstance(data, list):
            segments = data

        return self.chunk_transcript_segments(session_id, segments)

    def chunk_transcript_segments(
        self,
        session_id: str,
        segments: List[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        """
        Agrupa segmentos em janelas de ~150 a 250 palavras com sobreposição de 1 segmento.
        """
        if not segments:
            return []

        chunks: List[DocumentChunk] = []
        idx = 0
        n_segments = len(segments)
        chunk_counter = 0

        while idx < n_segments:
            current_window: List[Dict[str, Any]] = []
            word_count = 0
            j = idx

            while j < n_segments:
                seg = segments[j]
                seg_text = seg.get("text", "").strip()
                seg_words = len(seg_text.split())

                current_window.append(seg)
                word_count += seg_words
                j += 1

                # Se atingiu o limite mínimo e ultrapassou ou está no intervalo ideal de palavras
                if word_count >= self.min_words:
                    break

            if not current_window:
                break

            # Monta o texto representativo do chunk com marcação temporal e interlocutor
            lines = []
            speakers_set = set()
            start_sec = float(current_window[0].get("start", 0.0))
            end_sec = float(current_window[-1].get("end", start_sec))

            for s in current_window:
                speaker = s.get("speaker") or "Participante"
                speakers_set.add(speaker)
                s_start_str = format_duration(float(s.get("start", 0.0)))
                s_text = s.get("text", "").strip()
                lines.append(f"[{s_start_str}] [{speaker}]: {s_text}")

            full_text = "\n".join(lines)
            chunk_counter += 1
            chunk_id = f"{session_id}_tra_{chunk_counter:04d}"

            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    session_id=session_id,
                    source="transcript",
                    start_sec=start_sec,
                    end_sec=end_sec,
                    speakers=sorted(list(speakers_set)),
                    text=full_text,
                    metadata={
                        "chunk_type": "transcript_window",
                        "num_segments": len(current_window),
                        "word_count": word_count,
                    },
                )
            )

            # Avança o índice aplicando a sobreposição de segmentos configurada
            if j >= n_segments:
                break

            overlap = min(self.overlap_segments, len(current_window) - 1)
            next_idx = j - overlap
            if next_idx <= idx:
                next_idx = idx + 1
            idx = next_idx

        return chunks

    def chunk_minutes_file(self, session_id: str, minutes_path: Path) -> List[DocumentChunk]:
        """
        Extrai chunks de alta relevância da ata estruturada (resumo, decisões e ações).
        """
        try:
            with open(minutes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        chunks: List[DocumentChunk] = []
        chunk_idx = 0

        title = data.get("title", "Ata de Reunião")
        summary = data.get("summary", "")

        # 1. Chunk de Resumo Executivo / Visão Geral
        if summary:
            chunk_idx += 1
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{session_id}_min_sum_{chunk_idx:02d}",
                    session_id=session_id,
                    source="minutes",
                    start_sec=0.0,
                    end_sec=0.0,
                    speakers=["Ata Executiva"],
                    text=f"Resumo da Reunião ({title}):\n{summary}",
                    metadata={
                        "chunk_type": "summary",
                        "title": title,
                    },
                )
            )

        # 2. Chunks individuais por Decisão Tomada
        decisions = data.get("decisions", [])
        for i, dec in enumerate(decisions, start=1):
            if isinstance(dec, dict):
                d_text = dec.get("decision") or dec.get("text") or str(dec)
                evidence = dec.get("evidence_ts") or dec.get("evidence") or ""
            else:
                d_text = str(dec)
                evidence = ""

            if not d_text.strip():
                continue

            ts_sec = parse_timestamp_str_to_seconds(evidence)
            chunk_idx += 1
            evidence_line = f" [Evidência/Timestamp: {evidence}]" if evidence else ""
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{session_id}_min_dec_{chunk_idx:02d}",
                    session_id=session_id,
                    source="minutes",
                    start_sec=ts_sec,
                    end_sec=ts_sec,
                    speakers=["Ata Executiva"],
                    text=f"Decisão Registrada na Reunião:\n{d_text}{evidence_line}",
                    metadata={
                        "chunk_type": "decision",
                        "index": i,
                        "evidence_ts": evidence,
                    },
                )
            )

        # 3. Chunks individuais por Item de Ação (Matriz de Ações)
        action_items = data.get("action_items", [])
        for i, item in enumerate(action_items, start=1):
            if not isinstance(item, dict):
                continue

            action = item.get("action") or item.get("description") or ""
            owner = item.get("owner") or "Não definido"
            deadline = item.get("deadline") or "A combinar"
            evidence = item.get("evidence") or ""

            if not action.strip():
                continue

            ts_sec = parse_timestamp_str_to_seconds(evidence)
            chunk_idx += 1
            text_lines = [
                "Ação Deliberada na Reunião:",
                f"- Tarefa / O quê: {action}",
                f"- Responsável: {owner}",
                f"- Prazo: {deadline}",
            ]
            if evidence:
                text_lines.append(f"- Evidência temporal: {evidence}")

            chunks.append(
                DocumentChunk(
                    chunk_id=f"{session_id}_min_act_{chunk_idx:02d}",
                    session_id=session_id,
                    source="minutes",
                    start_sec=ts_sec,
                    end_sec=ts_sec,
                    speakers=[owner] if owner != "Não definido" else ["Ata Executiva"],
                    text="\n".join(text_lines),
                    metadata={
                        "chunk_type": "action_item",
                        "index": i,
                        "owner": owner,
                        "deadline": deadline,
                        "evidence_ts": evidence,
                    },
                )
            )

        return chunks


def compute_session_content_hash(session: MeetingSession) -> str:
    """
    Calcula hash SHA256 dos artefatos textuais da sessão (transcript.json e minutes.json)
    para permitir indexação incremental rigorosa em O(1).
    """
    hasher = hashlib.sha256()

    for p in (session.transcript_path, session.minutes_path):
        if p.exists() and p.is_file():
            try:
                hasher.update(p.read_bytes())
            except Exception:
                pass

    return hasher.hexdigest()
