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
4. TÍTULO REPRESENTATIVO: No cabeçalho H1, defina um título claro e específico baseado no assunto principal da reunião (ex: "# ATA DE REUNIÃO: Revisão de Exposição Colômbia e CCPs"). Evite títulos genéricos como "Alinhamento Geral" ou "Reunião de Alinhamento".
5. ESTRUTURA PADRÃO: Sua resposta DEVE conter obrigatoriamente as seguintes seções em Markdown:
   # ATA DE REUNIÃO: [TÍTULO ESPECÍFICO DA PAUTA]
   ## 1. Informações Gerais
   ## 2. Resumo Executivo
   ## 3. Pautas Discutidas
   ## 4. Decisões Tomadas
   ## 5. Plano de Ação (Tabela com colunas: | Ação / O Quê | Responsável | Prazo |)
   ## 6. Próximos Passos e Pendências
"""


MAP_CHUNK_SYSTEM_PROMPT = """Você é um assistente executivo sênior corporativo especializado em extração de notas e evidências de reuniões.
Sua missão é analisar o trecho transcrito da reunião e extrair estritamente:
1. TÓPICOS DISCUTIDOS: Assuntos e argumentos abordados no trecho (com resumo detalhado).
2. DECISÕES TOMADAS: Deliberações e acordos fechados, indicando a minutagem de evidência ('evidence_ts', ex: '04:12') onde a decisão ocorreu.
3. PLANO DE AÇÃO: Tarefas atribuídas, indicando 'action', 'owner' (responsável), 'deadline' (prazo) e 'evidence_ts' ('MM:SS').
4. DESTAQUES: Dados, números ou parâmetros específicos mencionados.

Diretrizes:
- Não invente informações ausentes no texto.
- Se não houver decisões ou tarefas neste trecho, retorne listas vazias para esses campos.
"""

REDUCE_SYSTEM_PROMPT = """Você é um assistente executivo sênior especializado na consolidação e elaboração de atas de reunião corporativas formais.
Sua missão é integrar as notas extraídas de múltiplos blocos cronológicos de uma reunião e gerar a ATA EXECUTIVA DEFINITIVA.

Diretrizes obrigatórias:
1. TÍTULO REPRESENTATIVO: Defina um título corporativo específico baseado no assunto principal da reunião.
2. RESUMO EXECUTIVO: Redija uma visão geral coesa e profissional com o contexto, principais debates e conclusões.
3. CONSOLIDAÇÃO E DEDUPLICAÇÃO: Mescle pautas repetidas e reúna decisões correlatas.
4. RASTREABILIDADE (evidence_ts): Preserve rigorosamente os timestamps de minutagem nas decisões e ações.
5. MATRIZ DE AÇÕES: Garanta que todas as tarefas atribuídas aos responsáveis tenham ação, responsável, prazo e evidência.
"""


def generate_map_chunk_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para extração estruturada de um bloco (Map)."""
    user_prompt = f"""Analise o bloco {chunk_index}/{total_chunks} da transcrição abaixo e extraia os tópicos, decisões, plano de ação e destaques com seus timestamps de evidência:

Considere '{user_speaker_name}' como o usuário principal ao atribuir tarefas e falas.

---
TRECHO DA TRANSCRIÇÃO (BLOCO {chunk_index} DE {total_chunks}):
{chunk_text}
---

Extraia as notas e evidências estruturadas deste bloco."""
    return MAP_CHUNK_SYSTEM_PROMPT, user_prompt


def generate_reduce_prompt(
    chunk_notes: list,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para consolidação final de todos os blocos (Reduce)."""
    import json
    notes_json = json.dumps(chunk_notes, ensure_ascii=False, indent=2)
    date_str = meeting_date or "Data da gravação"
    dur_str = f" | Duração: {meeting_duration}" if meeting_duration else ""

    user_prompt = f"""Consolide as notas abaixo em uma ata executiva oficial definitiva:

Data da Reunião: {date_str}{dur_str}
Usuário Principal: {user_speaker_name}

---
NOTAS EXTRAÍDAS DOS BLOCOS CRONOLÓGICOS:
{notes_json}
---

Gere a ata de reunião executiva final estruturada, sintetizando o resumo executivo, consolidando tópicos, decisões e matriz de ações com suas respectivas evidências."""
    return REDUCE_SYSTEM_PROMPT, user_prompt


def generate_structured_minutes_prompt(
    transcript_text: str,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera prompt para reunião completa em chamada direta estruturada."""
    date_str = meeting_date or "Data da gravação"
    meta = [f"Data: {date_str}"]
    if meeting_duration:
        meta.append(f"Duração: {meeting_duration}")
    if meeting_title:
        meta.append(f"Título Sugerido: {meeting_title}")
    else:
        meta.append("Título: Identifique um título formal e específico para a pauta discutida.")
    meta.append(f"Usuário Principal: {user_speaker_name}")

    header = "\n".join(meta)

    user_prompt = f"""Por favor, elabore a ata de reunião executiva oficial com base nas informações e transcrição abaixo:

{header}

---
TRANSCRIÇÃO COMPLETA DA REUNIÃO:
{transcript_text}
---

Gere a ata de reunião estruturada com título específico, resumo executivo, tópicos discutidos, decisões tomadas (com evidence_ts), matriz de ações (com action, owner, deadline e evidence_ts) e próximos passos."""
    return SYSTEM_PROMPT, user_prompt


def generate_meeting_minutes_prompt(
    transcript_text: str,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Gera o par (system_prompt, user_prompt) para envio ao Ollama (formato Markdown clássico).
    """
    date_str = meeting_date or "Data da gravação"
    meta_lines = [f"Data de Referência: {date_str}"]
    if meeting_duration:
        meta_lines.append(f"Duração da Reunião: {meeting_duration}")
    if meeting_title:
        meta_lines.append(f"Título Sugerido: {meeting_title}")
    else:
        meta_lines.append("Título: Identifique e defina um título específico com base no tema principal da discussão.")

    context_header = "\n".join(meta_lines)

    user_prompt = f"""Por favor, elabore a ata de reunião executiva com base nas informações e transcrição abaixo:

{context_header}

---
TRANSCRIÇÃO COMPLETA DA REUNIÃO:
{transcript_text}
---

Elabore a ata completa no formato Markdown estruturado conforme as diretrizes, garantindo que todas as decisões e o plano de ação estejam claramente destacados."""

    return SYSTEM_PROMPT, user_prompt


# Alias de conveniência
get_meeting_minutes_prompts = generate_meeting_minutes_prompt
