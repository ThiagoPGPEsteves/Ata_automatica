"""
Testes automatizados para o MeetingPipeline, CancelToken, estágios e fallback.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from src.pipeline.session import SessionStore, MeetingSession
from src.pipeline.meeting_pipeline import (
    MeetingPipeline,
    CancelToken,
    PipelineStage,
    create_fallback_minutes,
)
from src.minutes.parser import MeetingMinutes


def test_cancel_token():
    token = CancelToken()
    assert not token.is_cancelled
    token.cancel()
    assert token.is_cancelled


def test_create_fallback_minutes():
    doc = create_fallback_minutes(
        meeting_date_str="16/10/2026 14:30",
        meeting_duration_str="00:25:00",
        user_speaker_name="Thiago",
        reason="Ollama em manutenção.",
    )
    assert isinstance(doc, MeetingMinutes)
    assert doc.title != ""
    assert "Thiago" in " ".join(doc.participants) or "Thiago" in doc.executive_summary
    assert len(doc.action_items) >= 1
    assert len(doc.decisions) >= 1
    assert "Ollama em manutenção" in doc.executive_summary


def test_pipeline_generate_and_export_with_offline_ollama(tmp_path):
    store = SessionStore(root_dir=tmp_path)
    session = store.create_session("sess_offline_test")

    # Fornece transcript.json prévio para pular transcrição
    transcript_text = (
        "[00:00 - 00:05] [Você]: Bom dia a todos, iniciamos a reunião sobre a CCP.\n"
        "[00:05 - 00:15] [Participantes da Reunião]: Bom dia, confirmamos a ponderação de 100%."
    )
    transcript_payload = {
        "text": transcript_text,
        "segments": [
            {"speaker": "Você", "start": 0.0, "end": 5.0, "text": "Bom dia a todos, iniciamos a reunião sobre a CCP."},
            {"speaker": "Participantes da Reunião", "start": 5.0, "end": 15.0, "text": "Bom dia, confirmamos a ponderação de 100%."},
        ]
    }
    with open(session.transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_payload, f)

    progress_reports = []
    def on_prog(msg, pct):
        progress_reports.append((msg, pct))

    # Mock OllamaClient.is_available = False
    with patch("src.pipeline.meeting_pipeline.OllamaClient.is_available", return_value=False):
        pipeline = MeetingPipeline(
            session=session,
            on_progress=on_prog,
        )
        result = pipeline.run(from_stage=PipelineStage.GENERATE)

    assert result["status"] == "completed"
    assert session.has_minutes()
    assert session.has_docx()
    assert session.log_path.exists()

    manifest = session.load_manifest()
    assert manifest["status"] == "completed"
    assert manifest["has_minutes"] is True
    assert manifest["has_docx"] is True

    # Verifica se os callbacks de progresso foram acionados
    assert len(progress_reports) > 0
    assert any(pct == 100 for _, pct in progress_reports)


def test_pipeline_cancellation(tmp_path):
    import wave
    import struct

    store = SessionStore(root_dir=tmp_path)
    session = store.create_session("sess_cancelled_test")

    # Gera arquivo WAV válido com 2 canais e 16-bit
    with wave.open(str(session.audio_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        data = struct.pack("<1000h", *([0] * 1000))
        wf.writeframes(data)

    token = CancelToken()
    token.cancel()  # Cancela antes ou durante

    pipeline = MeetingPipeline(
        session=session,
        cancel_token=token,
    )

    result = pipeline.run(from_stage=PipelineStage.TRANSCRIBE)
    assert result["status"] == "cancelled"
    manifest = session.load_manifest()
    assert manifest["status"] == "cancelled"

