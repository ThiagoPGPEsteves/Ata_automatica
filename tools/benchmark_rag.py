"""
Ferramenta CLI de Avaliação e Benchmark Científico do RAG (Fase P4)
Mede cientificamente Recall@1/3/6, MRR, acurácia de citações, rejeição de alucinação (found=false),
latências detalhadas (embedding, busca vetorial, LLM) e consumo consolidado de memória RAM (App + Ollama).
"""

import sys
import os
import json
import time
import shutil
import tempfile
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# Garante raiz do projeto no sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import numpy as np

from src.config import MAX_RAM_ALLOWED_MB, OLLAMA_EMBED_MODEL, OLLAMA_MODEL
from src.pipeline.session import MeetingSession
from src.rag.chunker import DocumentChunk, SessionChunker
from src.rag.embedder import OllamaEmbedder
from src.rag.store import VectorStore, SearchResult
from src.rag.retriever import RagRetriever
from src.rag.answerer import RagAnswerer, RagAnswer
from src.rag.service import RagService
from src.utils.telemetry import SystemMemoryAuditor


def is_chunk_relevant(chunk: DocumentChunk, query_meta: Dict[str, Any]) -> bool:
    """
    Verifica se um chunk recuperado corresponde ao ground truth esperado para a pergunta.
    """
    expected_session = query_meta.get("session_id")
    if not expected_session or chunk.session_id != expected_session:
        return False

    # 1. Sobreposição temporal com o intervalo da pergunta (para transcrições)
    time_interval = query_meta.get("time_interval")
    if time_interval and chunk.start_sec is not None and chunk.end_sec is not None:
        q_start, q_end = time_interval
        # Checa sobreposição positiva entre [chunk.start_sec, chunk.end_sec] e [q_start, q_end]
        overlap_start = max(chunk.start_sec, q_start)
        overlap_end = min(chunk.end_sec, q_end)
        if overlap_start <= overlap_end:
            return True

    # 2. Correspondência semântica por palavras-chave fundamentais
    keywords = query_meta.get("keywords", [])
    chunk_text_lower = chunk.text.lower()
    for kw in keywords:
        if kw.lower() in chunk_text_lower:
            return True

    return False


