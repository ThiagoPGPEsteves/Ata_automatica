"""
Módulo de Detecção e Enumeração de Dispositivos de Áudio (WASAPI no Windows)
Identifica o Microfone Padrão e o Dispositivo de Saída em modo Loopback (áudio do Teams).
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class AudioDeviceInfo:
    id: Any
    name: str
    is_input: bool
    is_loopback: bool
    sample_rate: int
    channels: int
    backend: str  # "pyaudiowpatch" ou "soundcard"


def list_pyaudio_devices() -> Dict[str, Any]:
    """Lista dispositivos usando PyAudioWPatch com suporte nativo a WASAPI Loopback."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        logger.warning("pyaudiowpatch não está instalado.")
        return {"mic": None, "loopback": None}

    p = pyaudio.PyAudio()
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except Exception as e:
        logger.warning("WASAPI Host API não disponível no PyAudio: %s", e)
        p.terminate()
        return {"mic": None, "loopback": None}

    # Microfone padrão do host WASAPI
    default_input_idx = wasapi_info.get("defaultInputDevice")
    mic_info = None
    if default_input_idx is not None and default_input_idx >= 0:
        info = p.get_device_info_by_index(default_input_idx)
        mic_info = AudioDeviceInfo(
            id=info["index"],
            name=info["name"],
            is_input=True,
            is_loopback=False,
            sample_rate=int(info.get("defaultSampleRate", 16000)),
            channels=int(info.get("maxInputChannels", 1)),
            backend="pyaudiowpatch",
        )

    # Dispositivo padrão de saída para encontrar o par de loopback
    default_output_idx = wasapi_info.get("defaultOutputDevice")
    loopback_info = None
    if default_output_idx is not None and default_output_idx >= 0:
        default_speaker = p.get_device_info_by_index(default_output_idx)
        speaker_name = default_speaker["name"]

        # Busca o dispositivo de loopback correspondente ao alto-falante padrão
        try:
            for dev in p.get_loopback_device_info_generator():
                if speaker_name in dev["name"]:
                    loopback_info = AudioDeviceInfo(
                        id=dev["index"],
                        name=dev["name"],
                        is_input=True,
                        is_loopback=True,
                        sample_rate=int(dev.get("defaultSampleRate", 48000)),
                        channels=int(dev.get("maxInputChannels", 2)),
                        backend="pyaudiowpatch",
                    )
                    break
        except Exception as e:
            logger.warning("Erro ao enumerar dispositivos loopback: %s", e)

    p.terminate()
    return {"mic": mic_info, "loopback": loopback_info}


def list_available_inputs() -> List[AudioDeviceInfo]:
    """Retorna lista de todos os microfones físicos válidos detectados pelo WASAPI / PyAudio."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []

    p = pyaudio.PyAudio()
    devices: List[AudioDeviceInfo] = []
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        w_idx = wasapi_info["index"]

        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d.get("hostApi") == w_idx:
                is_loop = d.get("isLoopbackDevice", False)
                if d.get("maxInputChannels", 0) > 0 and not is_loop:
                    devices.append(
                        AudioDeviceInfo(
                            id=d["index"],
                            name=d["name"],
                            is_input=True,
                            is_loopback=False,
                            sample_rate=int(d.get("defaultSampleRate", 16000)),
                            channels=int(d.get("maxInputChannels", 1)),
                            backend="pyaudiowpatch",
                        )
                    )
    except Exception as e:
        logger.warning("Erro ao listar microfones WASAPI: %s", e)
    finally:
        p.terminate()

    return devices


def list_available_outputs_loopback() -> List[AudioDeviceInfo]:
    """Retorna lista de todos os dispositivos de saída (alto-falantes/fones) com suporte a Loopback."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []

    p = pyaudio.PyAudio()
    devices: List[AudioDeviceInfo] = []
    try:
        for dev in p.get_loopback_device_info_generator():
            devices.append(
                AudioDeviceInfo(
                    id=dev["index"],
                    name=dev["name"],
                    is_input=True,
                    is_loopback=True,
                    sample_rate=int(dev.get("defaultSampleRate", 48000)),
                    channels=int(dev.get("maxInputChannels", 2)),
                    backend="pyaudiowpatch",
                )
            )
    except Exception as e:
        logger.warning("Erro ao listar saídas loopback: %s", e)
    finally:
        p.terminate()

    return devices


def get_device_by_index(index: int) -> Optional[AudioDeviceInfo]:
    """Recupera informações detalhadas de um dispositivo de áudio pelo seu índice PyAudio."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return None

    p = pyaudio.PyAudio()
    try:
        if 0 <= index < p.get_device_count():
            d = p.get_device_info_by_index(index)
            is_loop = d.get("isLoopbackDevice", False)
            return AudioDeviceInfo(
                id=d["index"],
                name=d["name"],
                is_input=d.get("maxInputChannels", 0) > 0,
                is_loopback=is_loop,
                sample_rate=int(d.get("defaultSampleRate", 16000)),
                channels=int(d.get("maxInputChannels", 1) or d.get("maxOutputChannels", 2)),
                backend="pyaudiowpatch",
            )
    except Exception as e:
        logger.warning("Erro ao obter dispositivo index %d: %s", index, e)
    finally:
        p.terminate()

    return None


def get_default_devices() -> Dict[str, Optional[AudioDeviceInfo]]:
    """
    Retorna os melhores dispositivos padrão para gravação da reunião:
    - mic: Microfone para capturar o usuário
    - loopback: Saída de som para capturar os outros participantes do Teams
    """
    devices = list_pyaudio_devices()
    if devices.get("mic") and devices.get("loopback"):
        return devices

    # Fallback usando soundcard se pyaudio não encontrar ambos
    try:
        import soundcard as sc

        default_mic = sc.default_microphone()
        default_spk = sc.default_speaker()
        loopback_spk = sc.get_microphone(id=str(default_spk.name), include_loopback=True)

        if not devices.get("mic") and default_mic:
            devices["mic"] = AudioDeviceInfo(
                id=default_mic.name,
                name=default_mic.name,
                is_input=True,
                is_loopback=False,
                sample_rate=16000,
                channels=1,
                backend="soundcard",
            )

        if not devices.get("loopback") and loopback_spk:
            devices["loopback"] = AudioDeviceInfo(
                id=loopback_spk.name,
                name=loopback_spk.name,
                is_input=True,
                is_loopback=True,
                sample_rate=48000,
                channels=2,
                backend="soundcard",
            )
    except Exception as e:
        logger.warning("Falha no fallback soundcard: %s", e)

    return devices
