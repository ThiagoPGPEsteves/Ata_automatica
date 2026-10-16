"""
Testes Automatizados para a Fase P1:
- MinutesGenerator (Map-Reduce e Single-Pass estruturado)
- Schemas JSON e parsing direto para dataclass MeetingMinutes
- Particionamento inteligente de transcrições longas sem truncamento
- Rastreabilidade de minutagem (evidence_ts) e fallbacks resilientes
"""

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# Garante raiz do projeto no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.minutes.generator import (
    MinutesGenerator,
    partition_transcript,
    minutes_to_markdown,
    CHUNK_NOTES_SCHEMA,
    MEETING_MINUTES_SCHEMA,
)
from src.minutes.parser import MeetingMinutes, ActionItem


def test_partition_transcript_short():
    """Valida que reuniões curtas não são divididas."""
    short_text = (
        "[00:00:05] [Thiago]: Bom dia equipe.\n"
        "[00:00:15] [Participantes]: Bom dia, pauta revisada."
    )
    chunks = partition_transcript(short_text, max_chunk_chars=5000)
    assert len(chunks) == 1
    assert chunks[0] == short_text


def test_partition_transcript_long():
    """Valida divisão em blocos respeitando as quebras de linha."""
    # Cria transcrição longa com 100 linhas
    lines = [f"[{i:02d}:00:00] [Thiago]: Ponto de alinhamento número {i} com detalhes sobre arquitetura e prazos." for i in range(50)]
    long_text = "\n".join(lines)

    chunks = partition_transcript(long_text, max_chunk_chars=1200)
    assert len(chunks) > 1
    # Verifica que nenhuma fala foi cortada ao meio
    for ch in chunks:
        assert ch.startswith("[")
        assert not ch.endswith("[Thiago")


