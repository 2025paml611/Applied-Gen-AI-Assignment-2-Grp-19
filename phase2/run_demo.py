"""Run Phase 2 retrieval against the hand-curated golden set."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
import sys
from pathlib import Path

try:
    from .retrieval_engine import RetrievalEngine
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from phase2.retrieval_engine import RetrievalEngine


def reciprocal_rank(results, source_doc: str, source_page: int) -> float:
    for rank, result in enumerate(results, 1):
        if result.doc_name == source_doc and result.page_or_slide == source_page:
            return 1.0 / rank
    return 0.0


def run_benchmark(repo_root: Path, output_dir: Path, top_k: int = 10) -> dict:
    engine = RetrievalEngine(repo_root)
    golden_path = repo_root / "data" / "golden_set.json"
    with golden_path.open("r", encoding="utf-8") as handle:
        golden = json.load(handle)

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    latencies = []
    reciprocal_ranks = []
    recall_hits = 0

    for case in golden:
        started = time.perf_counter()
        results = engine.search(case["question"], top_k=top_k, use_memory=False)
        latencies.append((time.perf_counter() - started) * 1000)

        hit = any(
            result.doc_name == case["source_doc"]
            and result.page_or_slide == int(case["page_or_slide"])
            for result in results
        )
        recall_hits += int(hit)
        rr = reciprocal_rank(results, case["source_doc"], int(case["page_or_slide"]))
        reciprocal_ranks.append(rr)

        rows.append(
            {
                "id": case["id"],
                "modality": case["modality"],
                "question": case["question"],
                "source_doc": case["source_doc"],
                "source_page": case["page_or_slide"],
                "recall_at_k": int(hit),
                "reciprocal_rank": round(rr, 4),
                "top_result": results[0].doc_name if results else "",
                "top_page": results[0].page_or_slide if results else "",
                "top_score": round(results[0].score, 6) if results else 0,
                "latency_ms": round(latencies[-1], 3),
            }
        )

    latencies.sort()
    p50 = statistics.median(latencies)
    p95_index = max(0, math_ceil(len(latencies) * 0.95) - 1)
    metrics = {
        "golden_questions": len(golden),
        "top_k": top_k,
        f"recall_at_{top_k}": recall_hits / len(golden) if golden else 0.0,
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "p50_latency_ms": round(p50, 3),
        "p95_latency_ms": round(latencies[p95_index], 3),
    }

    csv_path = output_dir / "phase2_retrieval_benchmark.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary_path = output_dir / "phase2_retrieval_metrics.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)

    print(json.dumps(metrics, indent=2))
    print(f"Saved: {csv_path}")
    print(f"Saved: {summary_path}")
    return metrics


def math_ceil(value: float) -> int:
    return int(value + 0.999999)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the Phase 2 retrieval engine")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    run_benchmark(repo_root, args.output_dir, args.top_k)


if __name__ == "__main__":
    main()

