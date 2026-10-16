"""
Módulo Central do Pipeline Desacoplado de Processamento de Reuniões.
Totalmente desacoplado de PyQt6 para permitir execução headless via CLI ou automação,
com suporte a cancelamento cooperativo imediato (CancelToken) e log por sessão.
"""

import json
import logging
import os
import time
import wave
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Tuple, List, Union

from src.config import (
    DEFAULT_TRANSCRIPT_PATH,
    OLLAMA_MODEL,
    UserSettings,
    get_typed_user_settings,
)
from src.pipeline.session import MeetingSession
from src.transcription.whisper_engine import WhisperEngine
from src.transcription.post_process import (
    split_dual_channel_audio,
    merge_channel_transcripts,
    format_transcript_dialogue,
)
from src.minutes.ollama_client import OllamaClient
from src.minutes.parser import MinutesParser, MeetingMinutes
from src.minutes.generator import MinutesGenerator
from src.exporter.docx_builder import DocxMeetingMinutesBuilder

logger = logging.getLogger(__name__)


class CancelToken:
    """Token de cancelamento cooperativo entre threads e geradores."""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


class PipelineStage(str, Enum):
    TRANSCRIBE = "transcribe"
    MERGE = "merge"
    GENERATE = "generate"
    EXPORT = "export"


STAGE_ORDER = {
    PipelineStage.TRANSCRIBE: 1,
    PipelineStage.MERGE: 2,
    PipelineStage.GENERATE: 3,
    PipelineStage.EXPORT: 4,
}


def extract_audio_metadata(audio_path: Path) -> Tuple[str, str]:
    """Extrai data de modificação e duração formatada (HH:MM:SS) de um arquivo WAV."""
    meeting_date_str = time.strftime("%d/%m/%Y %H:%M")
    meeting_duration_str = "00:00"
    try:
        if audio_path.exists():
            mtime = audio_path.stat().st_mtime
            meeting_date_str = time.strftime("%d/%m/%Y %H:%M", time.localtime(mtime))
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    dur_sec = int(frames / rate)
                    m, s = divmod(dur_sec, 60)
                    h, m = divmod(m, 60)
                    meeting_duration_str = (
                        f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                    )
    except Exception as e:
        logger.debug("Não foi possível extrair metadados do áudio: %s", e)
    return meeting_date_str, meeting_duration_str


def create_fallback_minutes(
    meeting_date_str: str,
    meeting_duration_str: Optional[str] = None,
    user_speaker_name: str = "Você",
    reason: str = "O serviço local do Ollama não estava ativo no momento para síntese automática por IA.",
) -> MeetingMinutes:
    """Gera uma minuta executiva estruturada de fallback quando o Ollama está indisponível."""
    raw_markdown = f"""# ATA DE REUNIÃO: Reunião Microsoft Teams

## 1. Informações Gerais
- Data: {meeting_date_str}
- Duração: {meeting_duration_str or 'Não especificada'}
- Plataforma: Microsoft Teams (Gravação Local)
- Participantes: {user_speaker_name}, Participantes da Reunião

## 2. Resumo Executivo
Reunião gravada e transcrita localmente com sucesso. {reason} O diálogo integral está preservado na transcrição completa.

## 3. Pautas Discutidas
### Diálogo da Reunião
Consulte o conteúdo completo da conversa na aba de transcrição para revisar as pautas abordadas.

## 4. Decisões Tomadas
- Inicie o Ollama com 'ollama run {OLLAMA_MODEL}' para sínteses automáticas por IA.
- Preencha ou ajuste as decisões tomadas diretamente nos campos acima antes de exportar.

## 5. Plano de Ação
| Ação / O Quê | Responsável | Prazo | Evidência |
|---|---|---|---|
| Revisar transcrição e deliberações | {user_speaker_name} | Imediato | - |

## 6. Próximos Passos e Pendências
- Encaminhar ata revisada para os participantes.
"""
    return MinutesParser.parse(raw_markdown)


