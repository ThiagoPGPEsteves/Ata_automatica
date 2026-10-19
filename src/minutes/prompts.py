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
3. CONTEXTO MULTILÍNGUE (ESPANHOL E PORTUGUÊS): A reunião pode contar com participantes falando em Espanhol e/ou Português. Compreenda com precisão ambos os idiomas e redija a ata oficial consolidada em Língua Portuguesa (pt-BR), preservando termos técnicos, métricas e nomes próprios sem distorções.
4. CONCISÃO EXECUTIVA: Seja direto, claro e profissional. Evite termos coloquiais e NUNCA repita frases ou parágrafos.
5. TÍTULO REPRESENTATIVO: No cabeçalho H1, defina um título claro e específico baseado no assunto principal da reunião (ex: "# ATA DE REUNIÃO: Revisão de Exposição Colômbia e CCPs"). Evite títulos genéricos como "Alinhamento Geral" ou "Reunião de Alinhamento".
6. ESTRUTURA PADRÃO: Sua resposta DEVE conter obrigatoriamente as seguintes seções em Markdown:
   # ATA DE REUNIÃO: [TÍTULO ESPECÍFICO DA PAUTA]
   ## 1. Informações Gerais
   ## 2. Resumo Executivo (no máximo 2 a 3 parágrafos objetivos)
   ## 3. Pautas Discutidas
   ## 4. Decisões Tomadas
   ## 5. Plano de Ação (Tabela com colunas: | Ação / O Quê | Responsável | Prazo |)
   ## 6. Próximos Passos e Pendências
"""


THEME_SUMMARY_SYSTEM_PROMPT = """Você é um assistente executivo sênior especializado em síntese analítica e mapeamento de discussões corporativas.

Sua missão é analisar a transcrição da reunião realizada no Microsoft Teams e estruturar um RESUMO EXECUTIVO DOS TEMAS DISCUTIDOS em Língua Portuguesa (pt-BR).

Diretrizes obrigatórias:
1. FOCO NOS TEMAS E DISCUSSÕES: Sintetize em profundidade os assuntos, ideias, teses, pontos de vista e o contexto de cada pauta abordada.
2. SEM OBRIGATORIEDADE DE DECISÕES OU TAREFAS: Esta reunião é informativa, exploratória ou de alinhamento. NÃO invente decisões tomadas nem planos de ação se eles não ocorreram naturalmente. Caso deliberações ou tarefas pontuais tenham sido expressas claramente, você pode citá-las de forma sucinta nos tópicos, mas nunca force tabelas ou estruturas artificiais de tarefas.
3. CONTEXTO MULTILÍNGUE (ESPANHOL E PORTUGUÊS): A reunião pode contar com participantes se comunicando em Espanhol e/ou Português. Compreenda com precisão as falas em ambos os idiomas e traduza/sintetize tudo de forma fluida, executiva e profissional em Língua Portuguesa (pt-BR), mantendo termos técnicos, métricas e nomes próprios.
4. CONCISÃO E PROFUNDIDADE: Estruture a síntese de forma clara e analítica, destacando o cerne de cada discussão sem repetições.
5. ESTRUTURA PADRÃO:
   # RESUMO DE TEMAS: [TÍTULO ESPECÍFICO DA DISCUSSÃO]
   ## 1. Informações Gerais
   ## 2. Visão Geral da Discussão
   ## 3. Temas e Tópicos Discutidos
   ## 4. Destaques e Observações Relevantes
"""


MAP_CHUNK_SYSTEM_PROMPT = """Você é um assistente executivo sênior corporativo especializado em extração de notas e evidências de reuniões.
Sua missão é analisar o trecho transcrito da reunião e extrair estritamente:
1. TÓPICOS DISCUTIDOS: Assuntos e argumentos abordados no trecho (com resumo detalhado).
2. DECISÕES TOMADAS: Deliberações e acordos fechados, indicando a minutagem de evidência ('evidence_ts', ex: '04:12') onde a decisão ocorreu.
3. PLANO DE AÇÃO: Tarefas atribuídas, indicando 'action', 'owner' (responsável), 'deadline' (prazo) e 'evidence_ts' ('MM:SS').
4. DESTAQUES: Dados, números ou parâmetros específicos mencionados.

