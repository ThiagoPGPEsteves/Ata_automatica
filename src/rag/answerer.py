"""
Módulo de Síntese e Resposta (Answerer) para RAG
Constrói o prompt fundamentado nas fontes recuperadas [F1, F2...],
invoca o Ollama em modo JSON Schema e valida citações contra alucinações.
"""

from dataclasses import dataclass, field
import json
import logging
import re
from typing import List, Dict, Any, Optional

from src.minutes.ollama_client import OllamaClient
from src.minutes.generator import parse_json_safely
from src.rag.store import SearchResult
from src.utils.telemetry import format_duration

logger = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = "Não encontrei isso nas reuniões indexadas."


@dataclass
class SourceCitation:
    """Metadados estruturados de uma fonte citada."""

    id: str  # ex: "F1"
    session_id: str
    timestamp_str: str
    speakers: List[str]
    source_type: str  # "transcript" | "minutes"
    excerpt: str  # trecho de até 200 caracteres
    score: float


@dataclass
class RagAnswer:
    """Resposta consolidada pelo assistente com suporte a citações rastreáveis."""

    answer: str
    citations: List[str]  # Lista de IDs de fontes usadas, ex: ["F1", "F2"]
    found: bool
    sources: List[SourceCitation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": self.citations,
            "found": self.found,
            "sources": [
                {
                    "id": s.id,
                    "session_id": s.session_id,
                    "timestamp": s.timestamp_str,
                    "speakers": s.speakers,
                    "source_type": s.source_type,
                    "excerpt": s.excerpt,
                    "score": round(s.score, 4),
                }
                for s in self.sources
            ],
        }


