"""
Testes Unitários do Módulo de Chunking do RAG (pytest marker: unit)
Executa 100% offline sem Ollama, sem rede e sem dependências externas pesadas.
"""

import json
from pathlib import Path
import pytest

from src.rag.chunker import (
    SessionChunker,
    DocumentChunk,
    parse_timestamp_str_to_seconds,
    compute_session_content_hash,
)
from src.pipeline.session import MeetingSession


@pytest.mark.unit
def test_parse_timestamp_str_to_seconds():
    assert parse_timestamp_str_to_seconds("00:30") == 30.0
    assert parse_timestamp_str_to_seconds("01:15") == 75.0
    assert parse_timestamp_str_to_seconds("01:02:03") == 3723.0
    assert parse_timestamp_str_to_seconds("[02:45]") == 165.0
    assert parse_timestamp_str_to_seconds("inválido") == 0.0
    assert parse_timestamp_str_to_seconds(None) == 0.0


@pytest.mark.unit
def test_chunker_transcript_windowing_and_overlap():
    chunker = SessionChunker(min_words=150, max_words=250, overlap_segments=1)

    # Cria 8 segmentos com aproximadamente 40 palavras cada (~320 palavras no total)
    segments = []
    base_text = "palavra teste " * 20  # 40 palavras por segmento
    for i in range(8):
        speaker = "Thiago" if i % 2 == 0 else "Participante B"
        segments.append({
            "speaker": speaker,
            "start": float(i * 15),
            "end": float((i + 1) * 15),
            "text": f"Segmento {i}: {base_text}",
        })

    chunks = chunker.chunk_transcript_segments("2026-10-30_100000", segments)

    assert len(chunks) >= 2, "Deveria ter gerado pelo menos 2 chunks para ~320 palavras."

    # Validação do primeiro chunk
    c1 = chunks[0]
    assert c1.session_id == "2026-10-30_100000"
    assert c1.source == "transcript"
    assert c1.start_sec == 0.0
    assert "Thiago" in c1.speakers
    assert "Participante B" in c1.speakers

    # Validação da sobreposição: o último segmento do chunk 0 deve estar no início do chunk 1
    c2 = chunks[1]
    # O chunk 1 deve ter start_sec anterior ao end_sec do chunk 0 (sobreposição)
    assert c2.start_sec < c1.end_sec
    assert c2.start_sec >= 0.0

    # Cada chunk deve conter o texto formatado com marcação de tempo e falante
    assert "[00:00]" in c1.text
    assert "[Thiago]" in c1.text


@pytest.mark.unit
def test_chunker_minutes_items(tmp_path: Path):
    chunker = SessionChunker()
    session_id = "2026-10-30_120000"
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    minutes_data = {
        "title": "Alinhamento Estratégico",
        "summary": "Discussão sobre a entrega do projeto piloto e prazos de homologação.",
        "decisions": [
            {
                "decision": "Aprovar a migração para infraestrutura local.",
                "evidence_ts": "00:15:30",
            },
            {
                "decision": "Definir orçamento fixo de computação.",
                "evidence_ts": "00:35:10",
            },
        ],
        "action_items": [
            {
                "action": "Configurar ambiente do modelo Ollama",
                "owner": "Thiago",
                "deadline": "15/11/2026",
                "evidence": "00:20:00",
            },
            {
                "action": "Executar testes de estresse em CPU",
                "owner": "Carlos",
                "deadline": "20/11/2026",
                "evidence": "00:42:00",
            },
        ],
    }

    minutes_file = session_dir / "minutes.json"
    with open(minutes_file, "w", encoding="utf-8") as f:
        json.dump(minutes_data, f, ensure_ascii=False)

    chunks = chunker.chunk_minutes_file(session_id, minutes_file)

    # 1 de resumo + 2 de decisões + 2 de ações = 5 chunks
    assert len(chunks) == 5

    types = [c.metadata.get("chunk_type") for c in chunks]
    assert types == ["summary", "decision", "decision", "action_item", "action_item"]

    summary_chunk = chunks[0]
    assert "Alinhamento Estratégico" in summary_chunk.text
    assert summary_chunk.source == "minutes"

    dec_chunk1 = chunks[1]
    assert "migração para infraestrutura local" in dec_chunk1.text
    assert dec_chunk1.start_sec == 930.0  # 15m 30s = 930s

    action_chunk1 = chunks[3]
    assert "Thiago" in action_chunk1.text
    assert "15/11/2026" in action_chunk1.text
    assert action_chunk1.speakers == ["Thiago"]
    assert action_chunk1.start_sec == 1200.0  # 20m = 1200s


@pytest.mark.unit
def test_compute_session_content_hash(tmp_path: Path):
    session_id = "2026-10-30_150000"
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session = MeetingSession(session_id, session_dir)

    # Sem arquivos de texto
    assert compute_session_content_hash(session) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # sha256 vazio

    # Com transcript.json
    session.transcript_path.write_text('{"text": "olá mundo"}', encoding="utf-8")
    hash1 = compute_session_content_hash(session)
    assert hash1 != ""

    # Mesmo conteúdo -> mesmo hash
    hash2 = compute_session_content_hash(session)
    assert hash1 == hash2

    # Conteúdo alterado -> hash diferente
    session.transcript_path.write_text('{"text": "olá mundo modificado"}', encoding="utf-8")
    hash3 = compute_session_content_hash(session)
    assert hash3 != hash1
