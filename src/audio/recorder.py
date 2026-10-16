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
    Utiliza soxr com filtro anti-aliasing sinc de alta qualidade (HQ) para evitar
    dobramento espectral (aliasing), com fallback para interpolação se indisponível.
    """
    if len(audio) == 0:
        return np.zeros(0, dtype=np.int16)

    if orig_sr == target_sr:
        return audio

    try:
        import soxr
        resampled = soxr.resample(audio, orig_sr, target_sr, quality="HQ")
        if resampled.dtype != np.int16:
            resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
        return resampled
    except Exception:
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

        # Contadores de diagnóstico de overflow de fila
        self._dropped_mic_chunks: int = 0
        self._dropped_loop_chunks: int = 0

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

    def start(
        self,
        mic_device_id: Optional[int] = None,
        loopback_device_id: Optional[int] = None,
        mic_device_name: Optional[str] = None,
        loopback_device_name: Optional[str] = None,
    ):
        """Inicia a gravação dual e os fluxos assíncronos com suporte a dispositivos específicos."""
        if self._is_recording:
            logger.warning("Gravação já está em andamento.")
            return

        self.writer.open()
        self._is_recording = True
        self._is_paused = False
        self._start_time = time.time()
        self._pause_duration = 0.0

        # Limpa filas e reseta contadores de diagnóstico
        while not self._mic_queue.empty():
            self._mic_queue.get_nowait()
        while not self._loop_queue.empty():
            self._loop_queue.get_nowait()
        self._dropped_mic_chunks = 0
        self._dropped_loop_chunks = 0

        from src.audio.devices import get_device_by_index, get_device_by_name, get_default_devices

        # 1. Tenta resolver por nome (mais resiliente a reconexões USB/P3 e shifts de index)
        mic_dev = None
        if mic_device_name:
            mic_dev = get_device_by_name(mic_device_name, is_loopback=False)
            if not mic_dev:
                logger.warning("Microfone '%s' não encontrado pelo nome. Tentando índice...", mic_device_name)
        if not mic_dev and mic_device_id is not None:
            mic_dev = get_device_by_index(mic_device_id)

        loopback_dev = None
        if loopback_device_name:
            loopback_dev = get_device_by_name(loopback_device_name, is_loopback=True)
            if not loopback_dev:
                logger.warning("Dispositivo loopback '%s' não encontrado pelo nome. Tentando índice...", loopback_device_name)
        if not loopback_dev and loopback_device_id is not None:
            loopback_dev = get_device_by_index(loopback_device_id)

        # Fallback para os padrões caso não especificados ou inválidos
        if not mic_dev or not loopback_dev:
            defaults = get_default_devices()
            if not mic_dev:
                mic_dev = defaults.get("mic")
                logger.warning("Usando microfone padrão: %s", mic_dev.name if mic_dev else "Nenhum")
            if not loopback_dev:
                loopback_dev = defaults.get("loopback")
                logger.warning("Usando dispositivo loopback padrão: %s", loopback_dev.name if loopback_dev else "Nenhum")

        logger.info("Dispositivo Mic Selecionado: %s", mic_dev)
        logger.info("Dispositivo Loopback Selecionado: %s", loopback_dev)

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
                        self._dropped_mic_chunks += 1
                        if self._dropped_mic_chunks % 50 == 1:
                            logger.warning(
                                "Fila do Microfone cheia! Chunks descartados até agora: %d",
                                self._dropped_mic_chunks,
                            )
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
                        self._dropped_loop_chunks += 1
                        if self._dropped_loop_chunks % 50 == 1:
                            logger.warning(
                                "Fila do Loopback Teams cheia! Chunks descartados até agora: %d",
                                self._dropped_loop_chunks,
                            )
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
            self._writer_thread.join(timeout=5.0)

        saved_path = self.writer.close()
        self._mic_level = 0.0
        self._loopback_level = 0.0

        if self._dropped_mic_chunks > 0 or self._dropped_loop_chunks > 0:
            logger.warning(
                "Aviso de Gravação: Ocorreram descartes por buffer cheio (Mic: %d chunks, Teams: %d chunks).",
                self._dropped_mic_chunks,
                self._dropped_loop_chunks,
            )

        logger.info("Gravação finalizada. Arquivo salvo em: %s", saved_path)
        return saved_path

    def _writer_loop(self):
        """
        Consome dados das filas e escreve periodicamente no arquivo em disco.
        Utiliza sincronização por relógio de amostras real (wall-clock) para evitar drift
        cumulativo entre o microfone e o loopback quando um dos canais fica em silêncio.
        """
        chunk_target_len = int(self.sample_rate * 0.1)  # 1600 amostras (0.1s a 16kHz)
        silence_lag_tolerance = int(self.sample_rate * 0.25)  # 4000 amostras (0.25s)

        mic_buf = np.zeros(0, dtype=np.int16)
        loop_buf = np.zeros(0, dtype=np.int16)
        total_samples_written = 0

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

            # Sincronização temporal baseada em relógio de parede:
            # Se um dos canais parar de entregar pacotes (ex: WASAPI Loopback quando nada toca no Teams),
            # preenche apenas o atraso em relação ao relógio decorrido para evitar drift cumulativo.
            if self._is_recording and not self._is_paused:
                elapsed_sec = self.get_elapsed_seconds()
                expected_samples = int(elapsed_sec * self.sample_rate)

                # Preenche silêncio apenas se o canal estiver atrasado além da tolerância
                mic_lag = expected_samples - (total_samples_written + len(mic_buf))
                if mic_lag > silence_lag_tolerance:
                    silence_to_add = np.zeros(mic_lag, dtype=np.int16)
                    mic_buf = np.concatenate([mic_buf, silence_to_add]) if len(mic_buf) > 0 else silence_to_add

                loop_lag = expected_samples - (total_samples_written + len(loop_buf))
                if loop_lag > silence_lag_tolerance:
                    silence_to_add = np.zeros(loop_lag, dtype=np.int16)
                    loop_buf = np.concatenate([loop_buf, silence_to_add]) if len(loop_buf) > 0 else silence_to_add

            # Escreve o mínimo disponível em múltiplos de chunk_target_len
            min_len = min(len(mic_buf), len(loop_buf))
            if min_len >= chunk_target_len:
                write_len = (min_len // chunk_target_len) * chunk_target_len

                sub_mic = mic_buf[:write_len]
                sub_loop = loop_buf[:write_len]

                mic_buf = mic_buf[write_len:]
                loop_buf = loop_buf[write_len:]
                total_samples_written += write_len

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
                time.sleep(0.04)

        # Flush final após o término da gravação:
        # Se restaram amostras acumuladas em apenas um canal, alinha com silêncio e escreve
        final_len = max(len(mic_buf), len(loop_buf))
        if final_len > 0:
            if len(mic_buf) < final_len:
                mic_buf = np.pad(mic_buf, (0, final_len - len(mic_buf)))
            if len(loop_buf) < final_len:
                loop_buf = np.pad(loop_buf, (0, final_len - len(loop_buf)))

            stereo = np.empty((final_len, 2), dtype=np.int16)
            stereo[:, 0] = mic_buf
            stereo[:, 1] = loop_buf
            self.writer.write_chunk(stereo.tobytes())
