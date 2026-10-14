"""
Módulo de Engenharia de Prompts Corporativos para Geração de Atas de Reunião
Otimizado para LLMs compactos locais (Llama 3.2 3B e similares) em Português.
"""

from typing import Optional, Tuple


SYSTEM_PROMPT = """Você é um assistente executivo sênior especializado na elaboração de atas de reunião formais, objetivas e profissionais para ambientes corporativos.

Sua tarefa é analisar a transcrição da reunião realizada no Microsoft Teams e estruturar uma ATA DE REUNIÃO oficial e executiva em Língua Portuguesa (pt-BR).

Diretrizes obrigatórias:
1. FIDELIDADE E PRECISÃO: Baseie-se estritamente no conteúdo que foi discutido. Não invente decisões, prazos ou tarefas não mencionadas.
2. DISTINÇÃO DE INTERLOCUTORES: A transcrição identifica "[Você]" e "[Participantes da Reunião]". Use essas referências e nomes citados para atribuir responsabilidades corretamente.
3. CONCISÃO EXECUTIVA: Seja direto, claro e profissional. Evite termos coloquiais ou repetições.
4. ESTRUTURA PADRÃO: Sua resposta DEVE conter obrigatoriamente as seguintes seções em Markdown:
   # ATA DE REUNIÃO: [TÍTULO DA REUNIÃO]
   ## 1. Informações Gerais
   ## 2. Resumo Executivo
   ## 3. Pautas Discutidas
   ## 4. Decisões Tomadas
   ## 5. Plano de Ação (Tabela com colunas: | Ação / O Quê | Responsável | Prazo |)
   ## 6. Próximos Passos e Pendências
"""


def generate_meeting_minutes_prompt(
    transcript_text: str,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Gera o par (system_prompt, user_prompt) para envio ao Ollama.
    """
    title = meeting_title or "Reunião de Alinhamento e Deliberações"
    date_str = meeting_date or "Data da gravação"

    user_prompt = f"""Por favor, elabore a ata de reunião executiva com base nas informações e transcrição abaixo:

Título Sugerido: {title}
Data de Referência: {date_str}

---
TRANSCRIÇÃO COMPLETA DA REUNIÃO:
{transcript_text}
---

Elabore a ata completa no formato Markdown estruturado conforme as diretrizes, garantindo que todas as decisões e o plano de ação estejam claramente destacados."""

    return SYSTEM_PROMPT, user_prompt


# Alias de conveniência
get_meeting_minutes_prompts = generate_meeting_minutes_prompt