def test_single_pass_structured_json():
    """Valida geração estruturada em passo único com JSON Schema."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True

    sample_json = {
        "title": "Alinhamento Estratégico de Crédito e CCPs",
        "date": "16/10/2026",
        "participants": ["Thiago Esteves", "Equipe de Risco"],
        "executive_summary": "Reunião de alinhamento com foco na segregação de contrapartes centrais na Colômbia.",
        "topics": [
            {"topic": "Exposição Colômbia", "details": "Identificado catálogo de exposições com contrapartes."}
        ],
        "decisions": [
            {"decision": "Classificar contrapartes centrais sob regra específica", "evidence_ts": "02:16"}
        ],
        "action_items": [
            {"action": "Ajustar cadastro de PJ", "owner": "Thiago Esteves", "deadline": "20/10/2026", "evidence_ts": "02:25"}
        ],
        "next_steps": ["Validar relatório com compliance"]
    }

    mock_client.generate.return_value = json.dumps(sample_json, ensure_ascii=False)

    generator = MinutesGenerator(ollama_client=mock_client)
    minutes, raw_md = generator.generate(
        transcript_text="[00:01:00] [Thiago]: Breve reunião...",
        meeting_date="16/10/2026",
        user_speaker_name="Thiago Esteves",
    )

    assert isinstance(minutes, MeetingMinutes)
    assert minutes.title == "Alinhamento Estratégico de Crédito e CCPs"
    assert len(minutes.decisions) == 1
    assert "02:16" in minutes.decisions[0]
    assert len(minutes.action_items) == 1
    assert minutes.action_items[0].owner == "Thiago Esteves"
    assert minutes.action_items[0].evidence_ts == "02:25"
    assert "02:25" in raw_md
    assert mock_client.generate.called


def test_map_reduce_long_meeting():
    """Valida o ciclo completo de Map-Reduce para reuniões com múltiplos blocos."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True

    # Cria texto sintético longo que força particionamento
    speech_turns = [
        f"[{i:02d}:00:00] [Thiago]: Discussão importante do bloco {i} com deliberações e tarefas associadas."
        for i in range(120)
    ]
    long_transcript = "\n".join(speech_turns)

    # Mock das chamadas:
    # As primeiras chamadas são para o Map (retornam CHUNK_NOTES_SCHEMA)
    map_response = json.dumps({
        "topics": [{"topic": "Tópico de Bloco", "details": "Detalhe de bloco"}],
        "decisions": [{"decision": "Decisão parcial", "evidence_ts": "05:10"}],
        "action_items": [{"action": "Ação de bloco", "owner": "Thiago", "deadline": "Amanhã", "evidence_ts": "05:30"}],
        "highlights": ["Destaque de teste"],
    })

    # A chamada final é para o Reduce (retorna MEETING_MINUTES_SCHEMA)
    reduce_response = json.dumps({
        "title": "Ata Consolidada Map-Reduce",
        "date": "16/10/2026",
        "participants": ["Thiago", "Participantes da Reunião"],
        "executive_summary": "Resumo integrado e consolidado de todos os blocos cronológicos.",
        "topics": [{"topic": "Tópico Consolidado", "details": "Visão geral integrada."}],
        "decisions": [{"decision": "Decisão Final Integrada", "evidence_ts": "05:10"}],
        "action_items": [
            {"action": "Ação Consolidada", "owner": "Thiago", "deadline": "Amanhã", "evidence_ts": "05:30"}
        ],
        "next_steps": ["Próximo passo final"],
    })

    call_count = 0

    def mock_generate_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        # Se for a chamada de reduce (response_format == MEETING_MINUTES_SCHEMA)
        if kwargs.get("response_format") == MEETING_MINUTES_SCHEMA:
            return reduce_response
        return map_response

    mock_client.generate.side_effect = mock_generate_side_effect

    progress_events = []

    def on_progress(desc, pct):
        progress_events.append((desc, pct))

    generator = MinutesGenerator(ollama_client=mock_client)
    minutes, raw_md = generator.generate(
        transcript_text=long_transcript,
        meeting_title="Título Sugerido",
        meeting_date="16/10/2026",
        user_speaker_name="Thiago",
        progress_callback=on_progress,
    )

    assert call_count > 1, "Deveria ter executado chamadas de Map e uma de Reduce"
    assert minutes.title == "Ata Consolidada Map-Reduce"
    assert len(minutes.action_items) == 1
    assert minutes.action_items[0].evidence_ts == "05:30"
    assert len(progress_events) >= 2


def test_generator_fallback_on_ollama_json_error():
    """Valida fallback resiliente caso o Ollama retorne texto Markdown ao invés de JSON."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True

    # Simula resposta em Markdown puro
    mock_client.generate.return_value = """# ATA DE REUNIÃO: Reunião de Fallback

## 1. Informações Gerais
- Data: 16/10/2026

## 2. Resumo Executivo
Resumo em Markdown puro após falha de JSON.

## 4. Decisões Tomadas
- Deliberação de contingência [01:45]

## 5. Plano de Ação
| Ação | Responsável | Prazo |
|---|---|---|
| Ação de contingência [01:50] | Thiago | Imediato |
"""

    generator = MinutesGenerator(ollama_client=mock_client)
    minutes, raw_md = generator.generate(
        transcript_text="[00:01:00] [Thiago]: Reunião de teste.",
        user_speaker_name="Thiago",
    )

    assert isinstance(minutes, MeetingMinutes)
    assert "Fallback" in minutes.title
    assert len(minutes.decisions) >= 1
    assert len(minutes.action_items) >= 1
    assert minutes.action_items[0].evidence_ts == "01:50"


if __name__ == "__main__":
    test_partition_transcript_short()
    test_partition_transcript_long()
    test_single_pass_structured_json()
    test_map_reduce_long_meeting()
    test_generator_fallback_on_ollama_json_error()
    print("\nTODOS OS TESTES DO MINUTES GENERATOR FORAM APROVADOS COM SUCESSO!")
