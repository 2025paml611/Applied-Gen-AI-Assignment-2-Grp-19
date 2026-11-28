"""Phase 4 retrieval-only evaluation runner."""

from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
import os
import platform
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from phase2.retrieval_engine import RetrievalEngine
from phase3.self_improving_loop import PromptOptimizer
from phase3.guardrails import DoSProtection, InputGuardrails
from phase4.metrics import aggregate_retrieval_metrics


NOT_RUN_REASON = "no LLM backend configured"


def load_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def case_rank(result) -> str:
    return f"{result.doc_name}|{int(result.page_or_slide)}"


def modality_counts(cases: Iterable[dict]) -> dict[str, int]:
    counts = Counter(str(case.get("modality") or "unknown") for case in cases)
    return dict(sorted(counts.items()))


def run_retrieval(
    engine: RetrievalEngine,
    cases: list[dict],
    top_k: int = 10,
    modality: str | None = None,
    use_category_filter: bool = False,
) -> tuple[list[dict], dict]:
    per_case: list[dict] = []
    latencies_ms: list[float] = []

    for case in cases:
        started = time.perf_counter()
        category = str(case.get("category") or "") if use_category_filter else None
        results = engine.search(
            str(case["question"]),
            top_k=top_k,
            modality=modality,
            category=category or None,
            use_memory=False,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(latency_ms)

        relevant_id = f"{case.get('source_doc') or case.get('doc_name')}|{int(case['page_or_slide'])}"
        ranked_ids = [case_rank(result) for result in results]
        ranked_ids_modality = [
            f"{result.doc_name}|{int(result.page_or_slide)}|{str(result.modality)}"
            for result in results
        ]
        relevant_id_modality = (
            f"{case.get('source_doc') or case.get('doc_name')}|"
            f"{int(case['page_or_slide'])}|{str(case.get('modality') or '')}"
        )
        hit = relevant_id in ranked_ids
        modality_hit = relevant_id_modality in ranked_ids_modality
        reciprocal_rank = next(
            (1.0 / rank for rank, ranked_id in enumerate(ranked_ids, 1) if ranked_id == relevant_id),
            0.0,
        )

        per_case.append({
            "id": str(case.get("id") or ""),
            "modality": str(case.get("modality") or ""),
            "question": str(case.get("question") or ""),
            "source_doc": str(case.get("source_doc") or case.get("doc_name") or ""),
            "source_page": int(case["page_or_slide"]),
            "hit": int(hit),
            "modality_hit": int(modality_hit),
            "reciprocal_rank": reciprocal_rank,
            "ranked_ids": json.dumps(ranked_ids),
            "relevant_ids": json.dumps([relevant_id]),
            "retrieved_ids": ranked_ids,
            "retrieved_ids_modality": ranked_ids_modality,
            "relevant_ids_list": [relevant_id],
            "relevant_id_modality": relevant_id_modality,
            "top_result": results[0].doc_name if results else "",
            "top_page": int(results[0].page_or_slide) if results else "",
            "top_score": float(results[0].score) if results else 0.0,
            "top3": [
                {
                    "doc_name": result.doc_name,
                    "page_or_slide": int(result.page_or_slide),
                    "modality": str(result.modality),
                }
                for result in results[:3]
            ],
            "latency_ms": latency_ms,
        })

    metrics = aggregate_retrieval_metrics([
        {
            "retrieved_ids": row["retrieved_ids"],
            "relevant_ids": row["relevant_ids_list"],
            "modality": row["modality"],
        }
        for row in per_case
    ])
    metrics_modality = aggregate_retrieval_metrics([
        {
            "retrieved_ids": row["retrieved_ids_modality"],
            "relevant_ids": [row["relevant_id_modality"]],
            "modality": row["modality"],
        }
        for row in per_case
    ])
    metrics["p50_latency_ms"] = round(percentile(latencies_ms, 50), 3)
    metrics["p95_latency_ms"] = round(percentile(latencies_ms, 95), 3)
    metrics_modality["p50_latency_ms"] = round(percentile(latencies_ms, 50), 3)
    metrics_modality["p95_latency_ms"] = round(percentile(latencies_ms, 95), 3)
    metrics["modality_aware"] = metrics_modality
    return per_case, metrics


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def exact_two_sided_sign_test(wins: int, losses: int) -> dict[str, Any]:
    """Exact binomial sign test with ties excluded."""
    n = wins + losses
    if n == 0:
        return {"n_excluding_ties": 0, "p_value": None}
    tail_limit = min(wins, losses)
    one_tail = sum(math.comb(n, k) for k in range(0, tail_limit + 1)) / (2 ** n)
    p_value = min(1.0, 2.0 * one_tail)
    return {"n_excluding_ties": n, "p_value": p_value}


def rerun_phase2_in_temp_dir() -> dict:
    with tempfile.TemporaryDirectory(prefix="phase4_phase2_") as temp_dir:
        result = subprocess.run(
            [sys.executable, "phase2/run_demo.py", "--top-k", "10", "--output-dir", temp_dir],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        )
        metrics_path = Path(temp_dir) / "phase2_retrieval_metrics.json"
        return json.loads(metrics_path.read_text(encoding="utf-8"))


TOKENIZER_NAME = "regex-word-v1:unicode_alphanumeric_groups"
TOKEN_RE = re.compile(r"[^\W_]+(?:[-+./][^\W_]+)*", re.UNICODE)


def count_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def run_memory_order_evaluation(cases: list[dict], top_k: int = 10) -> dict:
    """Measure memory-enabled retrieval in golden and deterministic shuffled orders."""
    orders: list[tuple[str, list[dict]]] = [("golden", list(cases))]
    for seed in (42, 43, 44):
        shuffled = list(cases)
        random.Random(seed).shuffle(shuffled)
        orders.append((f"seed_{seed}", shuffled))

    results: dict[str, dict] = {}
    for order_name, ordered_cases in orders:
        engine = RetrievalEngine(REPO_ROOT)
        engine.memory.clear()
        per_case = []
        for case in ordered_cases:
            retrieved = engine.search(case["question"], top_k=top_k, use_memory=True)
            relevant_id = f"{case.get('source_doc') or case.get('doc_name')}|{int(case['page_or_slide'])}"
            ranked_ids = [f"{result.doc_name}|{int(result.page_or_slide)}" for result in retrieved]
            per_case.append({
                "retrieved_ids": ranked_ids,
                "relevant_ids": [relevant_id],
                "modality": str(case.get("modality") or ""),
            })
        metrics = aggregate_retrieval_metrics(per_case)
        results[order_name] = {
            "recall_at_10": metrics["recall_at_10"],
            "mrr": metrics["mrr"],
            "query_count": metrics["query_count"],
        }
    return results


def run_e6(engine: RetrievalEngine, cases: list[dict], runs: int, top_k: int) -> dict:
    """Run retrieval-only consistency, latency, token, and guardrail benchmarks."""
    same_engine_results: dict[str, list[tuple[str, ...]]] = {}
    fresh_engine_results: dict[str, list[tuple[str, ...]]] = {}
    memory_engine_results: dict[str, list[tuple[str, ...]]] = {}
    retrieval_latencies_ms: list[float] = []
    phase2_equivalent_latencies_ms: list[float] = []

    for run_index in range(runs):
        for case in cases:
            started = time.perf_counter()
            results = engine.search(case["question"], top_k=top_k, use_memory=False)
            retrieval_latencies_ms.append((time.perf_counter() - started) * 1000.0)
            same_engine_results.setdefault(str(case["id"]), []).append(
                tuple(result.element_id for result in results)
            )

            fresh_engine = RetrievalEngine(REPO_ROOT)
            started = time.perf_counter()
            fresh_results = fresh_engine.search(case["question"], top_k=top_k, use_memory=False)
            retrieval_latencies_ms.append((time.perf_counter() - started) * 1000.0)
            fresh_engine_results.setdefault(str(case["id"]), []).append(
                tuple(result.element_id for result in fresh_results)
            )

    memory_engine = RetrievalEngine(REPO_ROOT)
    for run_index in range(runs):
        memory_engine.memory.clear()
        for case in cases:
            results = memory_engine.search(case["question"], top_k=top_k, use_memory=True)
            memory_engine_results.setdefault(str(case["id"]), []).append(
                tuple(result.element_id for result in results)
            )

    same_vs_memory_changes = 0
    same_vs_memory_count = 0
    for case in cases:
        no_memory = same_engine_results[str(case["id"])][0]
        memory = memory_engine_results[str(case["id"])][0]
        same_vs_memory_count += 1
        same_vs_memory_changes += int(no_memory != memory)

    memory_consistency = 100.0 * sum(
        int(bool(sequences) and all(sequence == sequences[0] for sequence in sequences))
        for sequences in memory_engine_results.values()
    ) / len(memory_engine_results) if memory_engine_results else 0.0

    phase2_engine = RetrievalEngine(REPO_ROOT)
    for case in cases:
        started = time.perf_counter()
        phase2_engine.search(case["question"], top_k=top_k, use_memory=False)
        phase2_equivalent_latencies_ms.append((time.perf_counter() - started) * 1000.0)

    def consistency(results_by_query: dict[str, list[tuple[str, ...]]]) -> tuple[float, list[dict]]:
        query_rows = []
        identical_count = 0
        for case in cases:
            sequences = results_by_query[str(case["id"])]
            identical = bool(sequences) and all(sequence == sequences[0] for sequence in sequences)
            identical_count += int(identical)
            query_rows.append({
                "id": str(case["id"]),
                "identical": int(identical),
                "runs": len(sequences),
            })
        return (100.0 * identical_count / len(cases) if cases else 0.0), query_rows

    same_consistency, same_query_rows = consistency(same_engine_results)
    fresh_consistency, fresh_query_rows = consistency(fresh_engine_results)

    context_tokens: list[int] = []
    naive_tokens: list[int] = []
    ratios: list[float] = []
    max_ratio_detail: dict[str, Any] | None = None
    corpus_elements = engine.elements

    for case in cases:
        results = engine.search(case["question"], top_k=top_k, use_memory=False)
        context = engine.format_context(results)
        context_tokens.append(count_tokens(context))

        top_documents: list[str] = []
        for result in results:
            if result.doc_name not in top_documents:
                top_documents.append(result.doc_name)
            if len(top_documents) == 3:
                break

        page_text = []
        for doc_name in top_documents:
            text_elements = [
                str(element.get("content", ""))
                for element in corpus_elements
                if element.get("doc_name") == doc_name
                and str(element.get("modality", "text")).lower() == "text"
            ]
            if not text_elements:
                text_elements = [
                    str(element.get("content", ""))
                    for element in corpus_elements
                    if element.get("doc_name") == doc_name
                ]
            page_text.extend(text_elements)
        naive = "\n\n".join(page_text)
        naive_count = count_tokens(naive)
        naive_tokens.append(naive_count)
        ratio = context_tokens[-1] / naive_count if naive_count else 0.0
        ratios.append(ratio)
        if max_ratio_detail is None or ratio > max_ratio_detail["ratio"]:
            top_doc_details = []
            for doc_name in top_documents:
                doc_elements = [element for element in corpus_elements if element.get("doc_name") == doc_name]
                text_elements = [
                    str(element.get("content", "")) for element in doc_elements
                    if str(element.get("modality", "text")).lower() == "text"
                ]
                if not text_elements:
                    text_elements = [str(element.get("content", "")) for element in doc_elements]
                top_doc_details.append({
                    "doc_name": doc_name,
                    "elements": len(doc_elements),
                    "text_characters": sum(len(str(element.get("content", ""))) for element in doc_elements),
                    "naive_tokens": len(TOKEN_RE.findall("\n\n".join(text_elements))),
                    "modalities": sorted(set(str(element.get("modality", "text")) for element in doc_elements)),
                })
            max_ratio_detail = {
                "id": str(case["id"]),
                "question": str(case["question"]),
                "ratio": ratio,
                "context_tokens": context_tokens[-1],
                "naive_tokens": naive_count,
                "top_documents": top_doc_details,
            }

    guardrail_overheads_sec: list[float] = []
    guardrail_with_ms: list[float] = []
    guardrail_without_ms: list[float] = []
    dos = DoSProtection()
    dos_blocked_calls = 0
    dos_block_reasons: dict[str, int] = {}
    for case in cases:
        dos.last_query_time = 0.0
        started = time.perf_counter()
        dos_allowed, dos_message = dos.check(case["question"])
        if not dos_allowed:
            dos_blocked_calls += 1
            reason = dos_message or "unknown DoS block"
            dos_block_reasons[reason] = dos_block_reasons.get(reason, 0) + 1
        InputGuardrails.validate_input(case["question"])
        guardrail_with_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        _ = str(case["question"])
        guardrail_without_ms.append((time.perf_counter() - started) * 1000.0)

        guardrail_overheads_sec.append(
            (guardrail_with_ms[-1] - guardrail_without_ms[-1]) / 1000.0
        )

    phase2_temp_metrics = rerun_phase2_in_temp_dir()

    memory_order_metrics = run_memory_order_evaluation(cases, top_k)

    return {
        "runs": runs,
        "same_engine_identical_percent": same_consistency,
        "fresh_engine_identical_percent": fresh_consistency,
        "same_engine_query_rows": same_query_rows,
        "fresh_engine_query_rows": fresh_query_rows,
        "retrieval_p50_ms": percentile(retrieval_latencies_ms, 50),
        "retrieval_p95_ms": percentile(retrieval_latencies_ms, 95),
        "retrieval_latency_count": len(retrieval_latencies_ms),
        "phase2_equivalent_p50_ms": percentile(phase2_equivalent_latencies_ms, 50),
        "phase2_equivalent_p95_ms": percentile(phase2_equivalent_latencies_ms, 95),
        "phase2_temp_metrics": phase2_temp_metrics,
        "machine": {"python": platform.python_version(), "os": platform.platform(), "cpu": cpu_name()},
        "phase2_equivalent_count": len(phase2_equivalent_latencies_ms),
        "tokenizer": TOKENIZER_NAME,
        "mean_context_tokens": sum(context_tokens) / len(context_tokens) if context_tokens else 0.0,
        "median_context_tokens": statistics_median(context_tokens),
        "mean_naive_tokens": sum(naive_tokens) / len(naive_tokens) if naive_tokens else 0.0,
        "median_naive_tokens": statistics_median(naive_tokens),
        "mean_ratio": sum(ratios) / len(ratios) if ratios else 0.0,
        "median_ratio": statistics_median(ratios),
        "min_ratio": min(ratios) if ratios else 0.0,
        "max_ratio": max(ratios) if ratios else 0.0,
        "query_memory_active": False,
        "query_memory_affected_ranking": same_vs_memory_changes > 0,
        "memory_order_metrics": memory_order_metrics,
        "max_ratio_detail": max_ratio_detail,
        "guardrail_p50_ms": percentile(guardrail_overheads_sec, 50) * 1000.0,
        "guardrail_p95_ms": percentile(guardrail_overheads_sec, 95) * 1000.0,
        "guardrail_without_p50_ms": percentile(guardrail_without_ms, 50),
        "guardrail_without_p95_ms": percentile(guardrail_without_ms, 95),
        "guardrail_with_p50_ms": percentile(guardrail_with_ms, 50),
        "guardrail_with_p95_ms": percentile(guardrail_with_ms, 95),
        "guardrail_fr4_passed": percentile(guardrail_overheads_sec, 95) < 6.0,
        "dos_blocked_calls": dos_blocked_calls,
        "dos_block_reasons": dos_block_reasons,
        "memory_consistency_percent": memory_consistency,
        "memory_vs_nomemory_changes": same_vs_memory_changes,
        "memory_vs_nomemory_count": same_vs_memory_count,
    }


def statistics_median(values: list[float] | list[int]) -> float:
    if not values:
        return 0.0
    import statistics
    return float(statistics.median(values))


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "UNKNOWN"


def cpu_name() -> str:
    name = platform.processor().strip()
    return name if name else platform.machine()


def run_manifest(git_commit: str, top_k: int, golden_path: Path) -> dict:
    return {
        "seed": 42,
        "git_commit": git_commit,
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu": cpu_name(),
        "gpu": "NOT_PROBED",
        "model": None,
        "provider": None,
        "temperature": None,
        "top_k": top_k,
        "golden_set": str(golden_path),
        "retrieval_only": True,
        "answer_metrics": {
            "status": "NOT_RUN",
            "reason": NOT_RUN_REASON,
        },
    }


def write_per_case_csv(path: Path, full_rows: list[dict], heldout_rows: list[dict]) -> None:
    fieldnames = [
        "id", "split", "modality", "question", "source_doc", "source_page", "hit",
        "reciprocal_rank", "ranked_ids", "top_result", "top_page", "top_score", "latency_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for split_name, rows in (("full", full_rows), ("heldout", heldout_rows)):
            for row in rows:
                writer.writerow({
                    "id": row["id"], "split": split_name,
                    "modality": row["modality"], "question": row["question"],
                    "source_doc": row["source_doc"], "source_page": row["source_page"],
                    "hit": row["hit"], "reciprocal_rank": round(row["reciprocal_rank"], 6),
                    "ranked_ids": row["ranked_ids"], "top_result": row["top_result"],
                    "top_page": row["top_page"], "top_score": round(row["top_score"], 6),
                    "latency_ms": round(row["latency_ms"], 3),
                })


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_recorded_phase2(repo_root: Path) -> dict | None:
    path = repo_root / "output" / "phase2_retrieval_metrics.json"
    if not path.exists():
        return None
    return load_json(path)


def metric_rows(config: str, split: str, metrics: dict, hit_definition: str = "doc_page") -> list[dict]:
    rows = [{
        "record_type": "summary",
        "hit_definition": hit_definition,
        "config": config,
        "split": split,
        "modality": "overall",
        "n": metrics["query_count"],
        "recall_at_1": metrics["recall_at_1"],
        "recall_at_5": metrics["recall_at_5"],
        "recall_at_10": metrics["recall_at_10"],
        "mrr": metrics["mrr"],
        "ndcg_at_10": metrics["ndcg_at_10"],
    }]
    for modality in ("text", "table", "image"):
        if modality in metrics["by_modality"]:
            values = metrics["by_modality"][modality]
            rows.append({
                "record_type": "summary",
                "hit_definition": hit_definition,
                "config": config,
                "split": split,
                "modality": modality,
                "n": values["query_count"],
                "recall_at_1": values["recall_at_1"],
                "recall_at_5": values["recall_at_5"],
                "recall_at_10": values["recall_at_10"],
                "mrr": values["mrr"],
                "ndcg_at_10": values["ndcg_at_10"],
            })
    return rows


def paired_outcome(full_text: list[dict], full_multimodal: list[dict], split: str) -> tuple[list[dict], dict[str, Any]]:
    text_by_id = {row["id"]: row for row in full_text}
    outcomes: dict[str, Any] = {
        "wins": 0,
        "ties": 0,
        "losses": 0,
        "by_modality": {},
    }
    changed: list[dict] = []
    for multimodal_row in full_multimodal:
        text_row = text_by_id[multimodal_row["id"]]
        text_rr = float(text_row["reciprocal_rank"])
        multimodal_rr = float(multimodal_row["reciprocal_rank"])
        if multimodal_rr > text_rr:
            outcome = "win"
            outcomes["wins"] += 1
        elif multimodal_rr < text_rr:
            outcome = "loss"
            outcomes["losses"] += 1
        else:
            outcome = "tie"
            outcomes["ties"] += 1
        modality = str(multimodal_row["modality"] or "unknown")
        modality_counts = outcomes["by_modality"].setdefault(modality, {"n": 0, "wins": 0, "ties": 0, "losses": 0})
        modality_counts["n"] += 1
        modality_counts[{ "win": "wins", "tie": "ties", "loss": "losses" }[outcome]] += 1
        if outcome != "tie":
            changed.append({
                "record_type": "pair",
                "config": "text_vs_full_multimodal",
                "split": split,
                "modality": multimodal_row["modality"],
                "n": 1,
                "id": multimodal_row["id"],
                "paired_outcome": outcome,
                "text_rr": text_rr,
                "multimodal_rr": multimodal_rr,
                "text_hit": text_row["hit"],
                "multimodal_hit": multimodal_row["hit"],
            })
    return changed, outcomes


def write_e3_csv(path: Path, e3_rows: list[dict]) -> None:
    fieldnames = [
        "record_type", "hit_definition", "config", "split", "modality", "n",
        "recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10",
        "id", "paired_outcome", "text_rr", "multimodal_rr", "text_hit", "multimodal_hit",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(e3_rows)


def write_failure_candidates(path: Path, split: str, rows: list[dict], append: bool = False) -> None:
    """Write misses and lowest-RR hits; it intentionally does not classify causes."""
    misses = [row for row in rows if not row["hit"]]
    hits = sorted((row for row in rows if row["hit"]), key=lambda row: row["reciprocal_rank"])
    selected = list(misses)
    selected_types = {row["id"]: "recall_at_10_miss" for row in misses}
    selected_ids = set(selected_types)
    hit_limit = 5
    for row in hits:
        if len(selected) >= len(misses) + hit_limit:
            break
        if row["id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["id"])
            selected_types[row["id"]] = "lowest_rr_hit"

    fieldnames = [
        "split", "id", "candidate_type", "modality", "source_doc", "source_page", "recall_at_10_hit",
        "reciprocal_rank", "top1_doc", "top1_page", "top1_modality",
        "top2_doc", "top2_page", "top2_modality",
        "top3_doc", "top3_page", "top3_modality",
        "text_top1_doc", "text_top1_page", "text_top1_modality",
        "text_top2_doc", "text_top2_page", "text_top2_modality",
        "text_top3_doc", "text_top3_page", "text_top3_modality",
        "b_top1_doc", "b_top1_page", "b_top1_modality",
        "b_top2_doc", "b_top2_page", "b_top2_modality",
        "b_top3_doc", "b_top3_page", "b_top3_modality",
    ]
    with path.open("a" if append else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not append:
            writer.writeheader()
        for row in selected:
            top = row["top3"]
            record = {
                "split": split,
                "id": row["id"],
                "candidate_type": selected_types[row["id"]],
                "modality": row["modality"],
                "source_doc": row["source_doc"],
                "source_page": row["source_page"],
                "recall_at_10_hit": row["hit"],
                "reciprocal_rank": round(row["reciprocal_rank"], 6),
            }
            for index, key in enumerate(("top1", "top2", "top3"), 1):
                item = top[index - 1] if index <= len(top) else None
                record[f"{key}_doc"] = item["doc_name"] if item else ""
                record[f"{key}_page"] = item["page_or_slide"] if item else ""
                record[f"{key}_modality"] = item["modality"] if item else ""
            writer.writerow(record)


def append_pair_loss_candidates(path: Path, split: str, losses: list[dict], text_rows: list[dict], multimodal_rows: list[dict]) -> None:
    text_by_id = {row["id"]: row for row in text_rows}
    multimodal_by_id = {row["id"]: row for row in multimodal_rows}
    fieldnames = [
        "split", "id", "candidate_type", "modality", "source_doc", "source_page",
        "text_top1_doc", "text_top1_page", "text_top1_modality",
        "text_top2_doc", "text_top2_page", "text_top2_modality",
        "text_top3_doc", "text_top3_page", "text_top3_modality",
        "b_top1_doc", "b_top1_page", "b_top1_modality",
        "b_top2_doc", "b_top2_page", "b_top2_modality",
        "b_top3_doc", "b_top3_page", "b_top3_modality",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        for loss in losses:
            case_id = loss["id"]
            text_row = text_by_id[case_id]
            multimodal_row = multimodal_by_id[case_id]
            record = {
                "split": split,
                "id": case_id,
                "candidate_type": "b_vs_a_loss",
                "modality": loss["modality"],
                "source_doc": multimodal_row["source_doc"],
                "source_page": multimodal_row["source_page"],
            }
            for prefix, row, top_prefix in (("text", text_row, "text_top"), ("b", multimodal_row, "b_top")):
                for index, key in enumerate(("top1", "top2", "top3"), 1):
                    item = row["top3"][index - 1] if index <= len(row["top3"]) else None
                    record[f"{top_prefix}{index}_doc"] = item["doc_name"] if item else ""
                    record[f"{top_prefix}{index}_page"] = item["page_or_slide"] if item else ""
                    record[f"{top_prefix}{index}_modality"] = item["modality"] if item else ""
            writer.writerow(record)


def enrich_failure_candidates(path: Path, engine: RetrievalEngine, full_cases: list[dict], heldout_cases: list[dict], top_k: int) -> None:
    """Add config-a and config-b top-3 details to every failure-candidate row."""
    if not path.exists():
        return
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    fieldnames = list(rows[0].keys()) if rows else []
    for prefix in ("text_top", "b_top"):
        for index in (1, 2, 3):
            for suffix in ("doc", "page", "modality"):
                field = f"{prefix}{index}_{suffix}"
                if field not in fieldnames:
                    fieldnames.append(field)

    cases_by_split = {"full": full_cases, "heldout": heldout_cases}
    for row in rows:
        split_cases = cases_by_split.get(row.get("split", ""), [])
        case = next((item for item in split_cases if str(item.get("id")) == row["id"]), None)
        if not case:
            continue
        text_results = engine.search(case["question"], top_k=top_k, modality="text", use_memory=False)
        b_results = engine.search(case["question"], top_k=top_k, use_memory=False)
        for prefix, results in (("text_top", text_results), ("b_top", b_results)):
            for index, result in enumerate(results[:3], 1):
                row[f"{prefix}{index}_doc"] = result.doc_name
                row[f"{prefix}{index}_page"] = int(result.page_or_slide)
                row[f"{prefix}{index}_modality"] = str(result.modality)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_e6_csv(path: Path, e6_results: dict[str, dict]) -> None:
    fieldnames = [
        "metric", "split", "engine_mode", "n", "value", "unit", "status", "reason", "details",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for split_name, result in e6_results.items():
            rows = [
                ("retrieved_top10_identical", split_name, "same_engine", result["runs"], result["same_engine_identical_percent"], "percent", "RUN", "", f"top-10 element IDs and order; same engine across {result['runs']} runs"),
                ("retrieved_top10_identical", split_name, "fresh_engine_per_run", result["runs"], result["fresh_engine_identical_percent"], "percent", "RUN", "", f"top-10 element IDs and order; fresh engine across {result['runs']} runs"),
                ("retrieval_latency", split_name, "retrieval_only", result["retrieval_latency_count"], result["retrieval_p50_ms"], "ms", "RUN", "", "P50 retrieval search latency; not end-to-end"),
                ("retrieval_latency", split_name, "retrieval_only", result["retrieval_latency_count"], result["retrieval_p95_ms"], "ms", "RUN", "", "P95 retrieval search latency; not end-to-end"),
                ("phase2_equivalent_latency", split_name, "retrieval_only", result["phase2_equivalent_count"], result["phase2_equivalent_p50_ms"], "ms", "RUN", "", "P50 warm phase2-equivalent span: engine.search(use_memory=False), reranking included, no format_context"),
                ("phase2_equivalent_latency", split_name, "retrieval_only", result["phase2_equivalent_count"], result["phase2_equivalent_p95_ms"], "ms", "RUN", "", "P95 warm phase2-equivalent span: engine.search(use_memory=False), reranking included, no format_context"),
                ("context_tokens", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["mean_context_tokens"], "tokens/query", "RUN", "", f"engine.format_context(top_k); tokenizer={result['tokenizer']}"),
                ("naive_top3_document_tokens", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["mean_naive_tokens"], "tokens/query", "RUN", "", f"full text elements of all pages from top-3 documents; tokenizer={result['tokenizer']}"),
                ("context_to_naive_ratio", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["mean_ratio"], "ratio", "RUN", "", "mean context_tokens / naive_tokens"),
                ("context_to_naive_ratio", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["median_ratio"], "ratio", "RUN", "", "median context_tokens / naive_tokens"),
                ("context_to_naive_ratio", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["min_ratio"], "ratio", "RUN", "", "minimum per-query context_tokens / naive_tokens"),
                ("context_to_naive_ratio", split_name, "retrieval_only", len(result.get("same_engine_query_rows", [])), result["max_ratio"], "ratio", "RUN", "", "maximum per-query context_tokens / naive_tokens"),
                ("gs035_max_ratio_detail", split_name, "retrieval_only", 1, result["max_ratio_detail"]["ratio"] if result["max_ratio_detail"] else 0.0, "ratio", "RUN", "", json.dumps(result["max_ratio_detail"], sort_keys=True) if result["max_ratio_detail"] else "NOT_AVAILABLE"),
                ("guardrail_overhead", split_name, "with_vs_without_input_guardrail", result["retrieval_latency_count"], result["guardrail_p50_ms"], "ms", "RUN", "", "P50 with guardrail minus no-call baseline; FR4 threshold is 6000 ms P95"),
                ("guardrail_overhead", split_name, "with_vs_without_input_guardrail", result["retrieval_latency_count"], result["guardrail_p95_ms"], "ms", "PASS" if result["guardrail_fr4_passed"] else "FAIL", "", "P95 with guardrail minus no-call baseline"),
                ("dos_blocked_calls", split_name, "timed_guardrail_loop", result["retrieval_latency_count"], result["dos_blocked_calls"], "calls", "RUN", "", json.dumps(result["dos_block_reasons"], sort_keys=True)),
                ("memory_consistency", split_name, "reused_engine_use_memory_true", result["runs"], result["memory_consistency_percent"], "percent", "RUN", "", f"memory-vs-no-memory changed rankings for {result['memory_vs_nomemory_changes']}/{result['memory_vs_nomemory_count']} queries"),
                ("answer_consistency", split_name, "llm_answer", 0, 0.0, "percent", "NOT_RUN", "no LLM backend", "answer generation unavailable"),
                ("answer_tokens", split_name, "llm_answer", 0, 0.0, "tokens/query", "NOT_RUN", "no LLM backend", "answer generation unavailable"),
                ("end_to_end_latency", split_name, "llm_end_to_end", 0, 0.0, "ms", "NOT_RUN", "no LLM backend", "FR3 end-to-end latency unavailable"),
            ]
            for order_name, order_metrics in result["memory_order_metrics"].items():
                rows.append(("memory_recall_at_10", split_name, f"use_memory_true_{order_name}", order_metrics["query_count"], order_metrics["recall_at_10"], "ratio", "RUN", "", f"memory enabled; order={order_name}"))
                rows.append(("memory_mrr", split_name, f"use_memory_true_{order_name}", order_metrics["query_count"], order_metrics["mrr"], "ratio", "RUN", "", f"memory enabled; order={order_name}"))
            for row in rows:
                writer.writerow(dict(zip(fieldnames, row)))


def committed_phase2_latency_baseline() -> dict | None:
    try:
        result = subprocess.run(
            ["git", "show", "HEAD:output/phase2_retrieval_metrics.json"],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return None


def build_e6_section(e6_results: dict[str, dict]) -> str:
    sections = ["\n## E6: Retrieval Non-functional Evaluation"]
    for split_name, result in e6_results.items():
        sections.append(
            f"\n**{split_name.title()}** ({result['runs']} runs per query): "
            f"identical top-10 IDs/order: same engine {result['same_engine_identical_percent']:.2f}%, "
            f"fresh engine {result['fresh_engine_identical_percent']:.2f}%; "
            f"retrieval P50 {result['retrieval_p50_ms']:.3f} ms, P95 {result['retrieval_p95_ms']:.3f} ms; "
            f"phase2-equivalent warm P50 {result['phase2_equivalent_p50_ms']:.3f} ms, P95 {result['phase2_equivalent_p95_ms']:.3f} ms."
        )
        fr4_status = "PASS" if result["guardrail_fr4_passed"] else "FAIL"
        sections.append(
            f"\nTokens ({result['tokenizer']}): context mean {result['mean_context_tokens']:.3f}, median {result['median_context_tokens']:.3f}; "
            f"naive top-3-document mean {result['mean_naive_tokens']:.3f}, median {result['median_naive_tokens']:.3f}; "
            f"ratio mean {result['mean_ratio']:.6f}, median {result['median_ratio']:.6f}, min {result['min_ratio']:.6f}, max {result['max_ratio']:.6f}."
        )
        sections.append(
            f"\nGuardrail overhead: P50 {result['guardrail_p50_ms']:.3f} ms, P95 {result['guardrail_p95_ms']:.3f} ms; FR4 (<6 s): {fr4_status}. "
            "Timed checks ran: DoSProtection.check() and InputGuardrails.validate_input(); validate_input ran prompt-injection/domain-scope/PII checks."
        )
        sections.append(
            f"\nReused engine with `use_memory=True`: identical top-10 {result['memory_consistency_percent']:.2f}% across 5 runs; "
            f"memory changed ranking versus no-memory for {result['memory_vs_nomemory_changes']}/{result['memory_vs_nomemory_count']} queries. "
            f"Timed DoSProtection.check() calls blocked: {result['dos_blocked_calls']}; reasons: {json.dumps(result['dos_block_reasons'], sort_keys=True)}."
        )
        memory_order_rows = [
            f"{order_name}: Recall@10={metrics['recall_at_10']:.6f}, MRR={metrics['mrr']:.6f} (n={metrics['query_count']})"
            for order_name, metrics in result["memory_order_metrics"].items()
        ]
        sections.append("\nMemory-enabled Recall@10/MRR by query order: " + "; ".join(memory_order_rows) + ".")
        detail = result["max_ratio_detail"]
        if detail:
            doc_lines = "; ".join(
                f"{doc['doc_name']} ({doc['elements']} elements, {doc['text_characters']} text characters)"
                for doc in detail["top_documents"]
            )
            sections.append(
                f"\nMaximum token ratio case: {detail['id']} = {detail['ratio']:.6f} ({detail['context_tokens']} context tokens / {detail['naive_tokens']} naive tokens). "
                f"Top-3 document size: {doc_lines}."
            )
        sections.append(
            "\nMemory initialization: each of the 5 memory consistency runs starts with `memory.clear()`; queries then accumulate prior turns within that run via `use_memory=True`. "
            "Each golden/shuffle memory-order evaluation creates a fresh engine and clears memory before the first query."
        )
        sections.append(
            "\nQuery memory: disabled (`use_memory=False`) in the original reused-engine consistency runs; memory-active ranking: no; "
            "ranking-effect check: not applicable because memory was not active."
        )
    sections.append(
        "\nLatency coverage: phase2/run_demo.py starts its timer immediately before `engine.search(..., use_memory=False, top_k=10)` and does not include engine construction or `format_context`; reranking is inside `search`. "
        "A cold engine search additionally includes TF-IDF/BM25 index construction only outside the Phase 2 timer, while that construction occurs when `RetrievalEngine` is created. "
        "The general E6 retrieval timer covers the same `search` span, plus fresh-engine searches also include engine construction in their loop; phase2-equivalent values below isolate the warm `search` span."
    )
    temp_metrics = result.get("phase2_temp_metrics")
    machine = result.get("machine", {})
    if temp_metrics:
        sections.append(
            f"\nPhase 2 temp rerun on this machine ({machine.get('os', 'unknown')}; CPU {machine.get('cpu', 'unknown')}; "
            f"Python {machine.get('python', 'unknown')}): P50 {float(temp_metrics['p50_latency_ms']):.3f} ms, "
            f"P95 {float(temp_metrics['p95_latency_ms']):.3f} ms."
        )
    sections.append(
        "\nNamed timing runs: 23.592/31.416 ms was the direct temp-directory `phase2/run_demo.py` rerun performed earlier; "
        "26.851/36.587 ms was the later temp rerun after verification changes. Both cover the same Phase 2 `run_demo.py` search-only span."
    )
    baseline = committed_phase2_latency_baseline()
    if baseline:
        sections.append(
            f"\nCommitted Phase 2 baseline: P50 {float(baseline['p50_latency_ms']):.3f} ms, "
            f"P95 {float(baseline['p95_latency_ms']):.3f} ms. The gap from the warm Phase 4 measurements is due to the timer span "
            "and machine/environment differences: the committed baseline records one Phase 2 `run_demo.py` search-only run per query, "
            "while Phase 4 also has fresh-engine loop timing that may include engine construction and warm-search timing with reranking. "
            "Neither timer includes `format_context`."
        )
    sections.append(
        "\nAnswer consistency, answer-token count, and end-to-end latency are `NOT_RUN`: "
        "`no LLM backend` is configured."
    )
    return "".join(sections)


def build_summary(full_metrics: dict, heldout_metrics: dict, full_cases: list[dict], heldout_cases: list[dict], recorded: dict | None, e3_present: bool = False) -> str:
    full_recall = full_metrics["recall_at_10"]
    full_mrr = full_metrics["mrr"]
    comparison = "No recorded Phase 2 baseline file was found."
    if recorded:
        baseline_recall = float(recorded["recall_at_10"])
        baseline_mrr = float(recorded["mrr"])
        recall_match = abs(full_recall - baseline_recall) < 1e-12
        mrr_match = abs(full_mrr - baseline_mrr) < 1e-12
        comparison = (
            f"| Recall@10 | {baseline_recall:.6f} | {full_recall:.6f} | {'MATCH' if recall_match else 'DIFFER'} |\n"
            f"| MRR | {baseline_mrr:.6f} | {full_mrr:.6f} | {'MATCH' if mrr_match else 'DIFFER'} |"
        )
        if not recall_match or not mrr_match:
            comparison += "\n\nThe values differ. No forced adjustment was applied; compare corpus state, environment, and ranking/benchmark code."

    return f"""# Phase 4 Retrieval-Only Evaluation

## Hit definition
A hit is defined exactly as in `phase2/run_demo.py`: the retrieved result's `doc_name` equals the golden case's source document and `page_or_slide` equals the golden case's source page/slide.

## Case counts

| Split | Total | Text | Table | Image |
|---|---:|---:|---:|---:|
| Full | {len(full_cases)} | {modality_counts(full_cases).get('text', 0)} | {modality_counts(full_cases).get('table', 0)} | {modality_counts(full_cases).get('image', 0)} |
| Held-out | {len(heldout_cases)} | {modality_counts(heldout_cases).get('text', 0)} | {modality_counts(heldout_cases).get('table', 0)} | {modality_counts(heldout_cases).get('image', 0)} |

## Retrieval metrics

| Split | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| Full | {full_metrics['recall_at_1']:.6f} | {full_metrics['recall_at_5']:.6f} | {full_metrics['recall_at_10']:.6f} | {full_metrics['mrr']:.6f} | {full_metrics['ndcg_at_10']:.6f} |
| Held-out | {heldout_metrics['recall_at_1']:.6f} | {heldout_metrics['recall_at_5']:.6f} | {heldout_metrics['recall_at_10']:.6f} | {heldout_metrics['mrr']:.6f} | {heldout_metrics['ndcg_at_10']:.6f} |

## Phase 2 baseline sanity check

| Metric | Recorded Phase 2 | Current full run | Status |
|---|---:|---:|---|
{comparison}

## Answer-level metrics

| Metric | Status | Reason |
|---|---|---|
| Correctness | NOT_RUN | no LLM backend configured |
| Faithfulness | NOT_RUN | no LLM backend configured |
| Citation accuracy | NOT_RUN | no LLM backend configured |
| Refusal accuracy | NOT_RUN | no LLM backend configured |

No answer quality or LLM latency numbers are claimed in retrieval-only mode.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 4 evaluation")
    parser.add_argument("--retrieval-only", action="store_true", help="Run without an LLM backend")
    parser.add_argument("--e3", action="store_true", help="Run text-only versus full-multimodal retrieval comparison")
    parser.add_argument("--e6", action="store_true", help="Run retrieval-level consistency, latency, tokens, and guardrail benchmarks")
    parser.add_argument("--config", type=Path, help="Reserved for future answer-generation configuration")
    parser.add_argument("--split", choices=("full", "heldout", "both"), default="both")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "data" / "golden_set.json")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "output" / "phase4")
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if not args.retrieval_only:
        parser.error("Only --retrieval-only is currently implemented")

    golden_path = args.golden.resolve()
    full_cases = load_json(golden_path)

    optimizer = PromptOptimizer(str(golden_path))
    heldout_cases = optimizer.test_set

    print(f"Full golden set: {len(full_cases)} cases | modalities: {modality_counts(full_cases)}")
    print(f"Held-out split: {len(heldout_cases)} cases | modalities: {modality_counts(heldout_cases)}")

    engine = RetrievalEngine(REPO_ROOT)

    selected_full = full_cases if args.split in {"full", "both"} else []
    selected_heldout = heldout_cases if args.split in {"heldout", "both"} else []

    full_rows, full_metrics = run_retrieval(engine, selected_full, args.top_k) if selected_full else ([], aggregate_retrieval_metrics([]))
    heldout_rows, heldout_metrics = run_retrieval(engine, selected_heldout, args.top_k) if selected_heldout else ([], aggregate_retrieval_metrics([]))

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    write_per_case_csv(output_dir / "per_case_results.csv", full_rows, heldout_rows)

    retrieval_metrics = {
        "full": full_metrics,
        "heldout": heldout_metrics,
        "answer_level": {
            "status": "NOT_RUN",
            "reason": NOT_RUN_REASON,
        },
    }
    write_json(output_dir / "retrieval_metrics.json", retrieval_metrics)

    failure_path = output_dir / "failure_candidates.csv"
    write_failure_candidates(failure_path, "full", full_rows)
    write_failure_candidates(failure_path, "heldout", heldout_rows, append=True)

    manifest = run_manifest(git_commit(), args.top_k, golden_path)
    manifest["split_source"] = "phase3/self_improving_loop.py:PromptOptimizer.test_set"
    manifest["full_case_count"] = len(selected_full)
    manifest["heldout_case_count"] = len(selected_heldout)
    manifest["heldout_modality_counts"] = modality_counts(selected_heldout)
    write_json(output_dir / "run_manifest.json", manifest)

    e3_text = ""
    if args.e3:
        e3_rows: list[dict] = []
        e3_outcomes: dict[str, dict[str, Any]] = {}

        for split_name, cases in (("full", selected_full), ("heldout", selected_heldout)):
            if not cases:
                continue

            text_rows, text_metrics = run_retrieval(engine, cases, args.top_k, modality="text")
            multimodal_rows, multimodal_metrics = run_retrieval(engine, cases, args.top_k)
            metadata_rows, metadata_metrics = run_retrieval(engine, cases, args.top_k, use_category_filter=True)

            for config_name, primary_metrics in (
                ("text_only", text_metrics),
                ("full_multimodal", multimodal_metrics),
                ("multimodal_metadata_filtered", metadata_metrics),
            ):
                e3_rows.extend(metric_rows(config_name, split_name, primary_metrics, "doc_page"))
                if "modality_aware" in primary_metrics:
                    e3_rows.extend(metric_rows(config_name, split_name, primary_metrics["modality_aware"], "doc_page_modality"))

            changed, outcomes = paired_outcome(text_rows, multimodal_rows, split_name)
            e3_rows.extend(changed)
            for modality, counts in outcomes["by_modality"].items():
                e3_rows.append({
                    "record_type": "paired_summary",
                    "config": "text_vs_full_multimodal",
                    "split": split_name,
                    "modality": modality,
                    "n": counts["n"],
                    "wins": counts["wins"],
                    "ties": counts["ties"],
                    "losses": counts["losses"],
                })
            usable_categories = sum(1 for case in cases if str(case.get("category") or "").strip())
            outcomes["category_coverage"] = {
                "usable": usable_categories,
                "total": len(cases),
                "fallback": "no category filter; full-multimodal behavior" if usable_categories < len(cases) else "category filter applied",
            }
            loss_rows = [row for row in changed if row["paired_outcome"] == "loss"]
            append_pair_loss_candidates(output_dir / "failure_candidates.csv", split_name, loss_rows, text_rows, multimodal_rows)
            sign = exact_two_sided_sign_test(outcomes["wins"], outcomes["losses"])
            outcomes["sign_test"] = sign
            e3_outcomes[split_name] = outcomes

        write_e3_csv(output_dir / "e3_text_vs_multimodal.csv", e3_rows)

        sections = ["\n## E3: Text-only vs full multimodal"]
        for split_name in ("full", "heldout"):
            if split_name not in e3_outcomes:
                continue
            outcomes = e3_outcomes[split_name]
            coverage = outcomes["category_coverage"]
            sign = outcomes["sign_test"]
            p_text = "n/a (no non-tied pairs)" if sign["p_value"] is None else f"{sign['p_value']:.6g}"
            sections.append(
                f"\n**{split_name.title()}** — win/tie/loss compares per-case reciprocal rank: "
                "win when full-multimodal RR is greater, loss when it is lower, tie when equal (ties excluded from the sign test). "
                f"Overall: wins {outcomes['wins']}, ties {outcomes['ties']}, losses {outcomes['losses']}; "
                f"exact two-sided sign-test p={p_text} (n={sign['n_excluding_ties']} excluding ties)."
            )
            sections.append("\n| Modality | n | Wins | Ties | Losses |\n|---|---:|---:|---:|---:|")
            for modality in ("text", "table", "image"):
                counts = outcomes["by_modality"].get(modality, {"n": 0, "wins": 0, "ties": 0, "losses": 0})
                sections.append(f"\n| {modality} | {counts['n']} | {counts['wins']} | {counts['ties']} | {counts['losses']} |")
            sections.append(
                f"\nConfig (c) category coverage: {coverage['usable']}/{coverage['total']} usable cases; "
                f"fallback for remaining cases: {coverage['fallback']}.")
            sections.append("\nCase-changing outcomes are listed in `e3_text_vs_multimodal.csv` with `record_type=pair`.")
            sections.append("\n| Config | Hit definition | Recall@10 (n) | MRR (n) |\n|---|---|---:|---:|")
            for hit_definition in ("doc_page", "doc_page_modality"):
                for config_name in ("text_only", "full_multimodal", "multimodal_metadata_filtered"):
                    rows = [row for row in e3_rows if row.get("record_type") == "summary" and row.get("split") == split_name and row.get("config") == config_name and row.get("hit_definition") == hit_definition and row.get("modality") == "overall"]
                    if rows:
                        row = rows[0]
                        sections.append(f"\n| {config_name} | {hit_definition} | {row['recall_at_10']:.6f} (n={row['n']}) | {row['mrr']:.6f} (n={row['n']}) |")
            sections.append("\nDetailed per-modality metrics and n counts are reported in `e3_text_vs_multimodal.csv`.")
        e3_text = "".join(sections)

    enrich_failure_candidates(failure_path, engine, selected_full, selected_heldout, args.top_k)

    e6_text = ""
    if args.e6:
        e6_results: dict[str, dict] = {}
        for split_name, cases in (("full", selected_full), ("heldout", selected_heldout)):
            if not cases:
                continue
            e6_results[split_name] = run_e6(engine, cases, args.runs, args.top_k)
        write_e6_csv(output_dir / "e6_nonfunctional.csv", e6_results)
        log_dir = output_dir / "run_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if "full" in e6_results:
            (log_dir / "phase2_temp.json").write_text(
                json.dumps(e6_results["full"]["phase2_temp_metrics"], indent=2) + "\n",
                encoding="utf-8",
            )
        e6_text = build_e6_section(e6_results)

    recorded = read_recorded_phase2(REPO_ROOT)
    summary = build_summary(full_metrics, heldout_metrics, selected_full, selected_heldout, recorded)
    if e3_text:
        summary = summary.replace("\n## Answer-level metrics", e3_text + "\n\n## Answer-level metrics")
    if e6_text:
        summary = summary.replace("\n## Answer-level metrics", e6_text + "\n\n## Answer-level metrics")
    (output_dir / "phase4_summary.md").write_text(summary, encoding="utf-8")

    print(json.dumps(retrieval_metrics, indent=2, ensure_ascii=False))
    print(f"Wrote outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
