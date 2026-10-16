"""
Módulo de Gerenciamento de Sessões de Reunião (SessionStore e MeetingSession).
Garante persistência isolada por sessão (áudio, transcrição, ata e logs)
e retenção controlada de áudio (LGPD).
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.config import SESSIONS_DIR

logger = logging.getLogger(__name__)


class MeetingSession:
    """
    Representa uma sessão de reunião individual encapsulando seus artefatos em disco.
    """

    def __init__(self, session_id: str, session_dir: Path):
        self.session_id = session_id
        self.session_dir = session_dir

    @property
    def audio_path(self) -> Path:
        return self.session_dir / "audio.wav"

    @property
    def transcript_path(self) -> Path:
        return self.session_dir / "transcript.json"

    @property
    def minutes_path(self) -> Path:
        return self.session_dir / "minutes.json"

    @property
    def docx_path(self) -> Path:
        return self.session_dir / "ata.docx"

    @property
    def log_path(self) -> Path:
        return self.session_dir / "session.log"

    @property
    def manifest_path(self) -> Path:
        return self.session_dir / "manifest.json"

    def exists(self) -> bool:
        return self.session_dir.exists() and self.session_dir.is_dir()

    def has_audio(self) -> bool:
        return self.audio_path.exists() and self.audio_path.stat().st_size > 0

    def has_transcript(self) -> bool:
        return self.transcript_path.exists() and self.transcript_path.stat().st_size > 0

    def has_minutes(self) -> bool:
        return self.minutes_path.exists() and self.minutes_path.stat().st_size > 0

    def has_docx(self) -> bool:
        return self.docx_path.exists() and self.docx_path.stat().st_size > 0

    def load_manifest(self) -> Dict[str, Any]:
        """Carrega os metadados da sessão a partir do manifest.json."""
        if not self.manifest_path.exists():
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler manifest em {self.manifest_path}: {e}")
            return {}

    def save_manifest(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Salva ou atualiza os metadados no manifest.json da sessão."""
        data = self.load_manifest()
        if metadata:
            data.update(metadata)
        data.setdefault("session_id", self.session_id)
        data.setdefault("updated_at", datetime.now().isoformat())

        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar manifest da sessão {self.session_id}: {e}")

    def __repr__(self) -> str:
        return f"<MeetingSession id='{self.session_id}' dir='{self.session_dir}'>"


class SessionStore:
    """
    Gerenciador central do ciclo de vida das sessões de reunião.
    Permite criar, buscar, listar e realizar expurgo LGPD de áudios antigos.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or SESSIONS_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, session_id: Optional[str] = None) -> MeetingSession:
        """
        Cria uma nova sessão com pasta dedicada e manifest inicial.
        Se session_id não for informado, usa o timestamp atual YYYY-MM-DD_HHMMSS.
        """
        if not session_id:
            session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")

        session_dir = self.root_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        session = MeetingSession(session_id, session_dir)
        session.save_manifest({
            "created_at": datetime.now().isoformat(),
            "session_id": session_id,
            "status": "created"
        })
        logger.info(f"Sessão criada: {session_id} em {session_dir}")
        return session

    def get_session(self, session_id: str) -> Optional[MeetingSession]:
        """Recupera uma sessão existente pelo session_id."""
        target_dir = self.root_dir / session_id
        if target_dir.exists() and target_dir.is_dir():
            return MeetingSession(session_id, target_dir)
        return None

    def list_sessions(self) -> List[MeetingSession]:
        """
        Retorna todas as sessões ordenadas da mais recente para a mais antiga.
        """
        if not self.root_dir.exists():
            return []

        sessions = []
        for item in self.root_dir.iterdir():
            if item.is_dir():
                sessions.append(MeetingSession(item.name, item))

        # Ordena descendentemente pelo nome da pasta (que é YYYY-MM-DD_HHMMSS por padrão)
        # e como fallback pelo mtime da pasta
        def sort_key(s: MeetingSession):
            # Se session_id iniciar por data YYYY-MM-DD, usa como chave cronológica primária
            sid = s.session_id
            if len(sid) >= 10 and sid[:4].isdigit() and sid[4] == "-":
                return sid
            try:
                manifest = s.load_manifest()
                if "created_at" in manifest:
                    return manifest["created_at"]
            except Exception:
                pass
            return sid

        sessions.sort(key=sort_key, reverse=True)
        return sessions

    def get_latest_session(self) -> Optional[MeetingSession]:
        """Retorna a sessão mais recente ou None se nenhuma existir."""
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def cleanup_old_audio(self, retention_days: int = 7) -> List[str]:
        """
        Expurgo de áudio conforme LGPD:
        Remove audio.wav de sessões mais antigas que `retention_days`.
        PRESERVA transcript.json, minutes.json, ata.docx, manifest.json e session.log.
        Retorna a lista de session_ids cujo áudio foi purgado.
        """
        if retention_days <= 0:
            return []

        purged: List[str] = []
        now = datetime.now()
        cutoff_date = now - timedelta(days=retention_days)

        for session in self.list_sessions():
            if not session.has_audio():
                continue

            session_date = None
            manifest = session.load_manifest()

            if "created_at" in manifest:
                try:
                    session_date = datetime.fromisoformat(manifest["created_at"])
                except Exception:
                    pass

            if not session_date:
                try:
                    # Tenta parsear nome YYYY-MM-DD_HHMMSS
                    session_date = datetime.strptime(session.session_id[:17], "%Y-%m-%d_%H%M%S")
                except Exception:
                    # Fallback para mtime do arquivo de áudio
                    mtime = session.audio_path.stat().st_mtime
                    session_date = datetime.fromtimestamp(mtime)

            if session_date < cutoff_date:
                try:
                    session.audio_path.unlink()
                    session.save_manifest({
                        "audio_purged_at": now.isoformat(),
                        "audio_retention_days": retention_days
                    })
                    purged.append(session.session_id)
                    logger.info(
                        f"[LGPD Cleanup] Áudio expirado ({retention_days}d) removido com sucesso "
                        f"da sessão {session.session_id}. Transcrição e ata preservadas."
                    )
                except Exception as e:
                    logger.warning(
                        f"Falha ao remover áudio antigo da sessão {session.session_id}: {e}"
                    )

        return purged
