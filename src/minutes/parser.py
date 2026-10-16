"""
Parser e Sanitizador Estruturado da Ata de Reunião
Converte a saída Markdown do LLM em uma estrutura de dados tipada (MeetingMinutes)
para fácil exibição na interface e exportação para Microsoft Word (.docx).
"""

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ActionItem:
    action: str
    owner: str
    deadline: str
    evidence_ts: str = ""


@dataclass
class MeetingMinutes:
    title: str = "Ata de Reunião"
    date: str = ""
    participants: List[str] = field(default_factory=list)
    executive_summary: str = ""
    topics: List[Dict[str, str]] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    raw_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeetingMinutes":
        """Instancia MeetingMinutes a partir de um dicionário JSON estruturado."""
        raw_actions = data.get("action_items", [])
        action_objs: List[ActionItem] = []
        for a in raw_actions:
            if isinstance(a, dict):
                action_objs.append(
                    ActionItem(
                        action=str(a.get("action", "")).strip(),
                        owner=str(a.get("owner", "")).strip() or "Não definido",
                        deadline=str(a.get("deadline", "")).strip() or "Não definido",
                        evidence_ts=str(a.get("evidence_ts", "")).strip(),
                    )
                )
            elif isinstance(a, ActionItem):
                action_objs.append(a)

        raw_decisions = data.get("decisions", [])
        decisions_list: List[str] = []
        for d in raw_decisions:
            if isinstance(d, dict):
                dec_text = str(d.get("decision", "")).strip()
                ev = str(d.get("evidence_ts", "")).strip()
                if ev and f"[{ev}]" not in dec_text:
                    dec_text = f"{dec_text} [{ev}]"
                if dec_text:
                    decisions_list.append(dec_text)
            elif isinstance(d, str):
                if d.strip():
                    decisions_list.append(d.strip())

        raw_topics = data.get("topics", [])
        topics_list: List[Dict[str, str]] = []
        for t in raw_topics:
            if isinstance(t, dict):
                topics_list.append({
                    "topic": str(t.get("topic", "")).strip(),
                    "details": str(t.get("details", "")).strip(),
                })

        return cls(
            title=str(data.get("title", "Ata de Reunião")).strip(),
            date=str(data.get("date", "")).strip(),
            participants=[str(p).strip() for p in data.get("participants", []) if str(p).strip()],
            executive_summary=str(data.get("executive_summary", "")).strip(),
            topics=topics_list,
            decisions=decisions_list,
            action_items=action_objs,
            next_steps=[str(s).strip() for s in data.get("next_steps", []) if str(s).strip()],
            raw_markdown=str(data.get("raw_markdown", "")),
        )