class MeetingPipeline:
    """
    Pipeline orquestrador de reuniões, desacoplado de qualquer biblioteca de GUI.
    Pode ser executado tanto a partir da interface Qt (via worker thread)
    quanto via linha de comando (CLI) para reprocessamento de sessões passadas.
    """

    def __init__(
        self,
        session: MeetingSession,
        settings: Optional[UserSettings] = None,
        on_progress: Optional[Callable[[str, int], None]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        cancel_token: Optional[CancelToken] = None,
    ):
        self.session = session
        self.settings = settings or get_typed_user_settings()
        self.on_progress = on_progress
        self.on_chunk = on_chunk
        self.cancel_token = cancel_token or CancelToken()

    def _emit_progress(self, message: str, percent: int) -> None:
        logger.info(f"[{percent}%] {message}")
        if self.on_progress and not self.cancel_token.is_cancelled:
            try:
                self.on_progress(message, percent)
            except Exception as e:
                logger.warning(f"Erro no callback de progresso: {e}")

    def _emit_chunk(self, token: str) -> None:
        if self.on_chunk and not self.cancel_token.is_cancelled:
            try:
                self.on_chunk(token)
            except Exception as e:
                logger.warning(f"Erro no callback de chunk: {e}")

    def run(
        self,
        from_stage: Union[PipelineStage, str] = PipelineStage.TRANSCRIBE,
    ) -> Dict[str, Any]:
        """
        Executa o pipeline completo a partir do estágio especificado.
        Retorna dicionário com resultados e artefatos gerados.
        """
        if isinstance(from_stage, str):
            from_stage = PipelineStage(from_stage.lower())

        target_level = STAGE_ORDER[from_stage]

        # Anexa handler de log por sessão durante a execução
        session_log_handler = None
        try:
            self.session.session_dir.mkdir(parents=True, exist_ok=True)
            session_log_handler = logging.FileHandler(
                self.session.log_path, encoding="utf-8", mode="a"
            )
            session_log_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            logging.getLogger().addHandler(session_log_handler)
        except Exception as e:
            logger.warning(f"Não foi possível abrir log de sessão: {e}")

        try:
            self.session.save_manifest({
                "status": "processing",
                "current_stage": from_stage.value,
                "start_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

            transcript_text = ""
            merged_segments: List[Dict[str, Any]] = []
            if self.cancel_token.is_cancelled:
                return self._abort_cancelled()

            # -------------------------------------------------------------
            # Estágio 1: TRANSCRIBE
            # -------------------------------------------------------------
            if target_level <= STAGE_ORDER[PipelineStage.TRANSCRIBE]:
                if self.cancel_token.is_cancelled:
                    return self._abort_cancelled()

                if not self.session.has_audio():
                    raise FileNotFoundError(
                        f"Áudio não encontrado na sessão {self.session.session_id}: {self.session.audio_path}"
                    )

                transcript_text, merged_segments = self.run_transcription()

                if self.cancel_token.is_cancelled:
                    return self._abort_cancelled()

            # -------------------------------------------------------------
            # Estágio 2: MERGE (se iniciado em MERGE)
            # -------------------------------------------------------------
            elif target_level == STAGE_ORDER[PipelineStage.MERGE]:
                # Carrega segmentos brutos se existirem
                transcript_text, merged_segments = self._load_or_require_transcript()
                if self.cancel_token.is_cancelled:
                    return self._abort_cancelled()

            # Se começou em GENERATE ou EXPORT, carrega transcrição existente
            else:
                transcript_text, merged_segments = self._load_or_require_transcript()

            # -------------------------------------------------------------
            # Estágio 3: GENERATE
            # -------------------------------------------------------------
            if target_level <= STAGE_ORDER[PipelineStage.GENERATE]:
                minutes_obj = self.run_generation(transcript_text)
                if self.cancel_token.is_cancelled:
                    return self._abort_cancelled()
            else:
                minutes_obj = self._load_or_require_minutes()

            # -------------------------------------------------------------
            # Estágio 4: EXPORT
            # -------------------------------------------------------------
            if target_level <= STAGE_ORDER[PipelineStage.EXPORT]:
                docx_path = self.run_export(minutes_obj)
            else:
                docx_path = self.session.docx_path

            self._emit_progress("Processamento concluído com sucesso!", 100)
            self.session.save_manifest({
                "status": "completed",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "docx_path": str(docx_path),
            })

            return {
                "session_id": self.session.session_id,
                "status": "completed",
                "minutes": minutes_obj,
                "transcript_text": transcript_text,
                "audio_path": self.session.audio_path,
                "docx_path": docx_path,
            }

        except Exception as exc:
            logger.exception("Falha na execução do pipeline: %s", exc)
            self.session.save_manifest({
                "status": "error",
                "error_message": str(exc),
                "failed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            raise
        finally:
            if session_log_handler:
                try:
                    logging.getLogger().removeHandler(session_log_handler)
                    session_log_handler.close()
                except Exception:
                    pass

    def run_transcription(self) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Executa a transcrição dual-channel via faster-whisper com isolamento e descarregamento de RAM.
        Salva o resultado em session.transcript_path e sincroniza em DEFAULT_TRANSCRIPT_PATH.
        """
        if self.cancel_token.is_cancelled:
            return "", []

        self._emit_progress("Iniciando transcrição de áudio com Whisper...", 10)

        mic_wav, teams_wav, _ = split_dual_channel_audio(self.session.audio_path)

        if self.cancel_token.is_cancelled:
            return "", []

        preferred_model = self.settings.model_profile
        corporate_glossary = self.settings.corporate_glossary
        user_speaker_name = self.settings.user_speaker_name

        with WhisperEngine(model_size=preferred_model) as engine:
            self._emit_progress(
                f"Transcrevendo canal de voz ({user_speaker_name}) com Whisper '{engine.model_size}'...",
                25,
            )
            mic_segments = engine.transcribe(
                mic_wav,
                initial_prompt=corporate_glossary,
                cancel_token=self.cancel_token,
            )

            if self.cancel_token.is_cancelled:
                return "", []

            self._emit_progress(
                f"Transcrevendo canal do Teams (Participantes) com Whisper '{engine.model_size}'...",
                45,
            )
            teams_segments = engine.transcribe(
                teams_wav,
                initial_prompt=corporate_glossary,
                cancel_token=self.cancel_token,
            )

        if self.cancel_token.is_cancelled:
            return "", []

        self._emit_progress("Whisper descarregado da memória. Sincronizando diálogos...", 60)
        merged_segments = merge_channel_transcripts(
            mic_segments,
            teams_segments,
            user_label=user_speaker_name,
        )
        transcript_text = format_transcript_dialogue(merged_segments)

        if not transcript_text.strip():
            transcript_text = (
                f"[00:00:00] [{user_speaker_name}]: Reunião iniciada sem detecção de voz nos canais de áudio."
            )

        # Salva transcript estruturado e legível na pasta da sessão
        transcript_payload = {
            "session_id": self.session.session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "segments_count": len(merged_segments),
            "text": transcript_text,
            "segments": merged_segments,
        }
        try:
            with open(self.session.transcript_path, "w", encoding="utf-8") as f:
                json.dump(transcript_payload, f, ensure_ascii=False, indent=2)
            logger.info("Transcrição estruturada salva em '%s'.", self.session.transcript_path)

            # Retrocompatibilidade: atualiza também o arquivo default em temp/
            DEFAULT_TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_TRANSCRIPT_PATH.write_text(transcript_text, encoding="utf-8")
        except Exception as e:
            logger.warning("Erro ao persistir transcrição em disco: %s", e)

        self.session.save_manifest({
            "has_transcript": True,
            "segments_count": len(merged_segments),
        })

        return transcript_text, merged_segments

    def run_generation(self, transcript_text: Optional[str] = None) -> MeetingMinutes:
        """
        Executa a síntese da ata executiva via Ollama ou fallback seguro.
        Persiste o resultado em session.minutes_path.
        """
        if not transcript_text:
            transcript_text, _ = self._load_or_require_transcript()

        meeting_date_str, meeting_duration_str = extract_audio_metadata(self.session.audio_path)
        user_speaker_name = self.settings.user_speaker_name

        client = OllamaClient()

        if not client.is_available():
            logger.warning("Ollama offline em localhost:11434. Gerando ata de fallback estruturada.")
            self._emit_progress("Ollama offline. Gerando minuta com transcrição preservada...", 85)
            minutes_obj = create_fallback_minutes(
                meeting_date_str=meeting_date_str,
                meeting_duration_str=meeting_duration_str,
                user_speaker_name=user_speaker_name,
            )
        else:
            self._emit_progress("Iniciando síntese inteligente da ata com IA...", 70)
            generator = MinutesGenerator(ollama_client=client)
            try:
                minutes_obj, _ = generator.generate(
                    transcript_text=transcript_text,
                    meeting_date=meeting_date_str,
                    meeting_duration=meeting_duration_str,
                    user_speaker_name=user_speaker_name,
                    progress_callback=self._emit_progress,
                    token_callback=self._emit_chunk,
                )
            except Exception as ollama_err:
                logger.warning(
                    "Falha na comunicação com Ollama (%s). Usando minuta de fallback estruturada.",
                    ollama_err,
                )
                minutes_obj = create_fallback_minutes(
                    meeting_date_str=meeting_date_str,
                    meeting_duration_str=meeting_duration_str,
                    user_speaker_name=user_speaker_name,
                    reason=f"Ollama retornou erro durante síntese ({ollama_err}).",
                )

        # Salva minutes.json na sessão
        try:
            with open(self.session.minutes_path, "w", encoding="utf-8") as f:
                json.dump(minutes_obj.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("Minuta estruturada salva em '%s'.", self.session.minutes_path)
        except Exception as e:
            logger.warning("Erro ao persistir minutes.json: %s", e)

        self.session.save_manifest({
            "has_minutes": True,
            "minutes_title": minutes_obj.title,
            "action_items_count": len(minutes_obj.action_items),
        })

        return minutes_obj

    def run_export(self, minutes: Optional[MeetingMinutes] = None) -> Path:
        """
        Exporta a ata para formato Word (.docx) na pasta da sessão.
        """
        if not minutes:
            minutes = self._load_or_require_minutes()

        self._emit_progress("Exportando documento Word (.docx)...", 95)
        out_path = self.session.docx_path
        builder = DocxMeetingMinutesBuilder()
        builder.build(minutes, out_path)
        logger.info("Documento Word gerado em '%s'.", out_path)

        self.session.save_manifest({
            "has_docx": True,
            "docx_path": str(out_path),
        })

        return out_path

    def _load_or_require_transcript(self) -> Tuple[str, List[Dict[str, Any]]]:
        """Carrega a transcrição da sessão ou lança exceção se não existir."""
        if not self.session.has_transcript():
            raise FileNotFoundError(
                f"Transcrição não encontrada para a sessão {self.session.session_id}: {self.session.transcript_path}"
            )
        try:
            with open(self.session.transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("text", ""), data.get("segments", [])
                elif isinstance(data, str):
                    return data, []
        except Exception as e:
            logger.warning(f"Erro ao ler transcript.json: {e}")
        return "", []

    def _load_or_require_minutes(self) -> MeetingMinutes:
        """Carrega a ata estruturada da sessão ou lança exceção se não existir."""
        if not self.session.has_minutes():
            raise FileNotFoundError(
                f"Ata (minutes.json) não encontrada para a sessão {self.session.session_id}: {self.session.minutes_path}"
            )
        with open(self.session.minutes_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return MeetingMinutes.from_dict(data)

    def _abort_cancelled(self) -> Dict[str, Any]:
        logger.info("Operação do pipeline cancelada pelo usuário.")
        self.session.save_manifest({
            "status": "cancelled",
            "cancelled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return {
            "session_id": self.session.session_id,
            "status": "cancelled",
            "minutes": None,
            "transcript_text": "",
            "audio_path": self.session.audio_path,
            "docx_path": None,
        }