class RagAnswerer:
    """
    Sintetizador de respostas com ancoragem estrita nas fontes e citações explícitas.
    """

    def __init__(self, ollama_client: Optional[OllamaClient] = None):
        self.client = ollama_client or OllamaClient()

    def answer(
        self,
        query: str,
        results: List[SearchResult],
    ) -> RagAnswer:
        """
        Gera uma resposta fundamentada utilizando os trechos recuperados.
        """
        if not results:
            return RagAnswer(
                answer=NOT_FOUND_MESSAGE,
                citations=[],
                found=False,
                sources=[],
            )

        # Mapeamento ordenado de fontes [F1, F2...]
        source_map: Dict[str, SearchResult] = {}
        sources_text_blocks: List[str] = []
        source_citations: List[SourceCitation] = []

        for idx, res in enumerate(results, start=1):
            fid = f"F{idx}"
            source_map[fid] = res
            chunk = res.chunk

            time_range = f"{format_duration(chunk.start_sec)} - {format_duration(chunk.end_sec)}"
            speakers_str = ", ".join(chunk.speakers) if chunk.speakers else "Participantes"

            # Gera um extrato de até 200 caracteres para exibição
            cleaned_excerpt = re.sub(r"\s+", " ", chunk.text).strip()
            if len(cleaned_excerpt) > 200:
                cleaned_excerpt = cleaned_excerpt[:197] + "..."

            source_citations.append(
                SourceCitation(
                    id=fid,
                    session_id=chunk.session_id,
                    timestamp_str=format_duration(chunk.start_sec),
                    speakers=chunk.speakers,
                    source_type=chunk.source,
                    excerpt=cleaned_excerpt,
                    score=res.score,
                )
            )

            block = (
                f"--- FONTE [{fid}] ---\n"
                f"Reunião: {chunk.session_id}\n"
                f"Horário: {time_range}\n"
                f"Falantes / Responsáveis: {speakers_str}\n"
                f"Origem: {'Transcrição' if chunk.source == 'transcript' else 'Ata Oficial'}\n"
                f"Conteúdo:\n{chunk.text}\n"
            )
            sources_text_blocks.append(block)

        context_str = "\n".join(sources_text_blocks)

        system_prompt = (
            "Você é o assistente inteligente 'Pergunte às suas atas' da aplicação Ata Automática.\n"
            "Sua missão é responder à dúvida do usuário com extrema precisão, usando ESTRITAMENTE as fontes fornecidas.\n"
            "Diretrizes obrigatórias:\n"
            "1. Responda em Português do Brasil de forma clara, executiva e direta.\n"
            "2. Toda afirmação fatual DEVE conter a citação do identificador da fonte entre colchetes, ex: [F1] ou [F2].\n"
            "3. NUNCA invente fatos, reuniões ou prazos não presentes nas fontes.\n"
            "4. Se as fontes fornecidas NÃO tiverem informações suficientes para responder com certeza, retorne:\n"
            f"   'found': false e 'answer': '{NOT_FOUND_MESSAGE}'.\n"
            "5. No campo 'citations', liste APENAS as fontes que você citou diretamente no texto de 'answer'. NÃO inclua fontes irrelevantes ou não utilizadas.\n"
            "6. A resposta deve ser OBRIGATORIAMENTE um objeto JSON válido com o schema:\n"
            "   {\n"
            '     "answer": "Texto da resposta com citações [F1]...",\n'
            '     "citations": ["F1", "F2"],\n'
            '     "found": true\n'
            "   }\n"
        )

        user_prompt = (
            f"Pergunta do usuário:\n{query}\n\n"
            f"Fontes disponíveis de reuniões:\n{context_str}\n\n"
            "Responda à pergunta seguindo rigorosamente o formato JSON especificado:"
        )

        try:
            raw_response = self.client.generate(
                prompt=user_prompt,
                system=system_prompt,
                response_format="json",
                keep_alive="0s",  # Libera RAM do LLM imediatamente
            )

            parsed = parse_json_safely(raw_response)

            answer_text = str(parsed.get("answer", "")).strip()
            found = bool(parsed.get("found", True))
            raw_citations = parsed.get("citations", [])

            if not isinstance(raw_citations, list):
                raw_citations = []

            # Validação rigorosa de citações:
            # 1. Normaliza lista e descarta citações alucinadas (que não existam em source_map)
            valid_citations = []
            for c in raw_citations:
                c_clean = str(c).strip().replace("[", "").replace("]", "").upper()
                if c_clean in source_map and c_clean not in valid_citations:
                    valid_citations.append(c_clean)

            # 2. Também detecta citações explícitas [F1] presentes no texto da resposta
            text_citations = []
            for match in re.findall(r"\[F(\d+)\]", answer_text, re.IGNORECASE):
                cid = f"F{match}"
                if cid in source_map and cid not in text_citations:
                    text_citations.append(cid)

            # Se o texto da resposta tem citações explícitas, prioriza-as sobre a lista raw do JSON (evita over-citation de distratores)
            if text_citations:
                valid_citations = text_citations

            # Se encontrou mas o texto indica expressamente que não foi encontrado
            if NOT_FOUND_MESSAGE.lower() in answer_text.lower():
                found = False

            if not found or not answer_text:
                return RagAnswer(
                    answer=NOT_FOUND_MESSAGE,
                    citations=[],
                    found=False,
                    sources=[],
                )

            # Filtra apenas as fontes que foram efetivamente citadas
            cited_sources = [s for s in source_citations if s.id in valid_citations]
            # Se nenhuma citação válida foi apontada pelo LLM, mantém todas as fontes recuperadas como referência
            final_sources = cited_sources if cited_sources else source_citations

            return RagAnswer(
                answer=answer_text,
                citations=valid_citations,
                found=True,
                sources=final_sources,
            )

        except Exception as err:
            logger.warning("Falha ao gerar resposta via Ollama JSON: %s. Tentando extração de fallback...", err)
            return RagAnswer(
                answer=f"Não foi possível formular a resposta devido a erro na IA: {err}",
                citations=[],
                found=False,
                sources=[],
            )
