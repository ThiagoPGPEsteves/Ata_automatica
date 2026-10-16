"""
Teste Automatizado da Fase 3: Geração de Atas, Engenharia de Prompts e Cliente Ollama com keep_alive: 0s.
Valida:
1. Geração de prompts corporativos a partir de transcrições da Fase 2.
2. Parsing da ata estruturada (Título, Resumo, Pautas, Decisões, Tabela de Ações).
3. Verificação de conformidade do cliente Ollama (garantia de envio da diretiva keep_alive: 0s).
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.minutes.prompts import generate_meeting_minutes_prompt, SYSTEM_PROMPT
from src.minutes.parser import MinutesParser, MeetingMinutes, ActionItem
from src.minutes.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
)
import pytest

pytestmark = pytest.mark.unit


def test_prompts_generation():
    """Valida a construção dos prompts corporativos."""
    print("\n[TESTE 1] Validando Geração de Prompts Corporativos...")
    sample_transcript = (
        "[00:00 - 00:05] [Você]: Olá equipe, bom dia. Vamos aprovar a arquitetura do projeto de ata.\n"
        "[00:06 - 00:15] [Participantes da Reunião]: Bom dia Thiago, arquitetura revisada. Aprovado o uso do faster-whisper e Ollama.\n"
        "[00:16 - 00:25] [Você]: Perfeito. Thiago fica responsável por finalizar os módulos até sexta-feira."
    )

    sys_prompt, user_prompt = generate_meeting_minutes_prompt(
        sample_transcript,
        meeting_title="Reunião de Arquitetura",
        meeting_date="14/10/2026",
    )

    assert "assistente executivo" in sys_prompt.lower()
    assert "Plano de Ação" in sys_prompt
    assert "Decisões Tomadas" in sys_prompt
    assert "Reunião de Arquitetura" in user_prompt
    assert "14/10/2026" in user_prompt
    assert "Olá equipe" in user_prompt

    print("  -> Prompt do Sistema e Prompt do Usuário estruturados corretamente!")
    print("  -> TESTE 1 APROVADO!")


def test_minutes_parser():
    """Valida o parser em texto Markdown com tabelas e deliberações."""
    print("\n[TESTE 2] Validando Parser Estruturado da Ata de Reunião...")
    sample_markdown = """# ATA DE REUNIÃO: Alinhamento de Sprint e Arquitetura

## 1. Informações Gerais
- Data: 14/10/2026
- Participantes: Thiago Esteves, Equipe de Engenharia

## 2. Resumo Executivo
A reunião teve como objetivo alinhar a arquitetura técnica da aplicação de ata automática.
Ficou deliberado o uso de componentes locais com teto estrito de 4GB de RAM.

## 3. Pautas Discutidas
### Arquitetura de Áudio
Discussão sobre captura WASAPI loopback e microfone em canais separados.
### Pipeline de Transcrição
Definição do uso de faster-whisper com quantização int8 para operação em CPU.

## 4. Decisões Tomadas
- Aprovada a captura dual-channel no Windows com separação de interlocutores.
- Aprovado o uso do modelo Llama 3.2 3B com descarregamento imediato via keep_alive 0s.
- Homologado o formato Word (.docx) como padrão oficial de entrega.

## 5. Plano de Ação
| Ação / O Quê | Responsável | Prazo |
|---|---|---|
| Implementar gravador WASAPI | Thiago Esteves | 15/10/2026 |
| Integrar cliente Ollama | Equipe de Backend | 16/10/2026 |
| Homologar exportador DOCX | Coordenação | 18/10/2026 |

## 6. Próximos Passos e Pendências
- Teste prático em reunião real de 30 minutos no Microsoft Teams.
- Validação de entrega para a diretoria.
"""

    minutes = MinutesParser.parse(sample_markdown)

    assert minutes.title == "Alinhamento de Sprint e Arquitetura", f"Título incorreto: {minutes.title}"
    assert "14/10/2026" in minutes.date, f"Data incorreta: {minutes.date}"
    assert len(minutes.participants) >= 1, "Participantes não encontrados"
    assert "reunião teve como objetivo" in minutes.executive_summary.lower()
    assert len(minutes.topics) == 2, f"Esperado 2 tópicos, obtido {len(minutes.topics)}"
    assert len(minutes.decisions) == 3, f"Esperado 3 decisões, obtido {len(minutes.decisions)}"
    assert len(minutes.action_items) == 3, f"Esperado 3 ações, obtido {len(minutes.action_items)}"
    assert len(minutes.next_steps) == 2, f"Esperado 2 próximos passos, obtido {len(minutes.next_steps)}"

    first_action = minutes.action_items[0]
    assert first_action.action == "Implementar gravador WASAPI"
    assert first_action.owner == "Thiago Esteves"
    assert first_action.deadline == "15/10/2026"

    data_dict = minutes.to_dict()
    assert "title" in data_dict
    assert "action_items" in data_dict
    assert len(data_dict["action_items"]) == 3

    print(f"  -> Título extraído: {minutes.title}")
    print(f"  -> Decisões extraídas: {len(minutes.decisions)} itens")
    print(f"  -> Ações extraídas: {len(minutes.action_items)} itens na tabela")
    print("  -> TESTE 2 APROVADO: Parser e dataclass MeetingMinutes validados!")


def test_ollama_client_compliance():
    """Valida que o cliente Ollama sempre transmite a diretiva keep_alive: '0s'."""
    print("\n[TESTE 3] Validando Cliente Ollama e Diretiva keep_alive: '0s'...")
    client = OllamaClient()

    assert client.keep_alive == "0s", "keep_alive padrão deve ser estritamente '0s'"

    # Simula resposta do servidor Ollama para testar o envio do payload
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": "llama3.2:3b",
        "response": "# ATA DE REUNIÃO\nConteúdo gerado com sucesso.",
        "done": True,
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        output = client.generate(
            prompt="Elabore a ata de teste",
            system="Instrução do sistema",
            model="llama3.2:3b",
        )

        assert mock_post.called, "requests.post deveria ter sido chamado"
        call_args, call_kwargs = mock_post.call_args
        payload = call_kwargs.get("json", {})

        print(f"  -> URL chamada: {call_args[0]}")
        print(f"  -> Payload transmitido:")
        print(f"     - model: {payload.get('model')}")
        print(f"     - keep_alive: {payload.get('keep_alive')}")
        print(f"     - stream: {payload.get('stream')}")

        assert payload.get("keep_alive") == "0s", "ERRO CRÍTICO: keep_alive '0s' não foi enviado no payload!"
        assert payload.get("model") == "llama3.2:3b"
        assert "Instrução do sistema" in payload.get("system", "")
        assert "Conteúdo gerado" in output

    print("  -> TESTE 3 APROVADO: Diretiva de descarregamento imediato 'keep_alive': '0s' comprovada!")


if __name__ == "__main__":
    test_prompts_generation()
    test_minutes_parser()
    test_ollama_client_compliance()
    print("\n==========================================")
    print("TODOS OS TESTES DA FASE 3 FORAM CONCLUÍDOS!")
    print("==========================================")
