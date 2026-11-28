"""Small hand-computed tests for Phase 4 retrieval metrics."""

from phase4.evaluate import exact_two_sided_sign_test
from phase4.metrics import (
    aggregate_retrieval_metrics,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_hand_computed():
    assert recall_at_k(["A", "B", "C"], {"B", "C"}, 1) == 0.0
    assert recall_at_k(["A", "B", "C"], {"B", "C"}, 2) == 0.5
    assert recall_at_k(["A", "B", "C"], {"B", "C"}, 3) == 1.0


def test_reciprocal_rank_hand_computed():
    assert reciprocal_rank(["A", "B", "C"], {"C"}) == 1.0 / 3.0
    assert reciprocal_rank(["A", "B", "C"], {"X"}) == 0.0


def test_ndcg_at_k_hand_computed():
    assert ndcg_at_k(["A", "B", "C"], {"C"}, 3) == 0.5


def test_ndcg_does_not_double_count_duplicate_relevant_ids():
    assert ndcg_at_k(["A", "A", "B"], {"A"}, 3) == 1.0


def test_ndcg_at_10_never_exceeds_one_for_duplicate_doc_page_ids():
    assert ndcg_at_k(["doc|2"] * 10, {"doc|2"}, 10) <= 1.0


def test_aggregate_metrics_and_modality_breakdown():
    cases = [
        {"retrieved_ids": ["A", "B"], "relevant_ids": {"A"}, "modality": "text"},
        {"retrieved_ids": ["X", "B"], "relevant_ids": {"B"}, "modality": "table"},
    ]
    metrics = aggregate_retrieval_metrics(cases)

    assert metrics["query_count"] == 2
    assert metrics["recall_at_1"] == 0.5
    assert metrics["recall_at_5"] == 1.0
    assert metrics["recall_at_10"] == 1.0
    assert metrics["mrr"] == 0.75
    assert metrics["by_modality"]["text"]["recall_at_1"] == 1.0
    assert metrics["by_modality"]["table"]["mrr"] == 0.5


def test_exact_two_sided_sign_test_hand_computed():
    result = exact_two_sided_sign_test(wins=9, losses=9)
    assert result["n_excluding_ties"] == 18
    assert abs(result["p_value"] - 1.0) < 1e-12


def test_empty_cases_are_zero_not_estimated():
    metrics = aggregate_retrieval_metrics([])
    assert metrics["query_count"] == 0
    assert metrics["recall_at_10"] == 0.0
