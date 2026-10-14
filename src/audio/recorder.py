"""
Gravador de Áudio Dual-Channel com Streaming Direto para Disco
Utiliza callbacks assíncronos do PortAudio/WASAPI para captura contínua e sem bloqueio
do Microfone (Você) e Loopback (Teams), intercalando em 16kHz e escrevendo no disco.
"""

import time
import queue
import threading
import logging
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

from src.config import (
    SAMPLE_RATE,
    CHANNELS,
    SAMPLE_WIDTH,
    CHUNK_DURATION_SEC,
    DEFAULT_RECORDING_PATH,
)
from src.audio.disk_writer import AudioDiskWriter
from src.audio.devices import get_default_devices, AudioDeviceInfo

logger = logging.getLogger(__name__)


def resample_to_target(
    audio: np.ndarray,
    orig_sr: int,
    target_sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Reamostra array 1D (mono) para a taxa alvo (16.000 Hz).
    Otimizado para decimação inteira ultra-rápida (ex: 48k/16k = 3).
    """
    if len(audio) == 0:
        return np.zeros(0, dtype=np.int16)

    if orig_sr == target_sr:
        return audio

    if orig_sr % target_sr == 0:
        step = orig_sr // target_sr
        return audio[::step]

    num_samples = int(round(len(audio) * target_sr / orig_sr))
    if num_samples <= 0:
        return np.zeros(0, dtype=np.int16)

    orig_indices = np.linspace(0, len(audio) - 1, num_samples)
    resampled = np.interp(orig_indices, np.arange(len(audio)), audio)
    return resampled.astype(np.int16)


def to_mono_int16(raw_bytes: bytes, channels: int) -> np.ndarray:
    """Converte buffer de bytes para array mono int16 tirando a média entre canais se estéreo."""
    if not raw_bytes:
        return np.zeros(0, dtype=np.int16)

    data = np.frombuffer(raw_bytes, dtype=np.int16)
    if channels > 1:
        usable_len = (len(data) // channels) * channels
        if usable_len == 0:
            return np.zeros(0, dtype=np.int16)
        data = data[:usable_len].reshape(-1, channels)
        mono = data.mean(axis=1).astype(np.int16)
        return mono
    return data


class DualAudioRecorder:
    """
    Grava áudio do usuário e dos participantes em canais independentes (Esq: Você, Dir: Teams),
    gravando blocos em streaming diretamente para o arquivo WAV em disco.
    Mantém consumo de RAM constante em < 40 MB.
    """

    def __init__(
        self,
        output_path: Optional[Path] = None,
        target_sample_rate: int = SAMPLE_RATE,
    ):
        self.output_path = Path(output_path) if output_path else DEFAULT_RECORDING_PATH
        self.sample_rate = target_sample_rate

        self.writer = AudioDiskWriter(
            filepath=self.output_path,
            sample_rate=self.sample_rate,
            channels=CHANNELS,
            sample_width=SAMPLE_WIDTH,
        )

        self._is_recording = False
        self._is_paused = False
        self._start_time: float = 0.0
        self._pause_duration: float = 0.0
        self._pause_start: float = 0.0

        # Filas para buffers de áudio reamostrados (tamanho máximo pequeno para garantir Zero-RAM)
        self._mic_queue: queue.Queue = queue.Queue(maxsize=100)
        self._loop_queue: queue.Queue = queue.Queue(maxsize=100)

        self._writer_thread: Optional[threading.Thread] = None
        self._pyaudio_instance = None
        self._mic_stream = None
        self._loop_stream = None

        # Níveis de áudio (RMS) para os medidores visuais
        self._mic_level: float = 0.0
        self._loopback_level: float = 0.0

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def get_elapsed_seconds(self) -> float:
        """Retorna a duração da gravação líquida (descontadas as pausas)."""
        if not self._is_recording:
            return 0.0
        if self._is_paused:
            return self._pause_start - self._start_time - self._pause_duration
        return time.time() - self._start_time - self._pause_duration

    def get_audio_levels(self) -> Tuple[float, float]:
        """Retorna os níveis RMS atuais normalizados entre 0.0 e 1.0 (Mic, Teams)."""
        return self._mic_level, self._loopback_level

    def start(self):
        """Inicia a gravação dual e os fluxos assíncronos."""
        if self._is_recording:
            logger.warning("Gravação já está em andamento.")
            return

        self.writer.open()
        self._is_recording = True
        self._is_paused = False
        self._start_time = time.time()
        self._pause_duration = 0.0

        # Limpa filas
        while not self._mic_queue.empty():
            self._mic_queue.get_nowait()
        while not self._loop_queue.empty():
            self._loop_queue.get_nowait()

        devices = get_default_devices()
        mic_dev: Optional[AudioDeviceInfo] = devices.get("mic")
        loopback_dev: Optional[AudioDeviceInfo] = devices.get("loopback")

        logger.info("Dispositivo Mic: %s", mic_dev)
        logger.info("Dispositivo Loopback: %s", loopback_dev)

        import pyaudiowpatch as pyaudio

        self._pyaudio_instance = pyaudio.PyAudio()

        # Configuração do stream do Microfone
        if mic_dev:
            mic_sr = mic_dev.sample_rate
            mic_ch = mic_dev.channels
            frames_per_buf = int(mic_sr * 0.1)  # Buffer de 100ms para baixa latência

            def mic_callback(in_data, frame_count, time_info, status):
                if self._is_recording and not self._is_paused and in_data:
                    mono = to_mono_int16(in_data, mic_ch)
                    resampled = resample_to_target(mono, mic_sr, self.sample_rate)
                    try:
                        self._mic_queue.put_nowait(resampled)
                    except queue.Full:
                        pass
                return (None, pyaudio.paContinue)

            try:
                self._mic_stream = self._pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=mic_ch,
                    rate=mic_sr,
                    input=True,
                    input_device_index=mic_dev.id,
                    frames_per_buffer=frames_per_buf,
                    stream_callback=mic_callback,
                )
                self._mic_stream.start_stream()
                logger.info("Stream de Microfone aberto com callback (WASAPI).")
            except Exception as e:
                logger.warning("Erro ao abrir Microfone com callback: %s", e)

        # Configuração do stream do Loopback (Teams)
        if loopback_dev:
            loop_sr = loopback_dev.sample_rate
            loop_ch = loopback_dev.channels
            frames_per_buf = int(loop_sr * 0.1)  # Buffer de 100ms

            def loop_callback(in_data, frame_count, time_info, status):
                if self._is_recording and not self._is_paused and in_data:
                    mono = to_mono_int16(in_data, loop_ch)
                    resampled = resample_to_target(mono, loop_sr, self.sample_rate)
                    try:
                        self._loop_queue.put_nowait(resampled)
                    except queue.Full:
                        pass
                return (None, pyaudio.paContinue)

            try:
                self._loop_stream = self._pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=loop_ch,
                    rate=loop_sr,
                    input=True,
                    input_device_index=loopback_dev.id,
                    frames_per_buffer=frames_per_buf,
                    stream_callback=loop_callback,
                )
                self._loop_stream.start_stream()
                logger.info("Stream de Loopback Teams aberto com callback (WASAPI).")
            except Exception as e:
                logger.warning("Erro ao abrir Loopback com callback: %s", e)

        # Inicia a thread de escrita que drena as filas e escreve no arquivo WAV
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="AudioDiskWriterThread",
            daemon=True,
        )
        self._writer_thread.start()
        logger.info("Gravação de áudio iniciada com sucesso.")

    def pause(self):
        """Pausa a gravação."""
        if self._is_recording and not self._is_paused:
            self._is_paused = True
            self._pause_start = time.time()
            logger.info("Gravação pausada.")

    def resume(self):
        """Retoma a gravação."""
        if self._is_recording and self._is_paused:
            self._pause_duration += time.time() - self._pause_start
            self._is_paused = False
            logger.info("Gravação retomada.")

    def stop(self) -> Path:
        """Para todos os fluxos e finaliza o arquivo WAV no disco."""
        if not self._is_recording:
            return self.output_path

        self._is_recording = False

        # Para streams
        if self._mic_stream:
            try:
                self._mic_stream.stop_stream()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

        if self._loop_stream:
            try:
                self._loop_stream.stop_stream()
                self._loop_stream.close()
            except Exception:
                pass
            self._loop_stream = None

        if self._pyaudio_instance:
            try:
                self._pyaudio_instance.terminate()
            except Exception:
                pass
            self._pyaudio_instance = None

        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=2.0)

        saved_path = self.writer.close()
        self._mic_level = 0.0
        self._loopback_level = 0.0
        logger.info("Gravação finalizada. Arquivo salvo em: %s", saved_path)
        return saved_path

    def _writer_loop(self):
        """Consome dados das filas e escreve periodicamente no arquivo em disco."""
        chunk_target_len = int(self.sample_rate * 0.1)  # 1600 amostras (0.1s a 16kHz)

        mic_buf = np.zeros(0, dtype=np.int16)
        loop_buf = np.zeros(0, dtype=np.int16)

        while self._is_recording or not self._mic_queue.empty() or not self._loop_queue.empty():
            # Drena buffers disponíveis da fila de microfone
            while not self._mic_queue.empty():
                try:
                    chunk = self._mic_queue.get_nowait()
                    mic_buf = np.concatenate([mic_buf, chunk]) if len(mic_buf) > 0 else chunk
                except queue.Empty:
                    break

            # Drena buffers disponíveis da fila de loopback
            while not self._loop_queue.empty():
                try:
                    chunk = self._loop_queue.get_nowait()
                    loop_buf = np.concatenate([loop_buf, chunk]) if len(loop_buf) > 0 else chunk
                except queue.Empty:
                    break

            # Se um dos canais estiver em silêncio no Windows WASAPI (ex: ninguém falando no Teams),
            # preenche o canal silencioso com zeros para manter a sincronia temporal exata
            max_len = max(len(mic_buf), len(loop_buf))

            if max_len >= chunk_target_len:
                # Alinha os dois buffers para max_len usando zeros se necessário
                if len(mic_buf) < max_len:
                    mic_buf = np.pad(mic_buf, (0, max_len - len(mic_buf)))
                if len(loop_buf) < max_len:
                    loop_buf = np.pad(loop_buf, (0, max_len - len(loop_buf)))

                write_len = (max_len // chunk_target_len) * chunk_target_len

                sub_mic = mic_buf[:write_len]
                sub_loop = loop_buf[:write_len]

                mic_buf = mic_buf[write_len:]
                loop_buf = loop_buf[write_len:]

                # Calcula RMS para o VU meter
                self._mic_level = float(np.sqrt(np.mean(sub_mic.astype(np.float32) ** 2)) / 32768.0)
                self._loopback_level = float(np.sqrt(np.mean(sub_loop.astype(np.float32) ** 2)) / 32768.0)

                # Intercala canais: Canal 0 = Mic (Você), Canal 1 = Teams (Participantes)
                stereo = np.empty((write_len, 2), dtype=np.int16)
                stereo[:, 0] = sub_mic
                stereo[:, 1] = sub_loop

                # Gravação em disco com Zero-RAM!
                self.writer.write_chunk(stereo.tobytes())
            else:
                time.sleep(0.05)