def run_rag_benchmark(
    eval_file: Path,
    output_file: Path,
    retrieval_only: bool = False,
    top_k: int = 6,
    sample_llm: int = 6,
    keep_temp: bool = False,
) -> Dict[str, Any]:
    print("\n" + "=" * 88)
    print("  BENCHMARK CIENTÍFICO E AVALIAÇÃO DE RAG - ATA AUTOMÁTICA")
    print(f"  Dataset de Avaliação: {eval_file.resolve()}")
    print("=" * 88)

    if not eval_file.exists():
        raise FileNotFoundError(f"Arquivo de avaliação não encontrado: {eval_file}")

    with open(eval_file, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    sessions_data = eval_data.get("sessions", [])
    queries_data = eval_data.get("queries", [])

    print(f"\n• Especificações da Bateria de Testes:")
    print(f"  - Sessões sintéticas de teste: {len(sessions_data)}")
    print(f"  - Perguntas totais: {len(queries_data)}")
    answerable_queries = [q for q in queries_data if q.get("expected_found", True)]
    unanswerable_queries = [q for q in queries_data if not q.get("expected_found", True)]
    print(f"    * Perguntas com resposta fundamentada: {len(answerable_queries)}")
    print(f"    * Perguntas sem resposta (rejeição de alucinação): {len(unanswerable_queries)}")
    print(f"  - Modelo de Embeddings: {OLLAMA_EMBED_MODEL}")
    print(f"  - Modelo de Síntese LLM: {OLLAMA_MODEL if not retrieval_only else 'Desativado (--retrieval-only)'}")

    auditor = SystemMemoryAuditor()
    init_mem = auditor.get_total_pipeline_ram_mb()
    print(f"\n• Auditoria de Memória Inicial:")
    print(f"  - RAM App Python: {init_mem['app_mb']:.1f} MB")
    print(f"  - RAM Ollama daemon: {init_mem['ollama_mb']:.1f} MB")
    print(f"  - RAM Total Pipeline: {init_mem['total_pipeline_mb']:.1f} MB")
    print(f"  - Teto Regulatório (Budget): {MAX_RAM_ALLOWED_MB} MB")

    # Cria ambiente isolado para o benchmark
    temp_dir = Path(tempfile.mkdtemp(prefix="ata_rag_bench_"))
    db_path = temp_dir / "benchmark_rag.sqlite"

    try:
        # 1. Cria as pastas das sessões e grava transcript.json e minutes.json
        print(f"\n• Preparando sessões no diretório temporário isolado: {temp_dir.name}...")
        created_sessions: List[MeetingSession] = []
        for s_info in sessions_data:
            s_id = s_info["session_id"]
            s_dir = temp_dir / s_id
            s_dir.mkdir(parents=True, exist_ok=True)

            with open(s_dir / "transcript.json", "w", encoding="utf-8") as tf:
                json.dump(s_info["transcript"], tf, ensure_ascii=False, indent=2)

            with open(s_dir / "minutes.json", "w", encoding="utf-8") as mf:
                json.dump(s_info["minutes"], mf, ensure_ascii=False, indent=2)

            created_sessions.append(MeetingSession(s_id, s_dir))

        # 2. Inicializa componentes RAG apontando para o DB temporário
        store = VectorStore(db_path=db_path)
        embedder = OllamaEmbedder()
        answerer = RagAnswerer()
        retriever = RagRetriever(embedder=embedder, store=store, default_min_similarity=0.30)
        service = RagService(embedder=embedder, store=store, answerer=answerer)

        # 3. Fase de Indexação e Medição de Throughput
        print(f"\n• [FASE 1] Indexando {len(created_sessions)} sessões no banco vetorial SQLite...")
        indexing_start = time.time()
        session_indexing_stats = []
        total_chunks = 0

        for session in created_sessions:
            t0 = time.time()
            ok = service.index_session(session, force=True)
            elapsed = time.time() - t0

            # Conta chunks gravados
            session_chunks = [c for c in service.chunker.chunk_session(session)]
            total_chunks += len(session_chunks)
            session_indexing_stats.append({
                "session_id": session.session_id,
                "chunks": len(session_chunks),
                "elapsed_sec": round(elapsed, 3),
                "success": ok,
            })
            print(f"  ✓ Sessão '{session.session_id}': {len(session_chunks)} chunks vetorizados em {elapsed:.2f}s")

        total_indexing_time = time.time() - indexing_start
        throughput = total_chunks / total_indexing_time if total_indexing_time > 0 else 0
        mem_after_index = auditor.get_total_pipeline_ram_mb()
        print(f"  ➜ Total indexado: {total_chunks} chunks em {total_indexing_time:.2f}s ({throughput:.1f} chunks/s)")
        print(f"  ➜ RAM pós-indexação: {mem_after_index['total_pipeline_mb']:.1f} MB (App: {mem_after_index['app_mb']:.1f} MB, Ollama: {mem_after_index['ollama_mb']:.1f} MB)")

        # 4. Fase de Recuperação Semântica (Recall@k, MRR, Latência de Busca)
        print(f"\n• [FASE 2] Avaliando Recuperação Semântica ({len(answerable_queries)} perguntas com ground truth)...")
        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_6 = 0
        reciprocal_ranks = []
        embed_latencies_ms = []
        search_latencies_ms = []
        query_eval_results = []

        for q in answerable_queries:
            q_id = q["id"]
            question = q["question"]

            # Mede tempo de embedding da query isolado
            t_emb_0 = time.time()
            q_vecs = embedder.embed([question])
            t_emb_ms = (time.time() - t_emb_0) * 1000.0
            embed_latencies_ms.append(t_emb_ms)

            # Mede tempo de busca no SQLite exata
            t_search_0 = time.time()
            q_vec = q_vecs[0] if len(q_vecs) > 0 else np.zeros(768, dtype=np.float32)
            candidates = store.search(query_vec=q_vec, k=top_k)
            t_search_ms = (time.time() - t_search_0) * 1000.0
            search_latencies_ms.append(t_search_ms)

            # Avalia relevância por rank
            first_hit_rank: Optional[int] = None
            retrieved_chunk_summaries = []

            for rank_idx, res in enumerate(candidates, start=1):
                is_hit = is_chunk_relevant(res.chunk, q)
                retrieved_chunk_summaries.append({
                    "rank": rank_idx,
                    "session_id": res.chunk.session_id,
                    "source": res.chunk.source,
                    "score": round(res.score, 4),
                    "is_hit": is_hit,
                    "preview": res.chunk.text[:80],
                })
                if is_hit and first_hit_rank is None:
                    first_hit_rank = rank_idx

            if first_hit_rank == 1:
                hits_at_1 += 1
            if first_hit_rank is not None and first_hit_rank <= 3:
                hits_at_3 += 1
            if first_hit_rank is not None and first_hit_rank <= 6:
                hits_at_6 += 1

            rr = (1.0 / first_hit_rank) if first_hit_rank is not None else 0.0
            reciprocal_ranks.append(rr)

            query_eval_results.append({
                "id": q_id,
                "question": question,
                "expected_session": q.get("session_id"),
                "first_hit_rank": first_hit_rank,
                "reciprocal_rank": round(rr, 4),
                "embed_latency_ms": round(t_emb_ms, 2),
                "search_latency_ms": round(t_search_ms, 2),
                "retrieved": retrieved_chunk_summaries,
                "_candidates": candidates,
            })

            rank_disp = f"Rank {first_hit_rank}" if first_hit_rank else "MISS"
            print(f"  [{q_id}] {question[:50]}... -> {rank_disp} (Emb: {t_emb_ms:.1f}ms, Busca: {t_search_ms:.1f}ms)")

        num_answerable = len(answerable_queries)
        recall_1 = (hits_at_1 / num_answerable) * 100.0 if num_answerable > 0 else 0.0
        recall_3 = (hits_at_3 / num_answerable) * 100.0 if num_answerable > 0 else 0.0
        recall_6 = (hits_at_6 / num_answerable) * 100.0 if num_answerable > 0 else 0.0
        mrr = float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0
        avg_embed_ms = float(np.mean(embed_latencies_ms)) if embed_latencies_ms else 0.0
        avg_search_ms = float(np.mean(search_latencies_ms)) if search_latencies_ms else 0.0

        print(f"\n  ➜ Resultados de Recuperação:")
        print(f"    - Recall@1: {recall_1:.1f}% ({hits_at_1}/{num_answerable})")
        print(f"    - Recall@3: {recall_3:.1f}% ({hits_at_3}/{num_answerable})")
        print(f"    - Recall@6: {recall_6:.1f}% ({hits_at_6}/{num_answerable})")
        print(f"    - MRR (Mean Reciprocal Rank): {mrr:.4f}")
        print(f"    - Latência Média de Embedding: {avg_embed_ms:.2f} ms")
        print(f"    - Latência Média de Busca SQLite: {avg_search_ms:.2f} ms")

        # 5. Fase de Síntese e Geração LLM (Acurácia de Citação e Rejeição de Alucinação)
        citation_valid_count = 0
        unanswerable_rejected_count = 0
        gen_latencies_sec = []
        peak_total_ram_mb = init_mem["total_pipeline_mb"]
        peak_app_ram_mb = init_mem["app_mb"]
        peak_ollama_ram_mb = init_mem["ollama_mb"]

        if not retrieval_only:
            print(f"\n• [FASE 3] Avaliando Síntese LLM e Rejeição com '{OLLAMA_MODEL}'...")

            # Seleciona perguntas para síntese LLM (todas ou amostra balanceada)
            if sample_llm and 0 < sample_llm < len(query_eval_results):
                # Amostra balanceada com 2 perguntas de cada uma das 3 sessões
                preferred_ids = ["q01", "q03", "q05", "q07", "q09", "q11"]
                eval_answerable = [q for q in query_eval_results if q["id"] in preferred_ids][:sample_llm]
                print(f"  (Modo Amostral Ágil: avaliando {len(eval_answerable)} perguntas respondíveis balanceadas + {len(unanswerable_queries)} irrespondíveis)")
            else:
                eval_answerable = query_eval_results

            # 5.1 Teste de perguntas respondíveis
            for q_eval in eval_answerable:
                q_id = q_eval["id"]
                question = q_eval["question"]
                expected_session = q_eval["expected_session"]
                candidates = q_eval.get("_candidates", [])

                t_gen_0 = time.time()
                # Utiliza os chunks mais relevantes recuperados na Fase 2
                answer: RagAnswer = service.answerer.answer(
                    query=question,
                    results=candidates[:top_k] if candidates else service.retriever.retrieve(question, k=top_k),
                )
                elapsed_gen = time.time() - t_gen_0
                gen_latencies_sec.append(elapsed_gen)

                # Monitora pico de memória
                curr_mem = auditor.get_total_pipeline_ram_mb()
                peak_total_ram_mb = max(peak_total_ram_mb, curr_mem["total_pipeline_mb"])
                peak_app_ram_mb = max(peak_app_ram_mb, curr_mem["app_mb"])
                peak_ollama_ram_mb = max(peak_ollama_ram_mb, curr_mem["ollama_mb"])

                # Validação de citações:
                # Considera válida se found=True, possui citações válidas e ao menos uma corresponde à reunião correta
                has_citations = len(answer.citations) > 0
                source_dict = {s.id: s for s in answer.sources}
                all_citations_in_sources = all(c in source_dict for c in answer.citations)
                has_valid_source_match = any(
                    source_dict[c].session_id == expected_session
                    for c in answer.citations
                    if c in source_dict
                )

                valid_citation = (
                    answer.found
                    and has_citations
                    and all_citations_in_sources
                    and has_valid_source_match
                )
                if valid_citation:
                    citation_valid_count += 1

                q_eval["generation"] = {
                    "found": answer.found,
                    "citations": answer.citations,
                    "valid_citation": valid_citation,
                    "elapsed_sec": round(elapsed_gen, 2),
                    "answer_preview": answer.answer[:100],
                }

                cit_status = f"✓ Citações {answer.citations}" if valid_citation else f"✗ Citações inválidas/ausentes ({answer.citations})"
                print(f"  [{q_id}] {question[:45]}... -> {cit_status} em {elapsed_gen:.2f}s")

            # 5.2 Teste de perguntas irrespondíveis (ground truth found = False)
            print(f"\n  Testando {len(unanswerable_queries)} perguntas fora do escopo (Rejeição de Alucinações)...")
            unanswerable_eval_results = []
            for q_unans in unanswerable_queries:
                q_id = q_unans["id"]
                question = q_unans["question"]

                t_gen_0 = time.time()
                answer = service.ask(question, top_k=top_k)
                elapsed_gen = time.time() - t_gen_0
                gen_latencies_sec.append(elapsed_gen)

                curr_mem = auditor.get_total_pipeline_ram_mb()
                peak_total_ram_mb = max(peak_total_ram_mb, curr_mem["total_pipeline_mb"])
                peak_app_ram_mb = max(peak_app_ram_mb, curr_mem["app_mb"])
                peak_ollama_ram_mb = max(peak_ollama_ram_mb, curr_mem["ollama_mb"])

                is_correctly_rejected = (
                    (not answer.found)
                    or ("não encontrei" in answer.answer.lower())
                )
                if is_correctly_rejected:
                    unanswerable_rejected_count += 1

                unanswerable_eval_results.append({
                    "id": q_id,
                    "question": question,
                    "found": answer.found,
                    "is_correctly_rejected": is_correctly_rejected,
                    "elapsed_sec": round(elapsed_gen, 2),
                    "answer_preview": answer.answer[:100],
                })
                status_str = "✓ Rejeitou corretamente" if is_correctly_rejected else "✗ Alucinou resposta"
                print(f"  [{q_id}] {question[:45]}... -> {status_str} em {elapsed_gen:.2f}s")

            citation_acc = (citation_valid_count / len(eval_answerable)) * 100.0 if eval_answerable else 0.0
            unanswerable_acc = (unanswerable_rejected_count / len(unanswerable_queries)) * 100.0 if unanswerable_queries else 0.0
            avg_gen_s = float(np.mean(gen_latencies_sec)) if gen_latencies_sec else 0.0

            print(f"\n  ➜ Resultados de Síntese:")
            print(f"    - Acurácia de Citações: {citation_acc:.1f}% ({citation_valid_count}/{len(eval_answerable)})")
            print(f"    - Acurácia de Rejeição de Alucinação (found=false): {unanswerable_acc:.1f}% ({unanswerable_rejected_count}/{len(unanswerable_queries)})")
            print(f"    - Tempo Médio de Geração LLM: {avg_gen_s:.2f} s")
        else:
            citation_acc = 0.0
            unanswerable_acc = 0.0
            avg_gen_s = 0.0
            unanswerable_eval_results = []

        total_avg_query_s = (avg_embed_ms + avg_search_ms) / 1000.0 + avg_gen_s
        ram_budget_respected = peak_total_ram_mb <= MAX_RAM_ALLOWED_MB

        # 6. Tabela Consolidada de Resultados
        print("\n" + "=" * 88)
        print("  RESUMO EXECUTIVO DO BENCHMARK RAG (Métricas Finais)")
        print("=" * 88)
        print(f"  • Recall@1:                          {recall_1:6.1f} %  (Top 1 contém a fonte correta)")
        print(f"  • Recall@3:                          {recall_3:6.1f} %  (Top 3 contém a fonte correta)")
        print(f"  • Recall@6:                          {recall_6:6.1f} %  (Top 6 contém a fonte correta)")
        print(f"  • MRR (Mean Reciprocal Rank):        {mrr:6.4f}    (Qualidade do ordenamento semântico)")
        if not retrieval_only:
            print(f"  • Acurácia de Citação Válida:        {citation_acc:6.1f} %  (Citações [F1, F2] fundamentadas)")
            print(f"  • Rejeição de Alucinação:           {unanswerable_acc:6.1f} %  (found=false para fora de escopo)")
        print(f"  • Latência Média Embedding:          {avg_embed_ms:6.2f} ms (nomic-embed-text via Ollama)")
        print(f"  • Latência Média Busca SQLite:       {avg_search_ms:6.2f} ms (NumPy Cosine Similarity)")
        if not retrieval_only:
            print(f"  • Latência Média LLM:                {avg_gen_s:6.2f} s  (Llama 3.2 3B com schema JSON)")
            print(f"  • Tempo Médio Total por Pergunta:    {total_avg_query_s:6.2f} s")
        print(f"  • Pico de RAM do App Python:         {peak_app_ram_mb:6.1f} MB")
        print(f"  • Pico de RAM do Ollama:             {peak_ollama_ram_mb:6.1f} MB")
        print(f"  • Pico Consolidado de RAM:           {peak_total_ram_mb:6.1f} MB / {MAX_RAM_ALLOWED_MB} MB")
        print(f"  • Status do Orçamento de RAM:        {'APROVADO (Dentro do limite de 4GB)' if ram_budget_respected else 'REPROVADO'}")
        print("=" * 88)

        # 7. Salva resultado em JSON para consumo e reprodutibilidade
        benchmark_results = {
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "eval_file": str(eval_file.resolve()),
                "sessions_evaluated": len(sessions_data),
                "total_queries": len(queries_data),
                "answerable_queries": len(answerable_queries),
                "unanswerable_queries": len(unanswerable_queries),
                "embed_model": OLLAMA_EMBED_MODEL,
                "llm_model": OLLAMA_MODEL if not retrieval_only else None,
                "retrieval_only": retrieval_only,
            },
            "retrieval_metrics": {
                "recall_at_1": round(recall_1, 2),
                "recall_at_3": round(recall_3, 2),
                "recall_at_6": round(recall_6, 2),
                "mrr": round(mrr, 4),
                "hits_at_1": hits_at_1,
                "hits_at_3": hits_at_3,
                "hits_at_6": hits_at_6,
                "total_evaluated": num_answerable,
            },
            "generation_metrics": {
                "citation_accuracy": round(citation_acc, 2),
                "citation_valid_count": citation_valid_count,
                "unanswerable_accuracy": round(unanswerable_acc, 2),
                "unanswerable_rejected_count": unanswerable_rejected_count,
                "total_unanswerable": len(unanswerable_queries),
            },
            "latency_metrics": {
                "avg_embed_latency_ms": round(avg_embed_ms, 2),
                "avg_search_latency_ms": round(avg_search_ms, 2),
                "avg_gen_latency_sec": round(avg_gen_s, 2),
                "total_avg_query_sec": round(total_avg_query_s, 2),
            },
            "memory_metrics": {
                "initial_total_ram_mb": round(init_mem["total_pipeline_mb"], 1),
                "peak_app_ram_mb": round(peak_app_ram_mb, 1),
                "peak_ollama_ram_mb": round(peak_ollama_ram_mb, 1),
                "peak_total_ram_mb": round(peak_total_ram_mb, 1),
                "budget_max_ram_mb": MAX_RAM_ALLOWED_MB,
                "ram_budget_respected": ram_budget_respected,
            },
            "indexing_metrics": {
                "total_chunks": total_chunks,
                "total_indexing_time_sec": round(total_indexing_time, 2),
                "throughput_chunks_per_sec": round(throughput, 2),
                "sessions": session_indexing_stats,
            },
            "queries": query_eval_results,
            "unanswerable_queries": unanswerable_eval_results,
        }

        for q in query_eval_results:
            q.pop("_candidates", None)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as out_f:
            json.dump(benchmark_results, out_f, ensure_ascii=False, indent=2)

        print(f"\n✓ Resultados consolidados salvos em: {output_file.resolve()}\n")
        return benchmark_results

    finally:
        if not keep_temp:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Científico e Auditoria de RAG Local (Ata Automática)"
    )
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=ROOT_DIR / "tests" / "fixtures" / "rag_eval.json",
        help="Caminho do arquivo JSON de avaliação com ground truth",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / "tools" / "benchmark_rag_results.json",
        help="Caminho de saída para o JSON de resultados",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Executa apenas a avaliação de recuperação semântica (sem chamar LLM)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Número de candidatos no top-k (padrão: 3)",
    )
    parser.add_argument(
        "--sample-llm",
        type=int,
        default=6,
        help="Quantidade de perguntas respondíveis a avaliar com LLM (padrão: 6; use 0 para todas as 15)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Mantém diretório e banco temporários após a execução",
    )
    args = parser.parse_args()

    run_rag_benchmark(
        eval_file=args.eval_file,
        output_file=args.output,
        retrieval_only=args.retrieval_only,
        top_k=args.top_k,
        sample_llm=args.sample_llm,
        keep_temp=args.keep_temp,
    )


if __name__ == "__main__":
    main()