Diretrizes:
- A reunião pode conter falas em Espanhol e Português; compreenda ambos os idiomas com precisão e extraia as notas em Português (pt-BR).
- Não invente informações ausentes no texto.
- Se não houver decisões ou tarefas neste trecho, retorne listas vazias para esses campos.
"""

THEME_MAP_CHUNK_SYSTEM_PROMPT = """Você é um assistente executivo sênior corporativo especializado em extração de tópicos e discussões de reuniões.
Sua missão é analisar o trecho transcrito da reunião e extrair estritamente os temas e discussões abordados:
1. TÓPICOS DISCUTIDOS: Assuntos, pontos de vista, argumentos e preocupações abordados no trecho (com resumo detalhado).
2. DESTAQUES: Dados, métricas, números ou parâmetros específicos mencionados.

Diretrizes:
- A reunião pode conter falas em Espanhol e Português; compreenda ambos os idiomas com precisão e extraia as notas em Português (pt-BR).
- Não force extração de decisões ou tarefas se não existirem.
- Não invente informações ausentes no texto.
"""

REDUCE_SYSTEM_PROMPT = """Você é um assistente executivo sênior especializado na consolidação e elaboração de atas de reunião corporativas formais.
Sua missão é integrar as notas extraídas de múltiplos blocos cronológicos de uma reunião e gerar a ATA EXECUTIVA DEFINITIVA.

Diretrizes obrigatórias:
1. TÍTULO REPRESENTATIVO: Defina um título corporativo específico baseado no assunto principal da reunião.
2. RESUMO EXECUTIVO: Redija uma visão geral coesa e profissional com o contexto, principais debates e conclusões.
3. CONSOLIDAÇÃO E DEDUPLICAÇÃO: Mescle pautas repetidas e reúna decisões correlatas.
4. RASTREABILIDADE (evidence_ts): Preserve rigorosamente os timestamps de minutagem nas decisões e ações.
5. MATRIZ DE AÇÕES: Garanta que todas as tarefas atribuídas aos responsáveis tenham ação, responsável, prazo e evidência.
6. CONTEXTO MULTILÍNGUE: Consolide o documento oficial em Português (pt-BR) integrando perfeitamente discussões em espanhol e português.
"""

THEME_REDUCE_SYSTEM_PROMPT = """Você é um assistente executivo sênior especializado na consolidação analítica de discussões corporativas.
Sua missão é integrar as notas extraídas de múltiplos blocos cronológicos de uma reunião e gerar o RESUMO EXECUTIVO DE TEMAS DEFINITIVO.

Diretrizes obrigatórias:
1. TÍTULO REPRESENTATIVO: Defina um título corporativo específico baseado no assunto principal da reunião.
2. VISÃO GERAL: Redija uma visão geral coesa e profissional sintetizando o contexto global dos debates.
3. CONSOLIDAÇÃO DE TEMAS: Mescle temas correlatos em blocos analíticos ricos e sem repetições.
4. SEM OBRIGATORIEDADE DE DECISÕES OU AÇÕES: Não invente nem exija tabela de ações ou decisões tomadas.
5. CONTEXTO MULTILÍNGUE: Consolide o texto final em Português (pt-BR) integrando perfeitamente discussões ocorridas em espanhol e português.
"""


def generate_map_chunk_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para extração estruturada de um bloco (Map) para Ata Executiva."""
    user_prompt = f"""Analise o bloco {chunk_index}/{total_chunks} da transcrição abaixo e extraia os tópicos, decisões, plano de ação e destaques com seus timestamps de evidência:

Considere '{user_speaker_name}' como o usuário principal ao atribuir tarefas e falas.
Nota: Trechos em espanhol devem ser compreendidos e registrados em português.

---
TRECHO DA TRANSCRIÇÃO (BLOCO {chunk_index} DE {total_chunks}):
{chunk_text}
---

Extraia as notas e evidências estruturadas deste bloco."""
    return MAP_CHUNK_SYSTEM_PROMPT, user_prompt


def generate_theme_map_chunk_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para extração de temas de um bloco (Map) para Resumo Temático."""
    user_prompt = f"""Analise o bloco {chunk_index}/{total_chunks} da transcrição abaixo e extraia os temas discutidos e destaques:

Considere '{user_speaker_name}' como o usuário principal.
Nota: Trechos em espanhol devem ser compreendidos e registrados em português.

---
TRECHO DA TRANSCRIÇÃO (BLOCO {chunk_index} DE {total_chunks}):
{chunk_text}
---

Extraia os temas e discussões deste bloco."""
    return THEME_MAP_CHUNK_SYSTEM_PROMPT, user_prompt


def generate_reduce_prompt(
    chunk_notes: list,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para consolidação final de todos os blocos (Reduce) para Ata Executiva."""
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


def generate_theme_reduce_prompt(
    chunk_notes: list,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera o prompt para consolidação final de todos os blocos (Reduce) para Resumo Temático."""
    import json
    notes_json = json.dumps(chunk_notes, ensure_ascii=False, indent=2)
    date_str = meeting_date or "Data da gravação"
    dur_str = f" | Duração: {meeting_duration}" if meeting_duration else ""

    user_prompt = f"""Consolide as notas abaixo em um resumo executivo de temas definitivo:

Data da Reunião: {date_str}{dur_str}
Usuário Principal: {user_speaker_name}

---
NOTAS EXTRAÍDAS DOS BLOCOS CRONOLÓGICOS:
{notes_json}
---

Gere o resumo de temas estruturado, sintetizando a visão geral e consolidando em profundidade os tópicos debatidos e destaques sem exigir decisões ou ações."""
    return THEME_REDUCE_SYSTEM_PROMPT, user_prompt


def generate_structured_minutes_prompt(
    transcript_text: str,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera prompt para ata de reunião completa em chamada direta estruturada."""
    date_str = meeting_date or "Data da gravação"
    meta = [f"Data: {date_str}"]
    if meeting_duration:
        meta.append(f"Duração: {meeting_duration}")
    if meeting_title:
        meta.append(f"Título Sugerido: {meeting_title}")
    else:
        meta.append("Título: Identifique um título formal e específico para a pauta discutida.")
    meta.append(f"Usuário Principal: {user_speaker_name}")
    meta.append("Contexto de Idioma: A reunião pode conter participantes falando em Espanhol e/ou Português.")

    header = "\n".join(meta)

    user_prompt = f"""Por favor, elabore a ata de reunião executiva oficial com base nas informações e transcrição abaixo:

{header}

---
TRANSCRIÇÃO COMPLETA DA REUNIÃO:
{transcript_text}
---

Gere a ata de reunião estruturada em Português (pt-BR) com título específico, resumo executivo, tópicos discutidos, decisões tomadas (com evidence_ts), matriz de ações (com action, owner, deadline e evidence_ts) e próximos passos."""
    return SYSTEM_PROMPT, user_prompt


def generate_theme_summary_prompt(
    transcript_text: str,
    meeting_title: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_duration: Optional[str] = None,
    user_speaker_name: str = "Você",
) -> Tuple[str, str]:
    """Gera prompt para Resumo dos Temas Discutidos (sem obrigatoriedade de decisões ou tarefas)."""
    date_str = meeting_date or "Data da gravação"
    meta = [f"Data: {date_str}"]
    if meeting_duration:
        meta.append(f"Duração: {meeting_duration}")
    if meeting_title:
        meta.append(f"Título Sugerido: {meeting_title}")
    else:
        meta.append("Título: Identifique um título formal e representativo para o tema central debatido.")
    meta.append(f"Usuário Principal: {user_speaker_name}")
    meta.append("Contexto de Idioma: A reunião pode conter participantes falando em Espanhol e/ou Português.")

    header = "\n".join(meta)

    user_prompt = f"""Por favor, elabore o RESUMO EXECUTIVO DOS TEMAS DISCUTIDOS com base nas informações e transcrição abaixo:

{header}

---
TRANSCRIÇÃO COMPLETA DA REUNIÃO:
{transcript_text}
---

Gere o resumo temático estruturado em Português (pt-BR), sintetizando com clareza o contexto geral, os temas discutidos em profundidade e os destaques relevantes, sem forçar decisões ou planos de ação artificiais."""
    return THEME_SUMMARY_SYSTEM_PROMPT, user_prompt


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
    meta_lines.append("Contexto: Participantes podem se expressar em Português e Espanhol. Elabore a ata em Português.")

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

