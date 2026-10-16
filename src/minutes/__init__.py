"""
Módulo de Geração e Estruturação de Atas de Reunião com Ollama
"""

from src.minutes.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
)
from src.minutes.prompts import generate_meeting_minutes_prompt, SYSTEM_PROMPT
from src.minutes.parser import MinutesParser, MeetingMinutes, ActionItem
from src.minutes.generator import MinutesGenerator

__all__ = [
    "OllamaClient",
    "OllamaConnectionError",
    "OllamaModelNotFoundError",
    "generate_meeting_minutes_prompt",
    "SYSTEM_PROMPT",
    "MinutesParser",
    "MeetingMinutes",
    "ActionItem",
    "MinutesGenerator",
]
