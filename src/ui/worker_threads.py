"""
Módulo de Threads Assíncronas (QThread) para Desacoplamento da UI.
Atua como camada de adaptação Qt em torno do MeetingPipeline agnóstico,
garantindo que a interface gráfica (PyQt6) nunca congele ou apresente lentidão.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from src.config import DEFAULT_RECORDING_PATH, get_typed_user_settings
from src.audio.recorder import DualAudioRecorder
from src.pipeline.session import SessionStore, MeetingSession
from src.pipeline.meeting_pipeline import MeetingPipeline, CancelToken, PipelineStage

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """
    Worker assíncrono Qt que encapsula o MeetingPipeline.
    1. Finaliza a gravação e aloca uma sessão isolada em sessions/<session_id>/
    2. Executa a transcrição dual-channel via faster-whisper com isolamento de RAM
    3. Diariza e sincroniza os canais de áudio
    4. Gera a ata executiva estruturada via Ollama (ou fallback inteligente)
    5. Exporta automaticamente para DOCX na pasta da sessão
    """

    # Sinais emitidos para a UI
    progress_changed = pyqtSignal(str, int)          # (mensagem, porcentagem 0-100)
    token_streamed = pyqtSignal(str)                # token gerado em tempo real
    pipeline_finished = pyqtSignal(object, str, str) # (MeetingMinutes, transcript_dialogue, recording_path)
    pipeline_error = pyqtSignal(str)                # mensagem de erro

    def __init__(
        self,
        recorder: Optional[DualAudioRecorder] = None,
        audio_path: Optional[Path] = None,
        session_id: Optional[str] = None,
        session: Optional[MeetingSession] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.recorder = recorder
        self._session = session
        self.audio_path = audio_path or (session.audio_path if session else DEFAULT_RECORDING_PATH)
        self.session_id = session_id or (session.session_id if session else None)
        self.cancel_token = CancelToken()

    def cancel(self):
        """Sinaliza cancelamento cooperativo imediato do pipeline."""
        self.cancel_token.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_token.is_cancelled

    @property
    def _is_cancelled(self) -> bool:
        return self.cancel_token.is_cancelled

    @_is_cancelled.setter
    def _is_cancelled(self, val: bool):
        if val:
            self.cancel_token.cancel()

    def run(self):
        try:
            # 1. Finaliza a gravação se o gravador foi passado e ainda estiver ativo
            if self.recorder and self.recorder.is_recording:
                self.progress_changed.emit("Finalizando gravação de áudio no disco...", 5)
                saved_audio = self.recorder.stop()
                if saved_audio and saved_audio.exists():
                    self.audio_path = saved_audio

            if not self.audio_path.exists():
                raise FileNotFoundError(f"Arquivo de áudio não encontrado: {self.audio_path}")

            if self.cancel_token.is_cancelled:
                return

            # 2. Inicializa a sessão persistente em sessions/<session_id>/ (se ainda não fornecida)
            store = SessionStore()
            if not self._session:
                self._session = store.create_session(self.session_id)

            # Copia o áudio gravado para a pasta dedicada da sessão apenas se forem caminhos distintos
            if self.audio_path.resolve() != self._session.audio_path.resolve():
                shutil.copy2(self.audio_path, self._session.audio_path)
                logger.info("Áudio copiado para a sessão: %s", self._session.audio_path)
            else:
                logger.info("Áudio gravado diretamente na sessão (Zero-Copy): %s", self._session.audio_path)

            # Limpeza automática de áudios antigos (LGPD)
            settings = get_typed_user_settings()
            try:
                purged = store.cleanup_old_audio(retention_days=settings.audio_retention_days)
                if purged:
                    logger.info("[LGPD] Áudios antigos purgados das sessões: %s", purged)
            except Exception as e:
                logger.warning("Erro ao verificar expurgo de áudios antigos: %s", e)

            if self.cancel_token.is_cancelled:
                return

            # 3. Executa o MeetingPipeline agnóstico
            pipeline = MeetingPipeline(
                session=self._session,
                settings=settings,
                on_progress=lambda msg, pct: self.progress_changed.emit(msg, pct),
                on_chunk=lambda tok: self.token_streamed.emit(tok),
                cancel_token=self.cancel_token,
            )

            result = pipeline.run(from_stage=PipelineStage.TRANSCRIBE)

            if self.cancel_token.is_cancelled or result.get("status") == "cancelled":
                logger.info("Execução do PipelineWorker cancelada.")
                return

            self.pipeline_finished.emit(
                result["minutes"],
                result["transcript_text"],
                str(result["audio_path"]),
            )

        except Exception as exc:
            logger.exception("Erro durante o processamento do pipeline: %s", exc)
            self.pipeline_error.emit(str(exc))
