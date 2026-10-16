"""
Bateria de Testes Automatizados para Métricas de Transcrição e Levenshtein (Fase P5)
Valida a precisão matemática do Word Error Rate (WER), Character Error Rate (CER),
normalização corporativa de texto em português e alinhamento visual de erros.
"""

import pytest
from src.utils.text_metrics import (
    normalize_portuguese_text,
    levenshtein_distance,
    compute_wer,
    compute_cer,
    format_alignment_diff,
)


@pytest.mark.unit
def test_normalize_portuguese_text():
    # 1. Pontuação e maiúsculas
    raw = "Olá, mundo! Como vai a reunião de 16/10? (Tudo bem)."
    norm = normalize_portuguese_text(raw)
    assert norm == "olá mundo como vai a reunião de 16 10 tudo bem"

    # 2. Espaços múltiplos e quebras de linha
    raw_spaces = "   alinhamento \n\n de   sprint\t\t "
    assert normalize_portuguese_text(raw_spaces) == "alinhamento de sprint"

    # 3. String vazia
    assert normalize_portuguese_text("") == ""
    assert normalize_portuguese_text(None) == ""


@pytest.mark.unit
def test_wer_identical_strings():
    ref = "reunião de alinhamento com a diretoria"
    hyp = "reunião de alinhamento com a diretoria"
    res = compute_wer(ref, hyp)

    assert res["wer"] == 0.0
    assert res["wer_pct"] == 0.0
    assert res["substitutions"] == 0
    assert res["deletions"] == 0
    assert res["insertions"] == 0
    assert res["hits"] == 6
    assert res["ref_words_count"] == 6


@pytest.mark.unit
def test_wer_complete_deletion_and_insertion():
    ref = "um dois três quatro"
    hyp = ""
    res = compute_wer(ref, hyp)
    assert res["wer"] == 1.0
    assert res["wer_pct"] == 100.0
    assert res["deletions"] == 4
    assert res["hits"] == 0

    # Inserção total sobre referência vazia
    res_ins = compute_wer("", "um dois")
    assert res_ins["wer"] == 1.0
    assert res_ins["insertions"] == 2


@pytest.mark.unit
def test_wer_substitutions_and_corporate_names():
    # Caso típico reportado em reunião: troca de nomes próprios
    ref = "alinhamento com Cássio e Daniel sobre o projeto"
    # Whisper sem hotwords confundiu: Cássia e Gabriel
    hyp = "alinhamento com Cássia e Gabriel sobre o projeto"

    res = compute_wer(ref, hyp)
    # Total de palavras na referência: 8 ("alinhamento", "com", "cássio", "e", "daniel", "sobre", "o", "projeto")
    # Substituições: 2 ("cássio" -> "cássia", "daniel" -> "gabriel")
    # Erro esperado: 2 / 8 = 0.25 (25%)
    assert res["ref_words_count"] == 8
    assert res["substitutions"] == 2
    assert res["deletions"] == 0
    assert res["insertions"] == 0
    assert res["hits"] == 6
    assert res["wer"] == 0.25
    assert res["wer_pct"] == 25.0


@pytest.mark.unit
def test_cer_calculation():
    ref = "casa"
    hyp = "capa"  # 1 substituição em 4 caracteres -> 25%
    cer = compute_cer(ref, hyp)
    assert cer == 0.25

    # Idênticos
    assert compute_cer("teste unitario", "teste unitario") == 0.0


@pytest.mark.unit
def test_format_alignment_diff():
    ref = "Cássio falou com Daniel"
    hyp = "Cássia falou com Gabriel agora"
    diff_text = format_alignment_diff(ref, hyp)

    assert "REF:" in diff_text
    assert "HYP:" in diff_text
    assert "OP :" in diff_text
    assert "SUB" in diff_text
    assert "INS" in diff_text
    assert "WER = " in diff_text
