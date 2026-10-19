"""
Gerenciador de Gravação em Disco (Zero-RAM Streaming Audio Writer)
Garante escrita contínua e imediata em disco sem acumular buffers de áudio na memória RAM.
"""

import wave
import threading
from pathlib import Path
from typing import Union
import logging

from src.config import SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH

logger = logging.getLogger(__name__)


class AudioDiskWriter:
    """
    Escritor contínuo de áudio WAV direto para arquivo em disco.
    Previne estouro de memória mantendo consumo de RAM fixo em < 5 MB durante gravações longas.
    """

    def __init__(
        self,
        filepath: Union[str, Path],
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        sample_width: int = SAMPLE_WIDTH,
    ):
        self.filepath = Path(filepath)
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width

        self._lock = threading.Lock()
        self._wav_file: wave.Wave_write | None = None
        self._total_frames = 0
        self._is_open = False

    def open(self):
        """Inicializa o arquivo WAV no disco e escreve o cabeçalho inicial."""
        with self._lock:
            if self._is_open:
                return

            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            self._wav_file = wave.open(str(self.filepath), "wb")
            self._wav_file.setnchannels(self.channels)
            self._wav_file.setsampwidth(self.sample_width)
            self._wav_file.setframerate(self.sample_rate)

            self._total_frames = 0
            self._is_open = True
            logger.info("Arquivo WAV aberto para streaming em disco: %s", self.filepath)

    def write_chunk(self, data: bytes) -> bool:
        """Escreve um chunk de bytes de áudio diretamente no arquivo e descarrega o buffer."""
        with self._lock:
            if not self._is_open or not self._wav_file:
                logger.warning("Tentativa de gravar em arquivo WAV já finalizado ou fechado.")
                return False

            try:
                self._wav_file.writeframes(data)
                num_frames = len(data) // (self.channels * self.sample_width)
                self._total_frames += num_frames
                return True
            except Exception as e:
                logger.warning("Erro ao escrever frames no arquivo WAV: %s", e)
                return False

    def close(self) -> Path:
        """Finaliza o arquivo WAV, grava os cabeçalhos com o tamanho correto e fecha."""
        with self._lock:
            if not self._is_open or not self._wav_file:
                return self.filepath

            try:
                self._wav_file.close()
            finally:
                self._wav_file = None
                self._is_open = False

            duration_sec = self._total_frames / self.sample_rate if self.sample_rate > 0 else 0
            logger.info(
                "Arquivo WAV fechado: %s (Duração: %.2fs, Frames: %d)",
                self.filepath,
                duration_sec,
                self._total_frames,
            )
            return self.filepath

    @property
    def duration_seconds(self) -> float:
        """Retorna a duração aproximada em segundos já gravada no disco."""
        with self._lock:
            if self.sample_rate <= 0:
                return 0.0
            return self._total_frames / self.sample_rate

    @property
    def is_active(self) -> bool:
        return self._is_open
