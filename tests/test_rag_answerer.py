"""
Testes Unitários do RagAnswerer (pytest marker: unit)
Valida a geração de respostas com OllamaClient simulado, parsing robusto de JSON,
descarte de citações alucinadas e tratamento de casos 'não encontrado'.
"""

from unittest.mock import MagicMock
import pytest

from src.rag.answerer import RagAnswerer, RagAnswer, NOT_FOUND_MESSAGE
from src.rag.store import SearchResult
from src.rag.chunker import DocumentChunk


@pytest.fixture
def sample_search_results() -> list[SearchResult]:
    c1 = DocumentChunk(
        chunk_id="s1_c1",
        session_id="2026-10-15_100000",
        source="transcript",
        start_sec=120.0,
        end_sec=180.0,
        speakers=["Thiago"],
        text="Definimos que o prazo final do projeto será dia 15 de novembro.",
    )
    c2 = DocumentChunk(
        chunk_id="s1_c2",
        session_id="2026-10-15_100000",
        source="minutes",
        start_sec=200.0,
        end_sec=200.0,
        speakers=["Diretoria"],
        text="Ata: Orçamento fixado em 50 mil reais.",
    )
    return [SearchResult(chunk=c1, score=0.88), SearchResult(chunk=c2, score=0.75)]


@pytest.mark.unit
def test_answerer_valid_json_with_citations(sample_search_results):
    mock_client = MagicMock()
    mock_client.generate.return_value = (
        '{"answer": "O prazo final do projeto foi fixado para 15 de novembro [F1].", '
        '"citations": ["F1"], "found": true}'
    )

    answerer = RagAnswerer(ollama_client=mock_client)
    res = answerer.answer("Qual o prazo do projeto?", sample_search_results)

    assert res.found is True
    assert "15 de novembro" in res.answer
    assert res.citations == ["F1"]
    assert len(res.sources) == 1
    assert res.sources[0].id == "F1"
    assert res.sources[0].session_id == "2026-10-15_100000"


@pytest.mark.unit
def test_answerer_discards_hallucinated_citations(sample_search_results):
    # O LLM alucina [F99] e [F500] que não constam nas fontes (apenas F1 e F2 foram fornecidas)
    mock_client = MagicMock()
    mock_client.generate.return_value = (
        '{"answer": "Aprovado conforme [F1] e [F99].", '
        '"citations": ["F1", "F99", "F500"], "found": true}'
    )

    answerer = RagAnswerer(ollama_client=mock_client)
    res = answerer.answer("Qual o status?", sample_search_results)

    assert res.found is True
    assert res.citations == ["F1"]  # F99 e F500 foram eliminadas
    assert len(res.sources) == 1
    assert res.sources[0].id == "F1"


@pytest.mark.unit
def test_answerer_handles_markdown_json_wrapper(sample_search_results):
    mock_client = MagicMock()
    mock_client.generate.return_value = (
        "```json\n"
        '{"answer": "O orçamento é de 50 mil reais [F2].", "citations": ["F2"], "found": true}\n'
        "```"
    )

    answerer = RagAnswerer(ollama_client=mock_client)
    res = answerer.answer("Qual o orçamento?", sample_search_results)

    assert res.found is True
    assert "50 mil" in res.answer
    assert res.citations == ["F2"]


@pytest.mark.unit
def test_answerer_not_found_handling(sample_search_results):
    mock_client = MagicMock()
    mock_client.generate.return_value = (
        '{"answer": "' + NOT_FOUND_MESSAGE + '", "citations": [], "found": false}'
    )

    answerer = RagAnswerer(ollama_client=mock_client)
    res = answerer.answer("Qual a previsão do tempo em Tóquio?", sample_search_results)

    assert res.found is False
    assert res.answer == NOT_FOUND_MESSAGE
    assert res.citations == []
    assert res.sources == []


@pytest.mark.unit
def test_answerer_empty_input_returns_immediately_without_calling_llm():
    mock_client = MagicMock()
    answerer = RagAnswerer(ollama_client=mock_client)
    res = answerer.answer("Qualquer pergunta", results=[])

    assert res.found is False
    assert res.answer == NOT_FOUND_MESSAGE
    assert not mock_client.generate.called
