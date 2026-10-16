"""
Módulo de Configuração Central da Aplicação Ata Automática
Configurado com foco em estrito respeito ao orçamento de 4GB de RAM.
"""

from pathlib import Path

# Diretórios Base
ROOT_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = ROOT_DIR / "temp"
OUTPUT_DIR = ROOT_DIR / "output"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

# Prompt de Estilo e Glossário Técnico (Hotwords)
WHISPER_STYLE_PROMPT = (
    "Reunião corporativa no Microsoft Teams com ata executiva, decisões e plano de ação."
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

# Arquivos Padrão
DEFAULT_RECORDING_PATH = TEMP_DIR / "recording_dual.wav"
DEFAULT_TRANSCRIPT_PATH = TEMP_DIR / "transcript.json"
USER_CONFIG_PATH = ROOT_DIR / "config_user.json"


def get_user_settings() -> dict:
    """Carrega as preferências do usuário salvas no disco com fallback para os padrões."""
    import json
    defaults = {
        "mic_device_id": None,
        "mic_device_name": None,
        "loopback_device_id": None,
        "loopback_device_name": None,
        "model_profile": "auto",  # 'auto', 'large-v3-turbo', 'small', 'base'
        "corporate_glossary": DEFAULT_CORPORATE_GLOSSARY,
        "user_speaker_name": "Você",
    }
    if not USER_CONFIG_PATH.exists():
        return defaults
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            defaults.update(data)
            return defaults
    except Exception:
        return defaults


def save_user_settings(settings: dict) -> bool:
    """Salva as preferências do usuário no arquivo config_user.json."""
    import json
    try:
        current = get_user_settings()
        current.update(settings)
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
