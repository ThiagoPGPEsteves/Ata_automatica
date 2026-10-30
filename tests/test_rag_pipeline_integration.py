"""
Testes Unitários de Integração do RAG com o Pipeline Principal (pytest marker: unit)
Garante que falhas no serviço RAG nunca quebrem a geração ou exportação da ata executiva.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.pipeline.session import MeetingSession
from src.pipeline.meeting_pipeline import MeetingPipeline, PipelineStage
from src.config import UserSettings


@pytest.mark.unit
def test_pipeline_export_succeeds_even_when_rag_indexing_fails(tmp_path: Path):
    session_id = "2026-10-30_160000"
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    session = MeetingSession(session_id, session_dir)

    # Cria transcrição e ata estruturada para simular estágio final
    transcript_data = {
        "text": "[00:00:10] [Você]: Início da reunião.\n[00:00:20] [Participantes]: Alinhamento concluído.",
        "segments": [
            {"speaker": "Você", "start": 10.0, "end": 15.0, "text": "Início da reunião."},
            {"speaker": "Participantes", "start": 20.0, "end": 25.0, "text": "Alinhamento concluído."},
        ],
    }
    session.transcript_path.write_text(json.dumps(transcript_data, ensure_ascii=False), encoding="utf-8")

    minutes_data = {
        "title": "Ata de Teste de Resiliência",
        "meeting_date": "30/10/2026 16:00",
        "summary": "Resumo de teste de integração.",
        "topics": [],
        "decisions": [{"decision": "Decisão de teste", "evidence_ts": "00:00:10"}],
        "action_items": [],
        "next_steps": [],
    }
    session.minutes_path.write_text(json.dumps(minutes_data, ensure_ascii=False), encoding="utf-8")

    settings = UserSettings(rag_auto_index=True)
    pipeline = MeetingPipeline(session=session, settings=settings)

    # Simula falha catastrófica no RagService (ex: Ollama offline, modelo ausente ou timeout)
    with patch("src.rag.service.RagService.index_session", side_effect=RuntimeError("Ollama Embedder indisponível")):
        result = pipeline.run(from_stage=PipelineStage.EXPORT)

    assert result["status"] == "completed"
    assert result["docx_path"] is not None
    assert Path(result["docx_path"]).exists()
    assert session.has_docx()
