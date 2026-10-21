"""
Módulo de Transcrição de Áudio (Speech-to-Text) com faster-whisper
Otimizado para execução em CPU com quantização int8 e descarregamento ativo de RAM.
"""

from src.transcription.whisper_engine import WhisperEngine
from src.transcription.post_process import (
    split_dual_channel_audio,
    merge_channel_transcripts,
    format_transcript_dialogue,
    clean_text_tokens,
    filter_acoustic_echo_segments,
    ACOUSTIC_STOPWORDS,
)

__all__ = [
    "WhisperEngine",
    "split_dual_channel_audio",
    "merge_channel_transcripts",
    "format_transcript_dialogue",
    "clean_text_tokens",
    "filter_acoustic_echo_segments",
    "ACOUSTIC_STOPWORDS",
]
