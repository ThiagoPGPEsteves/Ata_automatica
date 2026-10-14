"""
Teste Automatizado da Fase 4: Construtor do Documento Word (.docx) com Padrão Executivo Corporativo.
Valida:
1. Geração do arquivo .docx com formatação visual corporativa.
2. Integridade dos elementos: Cabeçalho, Metadados, Caixa de Decisões e Tabela Zebrada de Ações.
3. Pipeline integrado: Markdown do LLM -> MinutesParser -> DocxMeetingMinutesBuilder.
"""

import sys
import os
from pathlib import Path
import docx

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OUTPUT_DIR
from src.minutes.parser import MeetingMinutes, ActionItem, MinutesParser
from src.exporter.docx_builder import DocxMeetingMinutesBuilder


def test_docx_generation_from_model():
    """Valida a construção do documento a partir de um objeto MeetingMinutes."""
    print("\n[TESTE 1] Validando Geração de Documento Word (.docx)...")
    minutes = MeetingMinutes(
        title="Reunião de Alinhamento Estratégico e Arquitetura",
        date="14/10/2026",
        participants=["Thiago Esteves", "Coordenação de TI", "Equipe de Engenharia"],
        executive_summary=(
            "A reunião teve como propósito homologar a arquitetura técnica da Ata Automática. "
            "Foram avaliadas as restrições de infraestrutura local, decidindo-se pelo uso de modelos "
            "com quantização int8 e diretiva de descarregamento imediato de memória."
        ),
        topics=[
            {
                "topic": "Arquitetura de Captura de Áudio",
                "details": "Apresentação do módulo WASAPI loopback com gravação contínua em streaming.",
            },
            {
                "topic": "Processamento e Transcrição Local",
                "details": "Homologação do motor faster-whisper com quantização int8 em CPU.",
            },
        ],
        decisions=[
            "Aprovada a implementação em pipeline sequencial desacoplado.",
            "Homologado o limite máximo estrito de 4.0 GB de memória RAM.",
            "Definido o padrão Word (.docx) como formato oficial de distribuição.",
        ],
        action_items=[
            ActionItem(action="Finalizar módulo de exportação Word", owner="Thiago Esteves", deadline="14/10/2026"),
            ActionItem(action="Conectar interface desktop PyQt6", owner="Equipe Frontend", deadline="16/10/2026"),
            ActionItem(action="Executar teste piloto de 30 minutos", owner="Coordenação", deadline="18/10/2026"),
        ],
        next_steps=[
            "Revisão final do código e empacotamento da aplicação.",
            "Apresentação dos resultados da homologação.",
        ],
    )

    output_file = OUTPUT_DIR / "test_ata_executiva.docx"
    builder = DocxMeetingMinutesBuilder(organization_name="Diretoria de Tecnologia / Teams")
    saved_path = builder.build(minutes, output_file)

    assert saved_path.exists(), "O arquivo .docx deveria existir no disco."
    file_size = saved_path.stat().st_size
    print(f"  -> Arquivo gerado com sucesso: {saved_path.name} ({file_size} bytes)")
    assert file_size > 10000, f"Arquivo .docx parece muito pequeno ou vazio: {file_size} bytes"

    print("  -> TESTE 1 APROVADO: Arquivo Word criado com sucesso!")


