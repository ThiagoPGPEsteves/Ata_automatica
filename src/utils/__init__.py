"""
Pacote de Utilitários de Telemetria e Diagnóstico
"""

from src.utils.telemetry import (
    SystemMemoryAuditor,
    RTFEstimator,
    has_speech_activity,
    format_duration,
)
from src.utils.text_metrics import (
    normalize_portuguese_text,
    levenshtein_distance,
    compute_wer,
    compute_cer,
    format_alignment_diff,
)

__all__ = [
    "SystemMemoryAuditor",
    "RTFEstimator",
    "has_speech_activity",
    "format_duration",
    "normalize_portuguese_text",
    "levenshtein_distance",
    "compute_wer",
    "compute_cer",
    "format_alignment_diff",
]
