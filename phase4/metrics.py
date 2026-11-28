"""Deterministic retrieval metrics for Phase 4 evaluation."""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import Any


def recall_at_k(ranked_ids: Sequence[Hashable], relevant_ids: Iterable[Hashable], k: int) -> float:
    """Fraction of relevant IDs found within the top k ranks."""
    if k < 1:
        raise ValueError("k must be at least 1")
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    hits = relevant.intersection(ranked_ids[:k])
    return len(hits) / len(relevant)


def reciprocal_rank(ranked_ids: Sequence[Hashable], relevant_ids: Iterable[Hashable]) -> float:
    """Reciprocal rank of the first relevant item."""
    relevant = set(relevant_ids)
    for rank, item_id in enumerate(ranked_ids, 1):
        if item_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[Hashable], relevant_ids: Iterable[Hashable], k: int) -> float:
    """Binary nDCG@k for one query."""
    if k < 1:
        raise ValueError("k must be at least 1")
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0

    dcg = 0.0
    seen: set[Hashable] = set()
    for rank, item_id in enumerate(ranked_ids[:k], 1):
        if item_id in seen:
            continue
        seen.add(item_id)
        if item_id in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / idcg if idcg else 0.0


def mean_reciprocal_rank(per_query_rankings: Sequence[Sequence[Hashable]], relevant_ids: Sequence[Iterable[Hashable]]) -> float:
    """Mean reciprocal rank across queries."""
    if len(per_query_rankings) != len(relevant_ids):
        raise ValueError("rankings and relevant_ids must have the same length")
    if not per_query_rankings:
        return 0.0
    return sum(
        reciprocal_rank(ranked, relevant)
        for ranked, relevant in zip(per_query_rankings, relevant_ids)
    ) / len(per_query_rankings)


def aggregate_retrieval_metrics(per_case: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate retrieval metrics and optional modality breakdown.

    Each case must contain ``retrieved_ids``, ``relevant_ids``, and optional ``modality``.
    """
    if not per_case:
        return {
            "query_count": 0,
            "recall_at_1": 0.0,
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0,
            "ndcg_at_10": 0.0,
            "by_modality": {},
        }

    rankings = [list(case["retrieved_ids"]) for case in per_case]
    relevants = [list(case["relevant_ids"]) for case in per_case]

    overall = {
        "query_count": len(per_case),
        "recall_at_1": sum(recall_at_k(rank, rel, 1) for rank, rel in zip(rankings, relevants)) / len(per_case),
        "recall_at_5": sum(recall_at_k(rank, rel, 5) for rank, rel in zip(rankings, relevants)) / len(per_case),
        "recall_at_10": sum(recall_at_k(rank, rel, 10) for rank, rel in zip(rankings, relevants)) / len(per_case),
        "mrr": mean_reciprocal_rank(rankings, relevants),
        "ndcg_at_10": sum(ndcg_at_k(rank, rel, 10) for rank, rel in zip(rankings, relevants)) / len(per_case),
    }

    modality_cases: dict[str, list[Mapping[str, Any]]] = {}
    for case in per_case:
        modality = str(case.get("modality") or "unknown")
        modality_cases.setdefault(modality, []).append(case)

    overall["by_modality"] = {}
    for modality in sorted(modality_cases):
        cases = modality_cases[modality]
        modality_rankings = [list(case["retrieved_ids"]) for case in cases]
        modality_relevants = [list(case["relevant_ids"]) for case in cases]
        overall["by_modality"][modality] = {
            "query_count": len(cases),
            "recall_at_1": sum(recall_at_k(rank, rel, 1) for rank, rel in zip(modality_rankings, modality_relevants)) / len(cases),
            "recall_at_5": sum(recall_at_k(rank, rel, 5) for rank, rel in zip(modality_rankings, modality_relevants)) / len(cases),
            "recall_at_10": sum(recall_at_k(rank, rel, 10) for rank, rel in zip(modality_rankings, modality_relevants)) / len(cases),
            "mrr": mean_reciprocal_rank(modality_rankings, modality_relevants),
            "ndcg_at_10": sum(ndcg_at_k(rank, rel, 10) for rank, rel in zip(modality_rankings, modality_relevants)) / len(cases),
        }

    return overall
