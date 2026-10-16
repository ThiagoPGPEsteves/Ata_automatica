"""
Fixtures compartilhadas para a suíte de testes do Pytest (Fase P5)
"""

import sys
from pathlib import Path
import numpy as np
import pytest

# Garante a raiz do projeto no sys.path para importações relativas e absolutas
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture
def sample_audio_mono_16k() -> np.ndarray:
    """Gera 2 segundos de áudio mono a 16 kHz com sinal senoidal simulando voz (300 Hz)."""
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Sinal senoidal a 300 Hz com amplitude moderada
    audio = (0.25 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    return audio


@pytest.fixture
def sample_silence_16k() -> np.ndarray:
    """Gera 2 segundos de silêncio absoluto mono a 16 kHz."""
    sr = 16000
    duration = 2.0
    return np.zeros(int(sr * duration), dtype=np.float32)


@pytest.fixture
def sample_audio_dual_16k() -> tuple[np.ndarray, np.ndarray]:
    """
    Gera um par estéreo (canal 0 = microfone / canal 1 = loopback) de 3 segundos a 16 kHz.
    Canal 0 tem fala no primeiro segundo; Canal 1 tem fala no segundo segundo.
    """
    sr = 16000
    n = sr * 3
    mic = np.zeros(n, dtype=np.float32)
    loop = np.zeros(n, dtype=np.float32)

    t1 = np.linspace(0, 1.0, sr, endpoint=False)
    mic[:sr] = 0.2 * np.sin(2 * np.pi * 250 * t1)

    t2 = np.linspace(0, 1.0, sr, endpoint=False)
    loop[sr : 2 * sr] = 0.2 * np.sin(2 * np.pi * 350 * t2)

    return mic, loop


@pytest.fixture
def sample_markdown_minutes() -> str:
    """Retorna uma ata estruturada de exemplo em formato Markdown."""
    return (
        "# ATA DE REUNIÃO: Alinhamento de Sprint e Arquitetura\n\n"
        "**Data:** 16/10/2026\n"
        "**Duração:** 00:30:00\n"
        "**Participantes:** Thiago, Daniel, Cássio, Bastian\n\n"
        "## Resumo Executivo\n"
        "Reunião de alinhamento técnico para homologação da Fase P5 de Engenharia de Qualidade.\n\n"
        "## Pautas Discutidas\n"
        "- Padronização dos testes com pytest e marcadores.\n"
        "- Implementação nativa de cálculo de WER e Levenshtein.\n"
        "- Validação de resiliência a jitter de áudio.\n\n"
        "## Decisões Tomadas\n"
        "- [05:12] Decidido manter o cálculo de WER sem bibliotecas binárias externas.\n"
        "- [12:30] Aprovado o uso de marcadores 'unit' para testes ultrarrápidos no CI.\n\n"
        "## Tabela de Ações\n"
        "| Ação | Responsável | Prazo |\n"
        "|---|---|---|\n"
        "| Implementar módulo text_metrics.py | Thiago | 17/10/2026 |\n"
        "| Executar benchmark com corpus real | Daniel | 18/10/2026 |\n\n"
        "## Próximos Passos\n"
        "Validar cobertura e homologar documentação no README.md."
    )


@pytest.fixture
def mock_meeting_minutes_dict() -> dict:
    """Retorna dicionário de dados da ata compatível com dataclass MeetingMinutes."""
    return {
        "title": "Alinhamento de Sprint e Arquitetura",
        "date": "16/10/2026",
        "duration": "00:30:00",
        "participants": ["Thiago", "Daniel", "Cássio", "Bastian"],
        "executive_summary": "Reunião de alinhamento técnico para homologação da Fase P5.",
        "agenda_topics": [
            "Padronização dos testes com pytest",
            "Métricas de WER",
            "Resiliência de áudio",
        ],
        "decisions": [
            "Decidido manter o cálculo de WER sem bibliotecas externas",
            "Aprovado o uso de marcadores unit",
        ],
        "action_items": [
            {
                "action": "Implementar módulo text_metrics.py",
                "owner": "Thiago",
                "deadline": "17/10/2026",
                "evidence_ts": "05:12",
            },
            {
                "action": "Executar benchmark com corpus real",
                "owner": "Daniel",
                "deadline": "18/10/2026",
                "evidence_ts": "12:30",
            },
        ],
        "next_steps": ["Validar cobertura e homologar documentação no README.md."],
        "raw_transcript_summary": "Transcrição resumida de alinhamento.",
    }
