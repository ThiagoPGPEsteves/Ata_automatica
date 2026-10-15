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
MIN_FREE_RAM_FOR_SMALL_MODEL_MB = 1500  # Se tiver < 1.5GB livre, faz fallback para whisper 'base'

# Configurações de Transcrição (faster-whisper)
WHISPER_DEFAULT_MODEL = "small"
WHISPER_FALLBACK_MODEL = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_CPU_THREADS = 4
WHISPER_LANGUAGE = "pt"

# Configurações de IA (Ollama Local)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_TIMEOUT = 300.0  # 5 minutos de tolerância para reuniões longas em CPU
OLLAMA_KEEP_ALIVE = "0s"  # Descarrega o modelo da RAM imediatamente após a geração

# Arquivos Padrão
DEFAULT_RECORDING_PATH = TEMP_DIR / "recording_dual.wav"
DEFAULT_TRANSCRIPT_PATH = TEMP_DIR / "transcript.json"
