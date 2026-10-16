"""
Módulo Nativo de Métricas de Transcrição e Levenshtein (Fase P5)
Implementação 100% nativa em Python (sem dependências de compiladores C++ externas)
para cálculo de Word Error Rate (WER), Character Error Rate (CER),
normalização de texto corporativo em português e alinhamento visual de erros.
"""

import re
import unicodedata
from typing import Dict, Any, List, Tuple


def normalize_portuguese_text(text: str, preserve_accents: bool = True) -> str:
    """
    Normaliza o texto para avaliação padronizada de ASR (Speech-to-Text):
    - Converte para minúsculas.
    - Remove pontuações (.,;!?:()[]{}"'«»-_/\\|).
    - Opcionalmente normaliza caracteres acentuados.
    - Colapsa espaços múltiplos e remove espaços nas bordas.
    """
    if not text:
        return ""

    text = text.lower()

    if not preserve_accents:
        # Decompõe e remove acentos
        nfkd = unicodedata.normalize("NFKD", text)
        text = "".join([c for c in nfkd if not unicodedata.combining(c)])

    # Remove pontuações e caracteres de formatação, preservando letras e números
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    # Colapsa múltiplos espaços em um único
    text = re.sub(r"\s+", " ", text).strip()

    return text


def levenshtein_distance(
    seq_ref: List[str], seq_hyp: List[str]
) -> Tuple[int, int, int, int, List[Tuple[str, str, str]]]:
    """
    Executa o algoritmo de Wagner-Fischer com backtracking para encontrar o alinhamento
    ótimo entre seq_ref e seq_hyp.
    Retorna: (substitutions, deletions, insertions, hits, alignment_ops)
    onde alignment_ops é uma lista de tuplas (op, ref_item, hyp_item)
    com op in {"OK", "SUB", "DEL", "INS"}.
    """
    n = len(seq_ref)
    m = len(seq_hyp)

    # Matriz de custos de edição: dp[i][j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        ref_item = seq_ref[i - 1]
        for j in range(1, m + 1):
            hyp_item = seq_hyp[j - 1]
            if ref_item == hyp_item:
                cost = 0
            else:
                cost = 1

            dp[i][j] = min(
                dp[i - 1][j] + 1,        # Deleção de ref
                dp[i][j - 1] + 1,        # Inserção de hyp
                dp[i - 1][j - 1] + cost  # Match ou Substituição
            )

    # Backtracking para reconstruir operações
    i, j = n, m
    ops_reversed = []
    substitutions = 0
    deletions = 0
    insertions = 0
    hits = 0

    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] and seq_ref[i - 1] == seq_hyp[j - 1]:
            ops_reversed.append(("OK", seq_ref[i - 1], seq_hyp[j - 1]))
            hits += 1
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops_reversed.append(("SUB", seq_ref[i - 1], seq_hyp[j - 1]))
            substitutions += 1
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops_reversed.append(("DEL", seq_ref[i - 1], "*"))
            deletions += 1
            i -= 1
        else:
            ops_reversed.append(("INS", "*", seq_hyp[j - 1]))
            insertions += 1
            j -= 1

    alignment_ops = list(reversed(ops_reversed))
    return substitutions, deletions, insertions, hits, alignment_ops


def compute_wer(
    reference: str, hypothesis: str, normalize: bool = True
) -> Dict[str, Any]:
    """
    Calcula a taxa de erro de palavras (Word Error Rate - WER):
    WER = (Substituições + Deleções + Inserções) / Total_de_Palavras_da_Referência.
    """
    if normalize:
        ref_clean = normalize_portuguese_text(reference)
        hyp_clean = normalize_portuguese_text(hypothesis)
    else:
        ref_clean = reference.strip()
        hyp_clean = hypothesis.strip()

    ref_words = ref_clean.split() if ref_clean else []
    hyp_words = hyp_clean.split() if hyp_clean else []

    n = len(ref_words)
    m = len(hyp_words)

    if n == 0:
        if m == 0:
            return {
                "wer": 0.0,
                "wer_pct": 0.0,
                "substitutions": 0,
                "deletions": 0,
                "insertions": 0,
                "hits": 0,
                "ref_words_count": 0,
                "hyp_words_count": 0,
                "alignment": [],
            }
        else:
            return {
                "wer": 1.0,
                "wer_pct": 100.0,
                "substitutions": 0,
                "deletions": 0,
                "insertions": m,
                "hits": 0,
                "ref_words_count": 0,
                "hyp_words_count": m,
                "alignment": [("INS", "*", w) for w in hyp_words],
            }

    substitutions, deletions, insertions, hits, alignment_ops = levenshtein_distance(
        ref_words, hyp_words
    )

    total_errors = substitutions + deletions + insertions
    wer = total_errors / n
    wer_pct = round(wer * 100.0, 2)

    return {
        "wer": round(wer, 4),
        "wer_pct": wer_pct,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "hits": hits,
        "ref_words_count": n,
        "hyp_words_count": m,
        "alignment": alignment_ops,
    }


def compute_cer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """
    Calcula a taxa de erro de caracteres (Character Error Rate - CER):
    CER = (Substituições + Deleções + Inserções de caracteres) / Total_de_Caracteres_da_Referência.
    """
    if normalize:
        ref_clean = normalize_portuguese_text(reference)
        hyp_clean = normalize_portuguese_text(hypothesis)
    else:
        ref_clean = reference.strip()
        hyp_clean = hypothesis.strip()

    ref_chars = list(ref_clean)
    hyp_chars = list(hyp_clean)

    n = len(ref_chars)
    if n == 0:
        return 0.0 if len(hyp_chars) == 0 else 1.0

    s, d, i, _, _ = levenshtein_distance(ref_chars, hyp_chars)
    cer = (s + d + i) / n
    return round(cer, 4)


def format_alignment_diff(
    reference: str, hypothesis: str, max_cols: int = 70
) -> str:
    """
    Formata visualmente as diferenças entre a referência e a hipótese
    em blocos legíveis de comparação (REF / HYP / OP).
    """
    res = compute_wer(reference, hypothesis, normalize=True)
    alignment = res["alignment"]

    if not alignment:
        return "Nenhum dado para alinhar."

    blocks = []
    current_ref = []
    current_hyp = []
    current_ops = []
    current_len = 0

    for op, ref_w, hyp_w in alignment:
        col_width = max(len(ref_w), len(hyp_w), len(op)) + 1
        if current_len + col_width > max_cols and current_ref:
            blocks.append(
                f"REF: {''.join(current_ref)}\n"
                f"HYP: {''.join(current_hyp)}\n"
                f"OP : {''.join(current_ops)}\n"
            )
            current_ref = []
            current_hyp = []
            current_ops = []
            current_len = 0

        current_ref.append(ref_w.ljust(col_width))
        current_hyp.append(hyp_w.ljust(col_width))
        current_ops.append(op.ljust(col_width))
        current_len += col_width

    if current_ref:
        blocks.append(
            f"REF: {''.join(current_ref)}\n"
            f"HYP: {''.join(current_hyp)}\n"
            f"OP : {''.join(current_ops)}\n"
        )

    summary = (
        f"Métricas: WER = {res['wer_pct']}% | "
        f"Substituições: {res['substitutions']} | "
        f"Deleções: {res['deletions']} | "
        f"Inserções: {res['insertions']} | "
        f"Acertos: {res['hits']} / {res['ref_words_count']}"
    )

    return f"{summary}\n\n" + "\n".join(blocks)
