"""
Módulo de Configuração Central da Aplicação Ata Automática
Configurado com foco em estrito respeito ao orçamento de 4GB de RAM.
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Union

logger = logging.getLogger(__name__)


# Diretórios Base
ROOT_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = ROOT_DIR / "temp"
OUTPUT_DIR = ROOT_DIR / "output"
SESSIONS_DIR = ROOT_DIR / "sessions"
LOGS_DIR = ROOT_DIR / "logs"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configurações de Áudio
# 16.000 Hz é a taxa nativa utilizada pelo Whisper, economizando memória e CPU
SAMPLE_RATE = 16000
CHANNELS = 2  # Canal 0 (Esq): Microfone Local | Canal 1 (Dir): Saída Teams/Loopback
SAMPLE_WIDTH = 2  # 16-bit PCM (2 bytes por amostra)
CHUNK_DURATION_SEC = 1.0  # Gravação em streaming a cada 1 segundo direto para disco
AUDIO_FORMAT = "wav"

# Limites e Orçamento Estrito de Memória (RAM)
MAX_RAM_ALLOWED_MB = 4096  # Teto máximo estrito de 4.0 GB
MIN_FREE_RAM_FOR_TURBO_MODEL_MB = 2000  # Se tiver >= 2.0GB livres, usa 'large-v3-turbo'
MIN_FREE_RAM_FOR_SMALL_MODEL_MB = 1200  # Se tiver < 2.0GB mas >= 1.2GB livres, usa 'small'

# Modelos Suportados de Transcrição (faster-whisper)
WHISPER_TURBO_MODEL = "large-v3-turbo"
WHISPER_SMALL_MODEL = "small"
WHISPER_BASE_MODEL = "base"
WHISPER_DEFAULT_MODEL = "large-v3-turbo"
WHISPER_FALLBACK_MODEL = "small"

WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_CPU_THREADS = 4
WHISPER_LANGUAGE = "pt"

# Parâmetros Avançados Anti-Repetição / Anti-Alucinação
WHISPER_CONDITION_ON_PREVIOUS_TEXT = False
WHISPER_REPETITION_PENALTY = 1.0   # Default Whisper (1.0 = neutro; evita substituição indevida de vocábulos)
WHISPER_NO_REPEAT_NGRAM_SIZE = 0   # 0 = desativado (evita proibir locuções legítimas como "de acordo com")
WHISPER_BEAM_SIZE = 3

# Filtros de Áudio DSP
AUDIO_DSP_ENABLED = False  # Desativado por padrão: evita corte inadvertido da fundamental da voz (80-300Hz)
AUDIO_HIGHPASS_CUTOFF_HZ = 80.0
AUDIO_PEAK_NORMALIZE = 0.95

# EchoGate: Supressão Inteligente de Eco e Vazamento no Sinal (Fase P3)
AUDIO_ECHOGATE_ENABLED = True
ECHOGATE_MIN_CORRELATION = 0.30       # Limiar mínimo de correlação cruzada para ativar o gate
ECHOGATE_FRAME_MS = 25.0             # Tamanho da janela de análise em milissegundos
ECHOGATE_MAX_DELAY_MS = 300.0        # Janela máxima de busca de atraso físico mic x loopback
ECHOGATE_SUPPRESSION_DB = -40.0      # Nível de atenuação de quadros de vazamento acústico/elétrico
ECHOGATE_DOUBLE_TALK_MARGIN_DB = 6.0 # Margem de energia para preservar voz do usuário em falas simultâneas

# Prompt de Estilo e Glossário Técnico (Hotwords)
WHISPER_STYLE_PROMPT = (
    "Reunião corporativa no Microsoft Teams, participantes em português e espanhol, discussões e alinhamentos de negócios."
)
DEFAULT_CORPORATE_GLOSSARY = (
    "CCP, Contraparte Central, Colômbia, PJ, B3, Compliance, Ptax, Liquidação, Ponderação"
)

# Configurações de IA (Ollama Local)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_TIMEOUT = 300.0  # 5 minutos de tolerância para reuniões longas em CPU
OLLAMA_KEEP_ALIVE = "0s"  # Descarrega o modelo da RAM imediatamente após a geração
OLLAMA_NUM_CTX = 4096     # Janela explícita de contexto (evita truncamento silencioso de transcrições longas)

# Formatos de Saída Suportados
OUTPUT_FORMAT_MINUTES = "minutes"
OUTPUT_FORMAT_THEME_SUMMARY = "theme_summary"

# Arquivos Padrão
DEFAULT_RECORDING_PATH = TEMP_DIR / "recording_dual.wav"
DEFAULT_TRANSCRIPT_PATH = TEMP_DIR / "transcript.json"
USER_CONFIG_PATH = ROOT_DIR / "config_user.json"


@dataclass
class UserSettings:
    """Configurações do usuário tipadas com suporte a versionamento de schema."""
    schema_version: int = 1
    mic_device_id: Optional[int] = None
    mic_device_name: Optional[str] = None
    loopback_device_id: Optional[int] = None
    loopback_device_name: Optional[str] = None
    model_profile: str = "auto"
    corporate_glossary: str = DEFAULT_CORPORATE_GLOSSARY
    user_speaker_name: str = "Você"
    audio_retention_days: int = 7
    echo_gate_enabled: bool = True
    output_format: str = OUTPUT_FORMAT_MINUTES  # "minutes" | "theme_summary"
    transcription_language: str = "auto"       # "auto" | "pt" | "es"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserSettings":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            mic_device_id=data.get("mic_device_id"),
            mic_device_name=data.get("mic_device_name"),
            loopback_device_id=data.get("loopback_device_id"),
            loopback_device_name=data.get("loopback_device_name"),
            model_profile=str(data.get("model_profile", "auto")),
            corporate_glossary=str(data.get("corporate_glossary", DEFAULT_CORPORATE_GLOSSARY)),
            user_speaker_name=str(data.get("user_speaker_name", "Você")),
            audio_retention_days=int(data.get("audio_retention_days", 7)),
            echo_gate_enabled=bool(data.get("echo_gate_enabled", True)),
            output_format=str(data.get("output_format", OUTPUT_FORMAT_MINUTES)),
            transcription_language=str(data.get("transcription_language", "auto")),
        )


def get_typed_user_settings() -> UserSettings:
    """Retorna as configurações do usuário como instância tipada de UserSettings."""
    default_obj = UserSettings()
    if not USER_CONFIG_PATH.exists():
        return default_obj
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return UserSettings.from_dict(data)
    except Exception as e:
        logger.warning("Falha ao ler %s (%s). Usando configurações padrão.", USER_CONFIG_PATH, e)
        return default_obj


def get_user_settings() -> dict:
    """Carrega as preferências do usuário como dicionário (retrocompatível com todo o código existente)."""
    return get_typed_user_settings().to_dict()


def save_user_settings(settings: Union[dict, UserSettings]) -> bool:
    """Salva as preferências do usuário de forma atômica no arquivo config_user.json."""
    try:
        current_dict = get_user_settings()
        if isinstance(settings, UserSettings):
            new_data = settings.to_dict()
        else:
            new_data = dict(settings)

        current_dict.update(new_data)
        # Garante schema_version
        if "schema_version" not in current_dict:
            current_dict["schema_version"] = 1

        target_dir = USER_CONFIG_PATH.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_fd, temp_path = tempfile.mkstemp(
            dir=str(target_dir),
            prefix="config_user_",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(current_dict, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, USER_CONFIG_PATH)
            return True
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise
    except Exception as e:
        logger.warning("Falha ao salvar configurações em %s (%s).", USER_CONFIG_PATH, e)
        return False