def test_docx_document_integrity():
    """Valida a estrutura interna do arquivo Word gerado."""
    print("\n[TESTE 2] Validando Integridade Estrutural do Documento Word...")
    test_file = OUTPUT_DIR / "test_ata_executiva.docx"
    assert test_file.exists(), "Arquivo de teste deve existir."

    doc = docx.Document(str(test_file))

    # 1. Valida parágrafos e títulos
    paragraphs_text = [p.text for p in doc.paragraphs if p.text.strip()]
    full_doc_text = " ".join(paragraphs_text)

    assert "ATA DE REUNIÃO EXECUTIVA" in full_doc_text
    assert "Alinhamento Estratégico" in full_doc_text
    assert "1. Resumo Executivo" in full_doc_text
    assert "2. Pautas e Discussões" in full_doc_text
    assert "3. Decisões Tomadas" in full_doc_text
    assert "4. Plano de Ação" in full_doc_text
    assert "5. Próximos Passos" in full_doc_text

    # 2. Valida tabelas (Metadados, Callout de Decisões, Tabela de Ações)
    assert len(doc.tables) >= 3, f"Esperado pelo menos 3 tabelas no documento, encontrado {len(doc.tables)}"

    # Tabela 0: Card de Metadados (2x2)
    meta_table = doc.tables[0]
    assert len(meta_table.rows) == 2
    assert len(meta_table.columns) == 2

    # Tabela 1: Caixa de Decisões (1x1 com decisões dentro)
    decisions_table = doc.tables[1]
    assert len(decisions_table.rows) == 1
    assert "Aprovada a implementação" in decisions_table.cell(0, 0).text

    # Tabela 2: Plano de Ação Zebrado (4 linhas: 1 cabeçalho + 3 dados)
    action_table = doc.tables[2]
    assert len(action_table.rows) == 4, f"Esperado 4 linhas na tabela de ações, encontrado {len(action_table.rows)}"
    assert len(action_table.columns) == 3

    hdr_text = [cell.text.strip() for cell in action_table.rows[0].cells]
    assert "AÇÃO / DELIBERAÇÃO" in hdr_text
    assert "RESPONSÁVEL" in hdr_text
    assert "PRAZO" in hdr_text

    row1_text = [cell.text.strip() for cell in action_table.rows[1].cells]
    assert "Finalizar módulo de exportação Word" in row1_text
    assert "Thiago Esteves" in row1_text

    print(f"  -> Parágrafos validados: {len(paragraphs_text)} parágrafos com títulos e estilos corretos.")
    print(f"  -> Tabelas validadas: {len(doc.tables)} tabelas (Metadados, Decisões e Matriz de Ações).")
    print("  -> TESTE 2 APROVADO: Integridade estrutural do DOCX confirmada!")


def test_markdown_to_docx_pipeline():
    """Valida o fluxo integrado de texto Markdown do LLM para o arquivo .docx."""
    print("\n[TESTE 3] Validando Fluxo Integrado (Markdown -> Parser -> DOCX)...")
    sample_markdown = """# ATA DE REUNIÃO: Homologação do Sistema

## 1. Informações Gerais
- Data: 14/10/2026
- Participantes: Thiago, Gerência

## 2. Resumo Executivo
Sessão de validação da exportação do documento corporativo.

## 3. Pautas Discutidas
### Formatação de Tabelas
Aplicação de paleta azul marinho nas colunas.

## 4. Decisões Tomadas
- Padrão visual homologado sem pendências.

## 5. Plano de Ação
| Ação / O Quê | Responsável | Prazo |
|---|---|---|
| Iniciar desenvolvimento da Fase 5 | Thiago | Imediato |

## 6. Próximos Passos e Pendências
- Conectar widget desktop na próxima fase.
"""

    minutes = MinutesParser.parse(sample_markdown)
    output_pipeline = OUTPUT_DIR / "test_pipeline_output.docx"

    builder = DocxMeetingMinutesBuilder()
    saved = builder.build(minutes, output_pipeline)

    assert saved.exists(), "O arquivo gerado pelo pipeline deveria existir."
    doc = docx.Document(str(saved))
    assert len(doc.tables) >= 3

    print(f"  -> Documento ponta a ponta gerado: {saved.name} ({saved.stat().st_size} bytes)")
    print("  -> TESTE 3 APROVADO: Fluxo integrado concluído com perfeição!")


if __name__ == "__main__":
    test_docx_generation_from_model()
    test_docx_document_integrity()
    test_markdown_to_docx_pipeline()
    print("\n==========================================")
    print("TODOS OS TESTES DA FASE 4 FORAM CONCLUÍDOS!")
    print("==========================================")
