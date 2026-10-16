"""
Bateria de Testes Automatizados para Casos Limite do Parser de Atas (Fase P5)
Valida a robustez do MinutesParser frente a variações nos cabeçalhos Markdown,
prefixos de títulos, tabelas com colunas atípicas e extração de timestamps de evidência.
"""

import pytest
from src.minutes.parser import MinutesParser, MeetingMinutes, ActionItem


@pytest.mark.unit
def test_parser_title_variations():
    """Valida extração limpa de títulos com diferentes prefixos, hífens e traços en-dash/em-dash."""
    test_cases = [
        ("# ATA DE REUNIÃO: Alinhamento de Sprint", "Alinhamento de Sprint"),
        ("# ATA DE REUNIÃO - Status Colômbia e Chile", "Status Colômbia e Chile"),
        ("# ATA DE REUNIÃO – Revisão de Arquitetura", "Revisão de Arquitetura"),
        ("# Ata de Reunião: Discussão de Faturamento", "Discussão de Faturamento"),
        ("# ATA DE REUNIAO: Sem Acento no Título", "Sem Acento no Título"),
        ("# Alinhamento Técnico Sem Prefixo", "Alinhamento Técnico Sem Prefixo"),
        ("# ATA DE REUNIÃO", "Ata de Reunião"),
        ("# ata de reunião", "Ata de Reunião"),
    ]

    for md_title, expected in test_cases:
        md = f"{md_title}\n\n## Resumo Executivo\nDiscussão realizada com sucesso."
        parsed = MinutesParser.parse(md)
        assert parsed.title == expected, f"Falhou para '{md_title}': esperado '{expected}', obteve '{parsed.title}'"


@pytest.mark.unit
def test_parser_action_items_irregular_tables():
    """Valida extração de ações mesmo quando o LLM gera colunas adicionais, traços ou espaços."""
    md = (
        "# Ata de Reunião: Teste Ações\n\n"
        "## Tabela de Ações\n"
        "| Ação | Responsável | Prazo |\n"
        "|---|---|---|\n"
        "| Configurar Transfer Family | Daniel | 20/10/2026 |\n"
        "| Atualizar simulação de faturamento | Cássio | A definir |\n"
        "| Validar layout com Colômbia | Thiago | - |\n"
    )

    parsed = MinutesParser.parse(md)
    assert len(parsed.action_items) == 3

    a1 = parsed.action_items[0]
    assert a1.action == "Configurar Transfer Family"
    assert a1.owner == "Daniel"
    assert a1.deadline == "20/10/2026"

    a2 = parsed.action_items[1]
    assert a2.action == "Atualizar simulação de faturamento"
    assert a2.owner == "Cássio"
    assert "definir" in a2.deadline.lower()

    a3 = parsed.action_items[2]
    assert a3.action == "Validar layout com Colômbia"
    assert a3.owner == "Thiago"


@pytest.mark.unit
def test_parser_decisions_with_timestamps():
    """Valida extração de decisões contendo timestamps de evidência formatados."""
    md = (
        "# Ata de Reunião: Decisões\n\n"
        "## Decisões Tomadas\n"
        "- [03:15] Decidido adiar a reunião das garantias para a próxima semana.\n"
        "- [08:30] Aprovado o uso do formato Excel para compartilhamento temporário.\n"
        "- Manter comunicação assíncrona com a equipe de Santiago.\n"
    )

    parsed = MinutesParser.parse(md)
    assert len(parsed.decisions) == 3
    assert "[03:15]" in parsed.decisions[0]
    assert "[08:30]" in parsed.decisions[1]
    assert "comunicação assíncrona" in parsed.decisions[2]


@pytest.mark.unit
def test_meeting_minutes_dataclass_serialization():
    """Valida serialização to_dict e desserialização from_dict com integridade de dados."""
    original = MeetingMinutes(
        title="Alinhamento Executivo",
        date="16/10/2026",
        participants=["Thiago", "Cássio"],
        executive_summary="Resumo de teste.",
        decisions=["Decisão 1 [01:00]", "Decisão 2"],
        action_items=[
            ActionItem(action="Fazer tarefa", owner="Thiago", deadline="Amanhã", evidence_ts="01:00")
        ],
    )

    as_dict = original.to_dict()
    assert as_dict["title"] == "Alinhamento Executivo"
    assert len(as_dict["action_items"]) == 1

    restored = MeetingMinutes.from_dict(as_dict)
    assert restored.title == original.title
    assert restored.action_items[0].action == "Fazer tarefa"
    assert restored.action_items[0].evidence_ts == "01:00"