class MinutesParser:
    """
    Analisa o texto Markdown gerado pelo LLM e extrai seções estruturadas.
    Possui alta tolerância a variações na formatação do modelo.
    """

    @classmethod
    def parse(cls, markdown_text: str) -> MeetingMinutes:
        minutes = MeetingMinutes(raw_markdown=markdown_text)

        # 1. Extração do Título (linha única que começa com # e não ##, sem engolir quebra de linha)
        title_matches = re.finditer(r"^#[ \t]+([^\r\n]+)$", markdown_text, re.MULTILINE)
        for tm in title_matches:
            raw_title = tm.group(1).strip()
            # Remove prefixos redundantes como "Ata de Reunião: " ou "Ata de Reunião - "
            cleaned = re.sub(r"^ATA DE REUNI[ÃA]O[ \t]*[:\-–][ \t]*", "", raw_title, flags=re.IGNORECASE).strip()
            if cleaned and not re.match(r"^ATA DE REUNI[ÃA]O$", cleaned, re.IGNORECASE):
                minutes.title = cleaned
                break
            elif cleaned and re.match(r"^ATA DE REUNI[ÃA]O$", cleaned, re.IGNORECASE):
                minutes.title = "Ata de Reunião"

        # Divide o texto em seções baseadas nos cabeçalhos H2 (## )
        sections = re.split(r"\n##\s+", "\n" + markdown_text)

        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue

            lines = sec.split("\n")
            header = lines[0].strip().lower()
            content = "\n".join(lines[1:]).strip()

            # 2. Informações Gerais / Participantes
            if any(k in header for k in ["informações", "informacoes", "dados", "participantes"]):
                cls._parse_info_section(content, minutes)

            # 3. Resumo Executivo
            elif any(k in header for k in ["resumo", "visão geral", "visao geral", "sumário", "sumario"]):
                minutes.executive_summary = content

            # 4. Pautas e Discussões
            elif any(k in header for k in ["pauta", "discussões", "discussoes", "tópicos", "topicos"]):
                minutes.topics = cls._parse_topics(content)

            # 5. Decisões Tomadas
            elif any(k in header for k in ["decisões", "decisoes", "decisão", "decisao", "deliberações", "deliberacoes", "consensos"]):
                minutes.decisions = cls._parse_bullet_list(content)

            # 6. Plano de Ação (Tabela ou Lista)
            elif any(k in header for k in ["ação", "ações", "acao", "acoes", "plano de ação", "plano de acao", "atividades", "tarefas"]):
                minutes.action_items = cls._parse_action_items(content)

            # 7. Próximos Passos e Pendências
            elif any(k in header for k in ["próximos passos", "proximos passos", "pendências", "pendencias", "encaminhamentos"]):
                minutes.next_steps = cls._parse_bullet_list(content)

        logger.info(
            "Ata parseada com sucesso: '%s' (%d decisões, %d ações identificadas).",
            minutes.title,
            len(minutes.decisions),
            len(minutes.action_items),
        )
        return minutes

    @classmethod
    def _parse_info_section(cls, content: str, minutes: MeetingMinutes):
        """Extrai data e lista de participantes citados."""
        for line in content.split("\n"):
            line = line.strip()
            if "data" in line.lower() and ":" in line:
                minutes.date = line.split(":", 1)[1].strip(" *_-")
            elif "participantes" in line.lower() and ":" in line:
                parts = line.split(":", 1)[1].strip(" *_-")
                minutes.participants = [p.strip() for p in parts.split(",") if p.strip()]

    @classmethod
    def _parse_bullet_list(cls, content: str) -> List[str]:
        """Extrai itens de listas com marcadores '-' ou numeração '1.'."""
        items = []
        for line in content.split("\n"):
            line = line.strip()
            # Casa com - item, * item ou 1. item
            match = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", line)
            if match:
                items.append(match.group(1).strip())
            elif line and not line.startswith("#"):
                # Linha avulsa dentro do bloco
                if items:
                    items[-1] += " " + line
        return items

    @classmethod
    def _parse_topics(cls, content: str) -> List[Dict[str, str]]:
        """Extrai tópicos discutidos (H3 ou marcadores)."""
        topics = []
        current_topic = ""
        current_details: List[str] = []

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("### ") or re.match(r"^(?:[-*]|\d+\.)\s+\*\*(.+?)\*\*", line):
                if current_topic:
                    topics.append({"topic": current_topic, "details": "\n".join(current_details).strip()})
                    current_details = []

                if line.startswith("### "):
                    current_topic = line.replace("### ", "").strip()
                else:
                    m = re.match(r"^(?:[-*]|\d+\.)\s+\*\*(.+?)\*\*(?::)?\s*(.*)$", line)
                    if m:
                        current_topic = m.group(1).strip()
                        if m.group(2):
                            current_details.append(m.group(2).strip())
            else:
                if line:
                    current_details.append(line)

        if current_topic:
            topics.append({"topic": current_topic, "details": "\n".join(current_details).strip()})

        # Fallback caso não tenha H3 nem negrito: trata como lista simples
        if not topics:
            bullets = cls._parse_bullet_list(content)
            topics = [{"topic": f"Pauta {i+1}", "details": b} for i, b in enumerate(bullets)]

        return topics

    @classmethod
    def _parse_action_items(cls, content: str) -> List[ActionItem]:
        """
        Extrai itens de ação prioritariamente da tabela Markdown (| Ação | Responsável | Prazo | Evidência |).
        Caso o modelo não tenha gerado tabela, tenta extrair de lista com marcadores.
        """
        actions: List[ActionItem] = []

        table_rows = [line.strip() for line in content.split("\n") if line.strip().startswith("|") and line.strip().endswith("|")]

        if len(table_rows) >= 3:
            # Pula cabeçalho (linha 0) e divisor (linha 1: |---|---|---|)
            for row in table_rows[2:]:
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if len(cells) >= 3:
                    action_text, owner, deadline = cells[0], cells[1], cells[2]
                    evidence_ts = cells[3] if len(cells) >= 4 else ""
                    # Se evidence_ts não estiver em coluna própria, tenta extrair do texto
                    if not evidence_ts:
                        ts_m = re.search(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", action_text)
                        if ts_m:
                            evidence_ts = ts_m.group(1)
                    # Ignora linhas divisórias residuais
                    if not all(c == "-" for c in action_text.replace(" ", "")):
                        actions.append(
                            ActionItem(
                                action=action_text,
                                owner=owner or "Não definido",
                                deadline=deadline or "Não definido",
                                evidence_ts=evidence_ts,
                            )
                        )
            if actions:
                return actions

        # Fallback para listas com regex (ex: - Finalizar módulo X (Responsável: Thiago, Prazo: Amanhã))
        for line in content.split("\n"):
            line = line.strip()
            match = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", line)
            if match:
                full_text = match.group(1).strip()
                owner = "Não definido"
                deadline = "Não definido"
                evidence_ts = ""

                ts_m = re.search(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", full_text)
                if ts_m:
                    evidence_ts = ts_m.group(1)

                owner_match = re.search(r"\(?(?:Responsável|Quem|Por)[:\s]+([^,\)\;]+)", full_text, re.IGNORECASE)
                if owner_match:
                    owner = owner_match.group(1).strip()

                deadline_match = re.search(r"(?:Prazo|Quando|Data|Até)[:\s]+([^,\)\;]+)", full_text, re.IGNORECASE)
                if deadline_match:
                    deadline = deadline_match.group(1).strip()

                clean_action = re.sub(r"\(?(?:Responsável|Quem|Prazo|Quando)[^\)]*\)?", "", full_text).strip(" -:;,")
                actions.append(
                    ActionItem(
                        action=clean_action or full_text,
                        owner=owner,
                        deadline=deadline,
                        evidence_ts=evidence_ts,
                    )
                )

        return actions
