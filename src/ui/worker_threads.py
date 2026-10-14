"""
Módulo de Threads Assíncronas (QThread) para Desacoplamento da UI
Executa o pipeline completo (Gravação -> Whisper -> Ollama -> Parser) em segundo plano,
garantindo que a interface gráfica (PyQt6) nunca congele ou apresente lentidão.
"""

import time
import logging
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from src.config import (
    DEFAULT_RECORDING_PATH,
    DEFAULT_TRANSCRIPT_PATH,
    OLLAMA_MODEL,
    OLLAMA_KEEP_ALIVE,
)
from src.audio.recorder import DualAudioRecorder
from src.transcription.whisper_engine import WhisperEngine
from src.transcription.post_process import (
    split_dual_channel_audio,
    merge_channel_transcripts,
    format_transcript_dialogue,
)
from src.minutes.prompts import generate_meeting_minutes_prompt
from src.minutes.ollama_client import OllamaClient
from src.minutes.parser import MinutesParser, MeetingMinutes

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """
    Worker assíncrono que orquestra sequencialmente:
    1. Finalização da gravação de áudio em disco
    2. Transcrição local com faster-whisper (int8) e descarregamento ativo de RAM
    3. Diarização e sincronização temporal de canais (Você vs Participantes)
    4. Geração da ata executiva via Ollama com streaming e keep_alive: 0s
    5. Parsing estruturado da ata para MeetingMinutes
    """

    # Sinais emitidos para a UI
    progress_changed = pyqtSignal(str, int)     # (mensagem, porcentagem 0-100)
    token_streamed = pyqtSignal(str)           # token gerado em tempo real
    pipeline_finished = pyqtSignal(object, str, str) # (MeetingMinutes, transcript_dialogue, recording_path)
    pipeline_error = pyqtSignal(str)           # mensagem de erro

    def __init__(
        self,
        recorder: Optional[DualAudioRecorder] = None,
        audio_path: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.recorder = recorder
        self.audio_path = audio_path or DEFAULT_RECORDING_PATH
        self._is_cancelled = False

    def cancel(self):
        """Sinaliza cancelamento do processamento."""
        self._is_cancelled = True

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

            if self._is_cancelled:
                return

            # 2. Fase de Transcrição (faster-whisper)
            self.progress_changed.emit("Iniciando transcrição de áudio com Whisper...", 15)

            # Separa os canais em memória ou temporários para diarização
            mic_wav, teams_wav = split_dual_channel_audio(self.audio_path)

            if self._is_cancelled:
                return

            self.progress_changed.emit("Transcrevendo canal de voz (Você)...", 25)
            # Utiliza o gerenciador de contexto para garantir descarregamento da RAM
            with WhisperEngine() as engine:
                mic_segments = engine.transcribe(mic_wav)

                if self._is_cancelled:
                    return

                self.progress_changed.emit("Transcrevendo canal do Teams (Participantes)...", 45)
                teams_segments = engine.transcribe(teams_wav)

            # Neste ponto o Whisper foi descarregado e a RAM voltou ao nível base
            self.progress_changed.emit("Whisper descarregado da memória. Sincronizando diálogos...", 60)
            merged_segments = merge_channel_transcripts(mic_segments, teams_segments)
            transcript_text = format_transcript_dialogue(merged_segments)

            # Se a transcrição estiver vazia (ex: teste rápido sem áudio), provê mensagem padrão
            if not transcript_text.strip():
                transcript_text = "[00:00:00] [Você]: Reunião iniciada sem detecção de voz nos canais de áudio."

            if self._is_cancelled:
                return

            # 3. Fase de Geração da Ata Executiva (Ollama com keep_alive: 0s)
            self.progress_changed.emit("Conectando ao Ollama (Llama 3.2 3B)...", 70)
            system_prompt, user_prompt = generate_meeting_minutes_prompt(transcript_text)

            client = OllamaClient()

            def on_chunk(token: str):
                if not self._is_cancelled:
                    self.token_streamed.emit(token)

            self.progress_changed.emit("Gerando ata executiva estruturada...", 80)
            raw_minutes_markdown = client.generate(
                prompt=user_prompt,
                system=system_prompt,
                model=OLLAMA_MODEL,
                keep_alive=OLLAMA_KEEP_ALIVE,
                on_chunk_callback=on_chunk,
            )

            if self._is_cancelled:
                return

            # 4. Parsing Estruturado
            self.progress_changed.emit("Validando estrutura da ata e matriz de ações...", 95)
            minutes_obj = MinutesParser.parse(raw_minutes_markdown)

            self.progress_changed.emit("Processamento concluído com sucesso!", 100)
            self.pipeline_finished.emit(minutes_obj, transcript_text, str(self.audio_path))

        except Exception as exc:
            logger.exception("Erro durante o processamento do pipeline: %s", exc)
            self.pipeline_error.emit(str(exc))
