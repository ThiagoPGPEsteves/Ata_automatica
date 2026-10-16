"""
Testes automatizados para o gerenciamento de sessões e expurgo de áudio LGPD (SessionStore e MeetingSession).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from src.pipeline.session import MeetingSession, SessionStore


def test_session_paths_and_manifest(tmp_path):
    store = SessionStore(root_dir=tmp_path)
    session = store.create_session("2026-10-16_100000")

    assert session.session_id == "2026-10-16_100000"
    assert session.session_dir == tmp_path / "2026-10-16_100000"
    assert session.audio_path == session.session_dir / "audio.wav"
    assert session.transcript_path == session.session_dir / "transcript.json"
    assert session.minutes_path == session.session_dir / "minutes.json"
    assert session.docx_path == session.session_dir / "ata.docx"
    assert session.log_path == session.session_dir / "session.log"
    assert session.manifest_path == session.session_dir / "manifest.json"

    assert session.exists()
    assert not session.has_audio()
    assert not session.has_transcript()
    assert not session.has_minutes()
    assert not session.has_docx()

    manifest = session.load_manifest()
    assert manifest["session_id"] == "2026-10-16_100000"
    assert manifest["status"] == "created"

    session.save_manifest({"custom_field": "test_val"})
    updated = session.load_manifest()
    assert updated["custom_field"] == "test_val"
    assert updated["session_id"] == "2026-10-16_100000"


def test_session_detection_of_artifacts(tmp_path):
    store = SessionStore(root_dir=tmp_path)
    session = store.create_session("2026-10-16_110000")

    # Cria arquivos simulados
    session.audio_path.write_bytes(b"RIFFmockwavcontent")
    session.transcript_path.write_text('{"text": "ola"}', encoding="utf-8")
    session.minutes_path.write_text('{"title": "ata"}', encoding="utf-8")
    session.docx_path.write_bytes(b"PKmockdocx")

    assert session.has_audio()
    assert session.has_transcript()
    assert session.has_minutes()
    assert session.has_docx()


def test_session_list_and_ordering(tmp_path):
    store = SessionStore(root_dir=tmp_path)
    s1 = store.create_session("2026-10-15_100000")
    s2 = store.create_session("2026-10-16_100000")
    s3 = store.create_session("2026-10-14_100000")

    sessions = store.list_sessions()
    session_ids = [s.session_id for s in sessions]
    # Mais recente primeiro
    assert session_ids == ["2026-10-16_100000", "2026-10-15_100000", "2026-10-14_100000"]
    latest = store.get_latest_session()
    assert latest is not None
    assert latest.session_id == "2026-10-16_100000"


def test_cleanup_old_audio_lgpd(tmp_path):
    store = SessionStore(root_dir=tmp_path)

    # 1. Sessão antiga (10 dias atrás)
    old_session = store.create_session("2026-10-06_100000")
    ten_days_ago = (datetime.now() - timedelta(days=10)).isoformat()
    old_session.save_manifest({"created_at": ten_days_ago})
    old_session.audio_path.write_bytes(b"OLD_AUDIO_DATA_LONG")
    old_session.transcript_path.write_text('{"text": "Transcricao preservada"}', encoding="utf-8")
    old_session.docx_path.write_bytes(b"DOCX_PRESERVED")

    # 2. Sessão recente (hoje)
    new_session = store.create_session("2026-10-16_100000")
    new_session.audio_path.write_bytes(b"NEW_AUDIO_DATA")
    new_session.transcript_path.write_text('{"text": "Transcricao recente"}', encoding="utf-8")

    assert old_session.has_audio()
    assert new_session.has_audio()

    # Executa limpeza com retenção de 7 dias
    purged = store.cleanup_old_audio(retention_days=7)

    assert "2026-10-06_100000" in purged
    assert "2026-10-16_100000" not in purged

    # Verifica que o áudio antigo foi excluído
    assert not old_session.has_audio()
    # Verifica que transcrição e DOCX antigos foram PRESERVADOS
    assert old_session.has_transcript()
    assert old_session.has_docx()

    # Verifica que o manifesto registrou o expurgo
    old_manifest = old_session.load_manifest()
    assert "audio_purged_at" in old_manifest
    assert old_manifest["audio_retention_days"] == 7

    # Verifica que a sessão recente manteve seu áudio intacto
    assert new_session.has_audio()
