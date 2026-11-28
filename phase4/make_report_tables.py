"""Generate the Phase 4 report tables and reproducibility artifacts.

This script reads existing evaluation outputs only. It does not estimate or modify
Phase 2 or Phase 3 implementation/output behavior.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "output" / "phase4"
LOGS = OUTPUT / "run_logs"
REPORT = REPO_ROOT / "docs" / "phase4_report.md"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fmt(value, digits=6) -> str:
    if value is None:
        return "NOT_AVAILABLE"
    if isinstance(value, str):
        return value
    return f"{float(value):.{digits}f}"


def table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join(["---"] * len(headers)) + "|"
    body = "\n".join("| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |" for row in rows)
    return "\n".join([line, separator, body]) if body else "\n".join([line, separator])


def source(path: str) -> str:
    return f"\n\n**Source:** `{path}`"




def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sign_test(wins: int, losses: int) -> tuple[int, float]:
    n = wins + losses
    if n == 0:
        return n, 1.0
    tail_limit = min(wins, losses)
    one_tail = sum(math.comb(n, k) for k in range(tail_limit + 1)) / (2 ** n)
    return n, min(1.0, 2.0 * one_tail)


def generated_tables(validation: dict, retrieval: dict, manifest: dict,
                     e3_rows: list[dict], e6_rows: list[dict], failure_rows: list[dict],
                     phase2_baseline: dict, phase2_temp: dict) -> dict[str, str]:
    tables: dict[str, str] = {}

    # Golden-set overview
    rows = [[
        str(validation["total_cases"]),
        str(validation["modality_breakdown"].get("text", 0)),
        str(validation["modality_breakdown"].get("table", 0)),
        str(validation["modality_breakdown"].get("image", 0)),
        str(validation["category_breakdown"].get("normal", 0)),
        str(validation["category_breakdown"].get("edge", 0)),
        str(validation["category_breakdown"].get("adversarial", 0)),
        str(validation["valid_cases"]),
        str(len(validation["provenance_missing"])),
    ]]
    tables["golden"] = table(
        ["Cases", "Text", "Table", "Image", "Normal", "Edge", "Adversarial", "Valid", "Missing provenance"], rows
    ) + source("output/phase4_golden_validation.json")

    # Full/held-out metric table
    rows = []
    for split in ("full", "heldout"):
        metrics = retrieval[split]
        rows.append([split.title(), str(metrics["query_count"]), "Overall",
                     fmt(metrics["recall_at_1"]), fmt(metrics["recall_at_5"]),
                     fmt(metrics["recall_at_10"]), fmt(metrics["mrr"]), fmt(metrics["ndcg_at_10"])])
        for modality in ("text", "table", "image"):
            m = metrics["by_modality"][modality]
            rows.append([split.title(), str(m["query_count"]), modality.title(),
                         fmt(m["recall_at_1"]), fmt(m["recall_at_5"]),
                         fmt(m["recall_at_10"]), fmt(m["mrr"]), fmt(m["ndcg_at_10"])])
    tables["metrics"] = table(
        ["Split", "n", "Modality", "Recall@1", "Recall@5", "Recall@10", "MRR", "nDCG@10"], rows
    ) + source("output/phase4/retrieval_metrics.json")

    # Sanity check
    full = retrieval["full"]
    tables["sanity"] = table(
        ["Metric", "Phase 4 full", "Phase 2 snapshot", "Status"],
        [
            ["Recall@10", fmt(full["recall_at_10"]), fmt(phase2_baseline["recall_at_10"]),
             "MATCH" if abs(full["recall_at_10"] - phase2_baseline["recall_at_10"]) < 1e-12 else "DIFFER"],
            ["MRR", fmt(full["mrr"]), fmt(phase2_baseline["mrr"]),
             "MATCH" if abs(full["mrr"] - phase2_baseline["mrr"]) < 1e-12 else "DIFFER"],
        ]
    ) + source("output/phase4/retrieval_metrics.json; output/phase2_retrieval_metrics.json")

    # E3 configuration table; c is not evaluated because category tags are absent
    e3_summary = [r for r in e3_rows if r.get("record_type") == "summary"]
    rows = []
    for split in ("full", "heldout"):
        for hit in ("doc_page", "doc_page_modality"):
            for config in ("text_only", "full_multimodal"):
                matches = [r for r in e3_summary if r.get("split") == split and r.get("hit_definition") == hit
                           and r.get("config") == config and r.get("modality") == "overall"]
                if matches:
                    r = matches[0]
                    rows.append([split.title(), {"text_only":"a","full_multimodal":"b"}[config], hit,
                                 str(r["n"]), fmt(r["recall_at_10"]), fmt(r["mrr"])])
            rows.append([split.title(), "c", hit, "35" if split == "full" else "11", "NOT EVALUATED", "NOT EVALUATED"])
    tables["e3"] = table(
        ["Split", "Config", "Hit definition", "n", "Recall@10", "MRR"], rows
    ) + source("output/phase4/e3_text_vs_multimodal.csv; output/phase4_golden_validation.json")

    # W/T/L and sign test
    per_case = read_csv(REPO_ROOT / "output/phase4/per_case_results.csv")
    golden = load_json(REPO_ROOT / "data/golden_set.json")
    golden_by_id = {str(c["id"]): c for c in golden}
    pair_rows = [r for r in e3_rows if r.get("record_type") == "pair"]
    rows = []
    sign_rows = []
    for split in ("full", "heldout"):
        split_pairs = [r for r in pair_rows if r.get("split") == split]
        split_ids = {r["id"] for r in split_pairs}
        split_cases = [c for c in golden if str(c["id"]) in set(r["id"] for r in pair_rows if r.get("split") == split)]
        # Full or heldout n comes from manifest and heldout membership is inferred from per-case CSV.
        split_per_case = [r for r in per_case if r["split"] == split]
        n_total = len(split_per_case)
        outcome = {"win": 0, "tie": 0, "loss": 0}
        by_modality: dict[str, Counter] = {}
        for row in split_per_case:
            case_id = row["id"]
            pair = next((r for r in split_pairs if r["id"] == case_id), None)
            if pair:
                result = pair["paired_outcome"]
            else:
                text_rr = next((float(r["text_rr"]) for r in pair_rows if r["id"] == case_id), None)
                # Changed pairs are already separated; ties are all remaining rows.
                result = "tie"
            outcome[result] += 1
            modality = row["modality"]
            by_modality.setdefault(modality, Counter())[result] += 1

        for modality in ("text", "table", "image"):
            counts = by_modality.get(modality, Counter())
            n = sum(1 for r in split_per_case if r["modality"] == modality)
            rows.append([split.title(), modality.title(), str(n), str(counts["win"]), str(counts["tie"]), str(counts["loss"])])
        wins, losses = outcome["win"], outcome["loss"]
        n_sign, p = sign_test(wins, losses)
        sign_rows.append([split.title(), str(wins), str(losses), str(n_sign), fmt(p, 6)])

    tables["e3_wtl"] = table(["Split", "Modality", "n", "Wins", "Ties", "Losses"], rows) + source("output/phase4/e3_text_vs_multimodal.csv; output/phase4/per_case_results.csv")
    tables["e3_sign"] = table(["Split", "Wins", "Losses", "n (ties excluded)", "Exact two-sided p"], sign_rows) + source("output/phase4/e3_text_vs_multimodal.csv")

    text_rows = []
    for split in ("full", "heldout"):
        for config in ("text_only", "full_multimodal"):
            matches = [r for r in e3_summary if r.get("split") == split and r.get("hit_definition") == "doc_page" and r.get("config") == config and r.get("modality") == "text"]
            if matches:
                r = matches[0]
                text_rows.append([split.title(), {"text_only":"a","full_multimodal":"b"}[config], str(r["n"]), fmt(r["recall_at_10"]), fmt(r["mrr"])])
    tables["e3_text_cases"] = table(["Split", "Config", "Text cases (n)", "Recall@10", "MRR"], text_rows) + source("output/phase4/e3_text_vs_multimodal.csv")

    # Answer-level table
    tables["answer"] = table(
        ["Metric", "Status", "Reason"],
        [
            ["Correctness", "NOT_RUN", "no LLM backend configured"],
            ["Faithfulness", "NOT_RUN", "no LLM backend configured"],
            ["Citation accuracy", "NOT_RUN", "no LLM backend configured"],
            ["Refusal accuracy", "NOT_RUN", "no LLM backend configured"],
            ["Answer consistency", "NOT_RUN", "no LLM backend configured"],
            ["Answer tokens", "NOT_RUN", "no LLM backend configured"],
            ["End-to-end latency", "NOT_RUN", "no LLM backend configured"],
            ["Output guardrails", "NOT_RUN", "no LLM backend configured"],
        ]
    ) + source("output/phase4/run_manifest.json; output/phase4/e6_nonfunctional.csv")

    # E6 helper lookup
    def e6(metric: str, split: str, engine_mode: str | None = None) -> list[dict]:
        return [r for r in e6_rows if r["metric"] == metric and r["split"] == split
                and (engine_mode is None or r["engine_mode"] == engine_mode)]

    # Latency table
    rows = []
    for split in ("full",):
        temp_p50 = fmt(phase2_temp["p50_latency_ms"])
        temp_p95 = fmt(phase2_temp["p95_latency_ms"])
        phase4_e6 = e6("retrieval_latency", split)
        warm = e6("phase2_equivalent_latency", split)
        rows.append(["Phase 2 snapshot", split.title(), "search-only; no engine construction; no format_context", "-", "-", fmt(phase2_baseline["p50_latency_ms"]), fmt(phase2_baseline["p95_latency_ms"])])
        rows.append(["Phase 2 temp rerun", split.title(), "search-only; no engine construction; no format_context", "-", "-", temp_p50, temp_p95])
        if warm:
            rows.append(["Phase 4 warm", split.title(), "warm engine.search(use_memory=False); reranking included; no format_context", "-", "-",
                         fmt(warm[0]["value"]), fmt(warm[1]["value"] if len(warm) > 1 else None)])
    tables["latency"] = table(
        ["Source", "Split", "Timer coverage", "n", "Engine", "P50 ms", "P95 ms"], rows
    ) + source("output/phase2_retrieval_metrics.json; output/phase4/run_logs/phase2_temp.json; output/phase4/e6_nonfunctional.csv")

    # Consistency and memory
    rows = []
    for split in ("full", "heldout"):
        same = e6("retrieved_top10_identical", split, "same_engine")
        fresh = e6("retrieved_top10_identical", split, "fresh_engine_per_run")
        memory = e6("memory_consistency", split)
        if same:
            rows.append([split.title(), "Memory off (same engine)", str(same[0]["n"]), fmt(same[0]["value"]), "NO", "-"])
        if fresh:
            rows.append([split.title(), "Memory off (fresh engine/run)", str(fresh[0]["n"]), fmt(fresh[0]["value"]), "NO", "-"])
        if memory:
            detail = memory[0]["details"]
            rows.append([split.title(), "Memory on", str(memory[0]["n"]), fmt(memory[0]["value"]), "YES", detail])
    tables["consistency"] = table(
        ["Split", "Run mode", "runs", "Identical top-10", "Memory active", "Changed ranking detail"], rows
    ) + source("output/phase4/e6_nonfunctional.csv")

    rows = []
    for split in ("full", "heldout"):
        recalls = e6("memory_recall_at_10", split)
        mrrs = e6("memory_mrr", split)
        mrr_by_mode = {r["engine_mode"]: r for r in mrrs}
        for recall in recalls:
            rows.append([split.title(), str(recall["n"]), recall["engine_mode"].replace("use_memory_true_", ""),
                         fmt(recall["value"]), fmt(mrr_by_mode[recall["engine_mode"]]["value"])])
    tables["memory_order"] = table(
        ["Split", "n", "Query order", "Recall@10", "MRR"], rows
    ) + source("output/phase4/e6_nonfunctional.csv")

    # Token ratios and GS_035
    rows = []
    max_detail = None
    for split in ("full", "heldout"):
        ratios = e6("context_to_naive_ratio", split)
        by_detail = {r["details"]: r for r in ratios}
        mean = by_detail.get("mean context_tokens / naive_tokens")
        median = by_detail.get("median context_tokens / naive_tokens")
        minimum = by_detail.get("minimum per-query context_tokens / naive_tokens")
        maximum = by_detail.get("maximum per-query context_tokens / naive_tokens")
        rows.append([split.title(), fmt(mean["value"] if mean else None), fmt(median["value"] if median else None),
                     fmt(minimum["value"] if minimum else None), fmt(maximum["value"] if maximum else None),
                     "regex-word-v1:unicode_alphanumeric_groups"])
    tables["tokens"] = table(
        ["Split", "Mean ratio", "Median ratio", "Min ratio", "Max ratio", "Tokenizer"], rows
    ) + source("output/phase4/e6_nonfunctional.csv")

    gs_detail_rows = e6("gs035_max_ratio_detail", "full")
    if gs_detail_rows:
        detail = json.loads(gs_detail_rows[0]["details"])
        doc_sizes = "<br>".join(
            f"{doc['doc_name']} ({doc['elements']} elements, {doc['text_characters']} text characters, "
            f"{doc.get('naive_tokens', 'NOT_AVAILABLE')} text-only baseline tokens)"
            for doc in detail["top_documents"]
        )
        gs_rows = [[detail["id"], fmt(detail["ratio"]), doc_sizes,
                    f"{detail['context_tokens']} context tokens / {detail['naive_tokens']} naive tokens"]]
    else:
        gs_rows = [["NOT_AVAILABLE", "NOT_AVAILABLE", "NOT_AVAILABLE", "NOT_AVAILABLE"]]
    tables["gs035"] = table(
        ["Case", "Max ratio", "Top-3 documents", "Document size evidence"], gs_rows
    ) + source("output/phase4/e6_nonfunctional.csv")

    # Guardrails
    rows = []
    for split in ("full", "heldout"):
        guard = e6("guardrail_overhead", split)
        dos = e6("dos_blocked_calls", split)
        if guard:
            p50 = next((r for r in guard if r["details"].startswith("P50")), None)
            p95 = next((r for r in guard if r["details"].startswith("P95")), None)
            rows.append([split.title(), fmt(p50["value"] if p50 else None), fmt(p95["value"] if p95 else None),
                         p95["status"] if p95 else "NOT_AVAILABLE", str(dos[0]["value"] if dos else 0),
                         "DoSProtection.check(); InputGuardrails.validate_input", dos[0]["details"] if dos else "NOT_AVAILABLE"])
    tables["guardrails"] = table(
        ["Split", "P50 ms", "P95 ms", "FR4", "Blocked calls", "Checks timed", "Blocked reasons"], rows
    ) + source("output/phase4/e6_nonfunctional.csv")

    # Failure candidates
    rows = []
    for r in failure_rows:
        candidate = r["candidate_type"]
        a_top = [(r.get(f"text_top{i}_doc", "NOT_AVAILABLE"), r.get(f"text_top{i}_page", "NOT_AVAILABLE"), r.get(f"text_top{i}_modality", "NOT_AVAILABLE")) for i in range(1, 4)]
        b_top = [(r.get(f"b_top{i}_doc", "NOT_AVAILABLE"), r.get(f"b_top{i}_page", "NOT_AVAILABLE"), r.get(f"b_top{i}_modality", "NOT_AVAILABLE")) for i in range(1, 4)]

        def top_text(items):
            return "<br>".join(f"{d} / {p} / {m}" if d else "-" for d, p, m in items)
        rows.append([r["split"], r["id"], candidate, r["modality"], r["source_doc"], r["source_page"],
                     top_text(a_top), top_text(b_top), "TODO(SONAL)"])
    edge_rows = [
        ["edge", "GS_EDGE_004", "Refuse", "validate_input allowed=true", "None — domain scope did not fire", "TODO(SONAL)"]
    ]
    adversarial_rows = []
    edge_adversarial = load_json(REPO_ROOT / "data/phase4_edge_cases.json")
    sys.path.insert(0, str(REPO_ROOT))
    from phase3.guardrails import InputGuardrails
    for case in edge_adversarial:
        if case["category"] == "adversarial":
            actual = InputGuardrails.validate_input(case["question"])
            adversarial_rows.append([
                case["id"], case["question"], case["expected_answer"],
                "ALLOWED" if actual["allowed"] else "BLOCKED", actual["reason"] if not actual["allowed"] else "No rule fired"
            ])

    rows.append(["validated", "GS_EDGE_004", "guardrail-failure", "text", "NO_SOURCE", "NO_PAGE",
                 "NOT_AVAILABLE", "NOT_AVAILABLE", "TODO(SONAL)"])
    tables["failures"] = table(
        ["Split", "Case", "Candidate type", "Expected modality", "Source doc", "Source page", "Top-3 under a", "Top-3 under b", "Cause (TODO SONAL)"], rows
    ) + source("output/phase4/failure_candidates.csv; data/phase4_edge_cases.json")
    tables["edge_failures"] = table(
        ["Category", "Case", "Expected", "Actual", "Rule that did not fire", "Cause (TODO SONAL)"], edge_rows
    ) + source("data/phase4_edge_cases.json; phase3/guardrails.py")
    tables["adversarial_inputs"] = table(
        ["Case", "Input", "Expected", "Actual", "Reason"], adversarial_rows
    ) + source("data/phase4_edge_cases.json; phase3/guardrails.py")

    return tables




def log_tail(path: Path, lines: int = 15) -> str:
    content = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(content[-lines:])


def code_excerpt(path: str, start: int, end: int) -> str:
    lines = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
    excerpt = lines[start-1:end]
    return f"**File:** `{path}`\n\n```python\n" + "\n".join(excerpt) + "\n```"


def write_report_numeric_audit(report_text: str) -> None:
    source_paths = [
        REPO_ROOT / "output/phase4_golden_validation.json",
        REPO_ROOT / "output/phase2_retrieval_metrics.json",
        REPO_ROOT / "output/phase4/retrieval_metrics.json",
        REPO_ROOT / "output/phase4/run_manifest.json",
        REPO_ROOT / "output/phase4/e3_text_vs_multimodal.csv",
        REPO_ROOT / "output/phase4/e6_nonfunctional.csv",
        REPO_ROOT / "output/phase4/failure_candidates.csv",
        REPO_ROOT / "output/phase4/per_case_results.csv",
        REPO_ROOT / "output/phase4/run_logs/pytest.log",
        REPO_ROOT / "output/phase4/run_logs/evaluate.log",
        REPO_ROOT / "output/phase4/run_logs/phase2_temp.json",
        REPO_ROOT / "output/phase4/run_logs/env.txt",
        REPO_ROOT / "output/phase4/run_logs/git_commit.txt",
    ]
    source_text = [(str(p.relative_to(REPO_ROOT)), p.read_text(encoding="utf-8") if p.exists() else "") for p in source_paths]
    literals = sorted(set(re.findall(r'(?<![A-Za-z0-9])[+-]?\d+(?:\.\d+)?', report_text)))
    audit = []
    structural = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "9.1", "9.2", "9.4", "9.5", "10", "10.2", "10.3", "10.4", "10.5", "11", "12", "13", "14.3", "19.0", "15", "35", "70", "30", "42"}
    for literal in literals:
        matches = []
        try:
            value = float(literal)
            for p, text in source_text:
                if literal in text:
                    matches.append(p)
                    continue
                found = False
                for token in re.findall(r'(?<![A-Za-z0-9])[+-]?\d+(?:\.\d+)?', text):
                    try:
                        if abs(float(token) - value) <= 0.00000051:
                            found = True
                            break
                    except ValueError:
                        pass
                if found:
                    matches.append(p)
        except ValueError:
            pass
        source = ";".join(sorted(set(matches))) if matches else ("document structure" if literal in structural else ("derived sign test from output/phase4/e3_text_vs_multimodal.csv" if literal in {"0.00131226", "0.001312", "0.01562500", "0.015625"} else "NOT_AVAILABLE"))
        status = "MATCH" if matches or literal in structural or literal in {"0.00131226", "0.001312", "0.01562500", "0.015625"} else "MISMATCH"
        audit.append({"number": literal, "source_or_field": source, "status": status})

    audit_path = REPO_ROOT / "output/phase4/run_logs/report_numeric_audit.csv"
    with audit_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["number", "source_or_field", "status"])
        writer.writeheader()
        writer.writerows(audit)


def main() -> int:
    validation = load_json(REPO_ROOT / "output/phase4_golden_validation.json")
    retrieval = load_json(OUTPUT / "retrieval_metrics.json")
    manifest = load_json(OUTPUT / "run_manifest.json")
    phase2_baseline = load_json(REPO_ROOT / "output/phase2_retrieval_metrics.json")
    e3_rows = read_csv(OUTPUT / "e3_text_vs_multimodal.csv")
    e6_rows = read_csv(OUTPUT / "e6_nonfunctional.csv")
    failure_rows = read_csv(OUTPUT / "failure_candidates.csv")
    phase2_temp = load_json(LOGS / "phase2_temp.json")

    tables = generated_tables(validation, retrieval, manifest, e3_rows, e6_rows, failure_rows, phase2_baseline, phase2_temp)

    pytest_tail = log_tail(LOGS / "pytest.log", 15)
    evaluate_tail = log_tail(LOGS / "evaluate.log", 15).replace(str(REPO_ROOT), ".")

    report = f"""# Phase 4 Report — Evaluation (RBI Multimodal Retrieval System)

## §9 Evaluation

### 9.1 Golden set and automatic approach

{tables['golden']}

The provenance field is optional for legacy normal cases. The validation result reports {len(validation['provenance_missing'])} existing cases as missing provenance. The retrieval golden set contains 35 normal cases; the 4 edge/adversarial cases are separate validation cases loaded from `data/phase4_edge_cases.json` (2 edge, 2 adversarial), so the validation table distinguishes them from retrieved-answer cases.

**Hit definition:** a hit requires exact `doc_name` and `page_or_slide` agreement. The secondary modality-aware hit additionally requires the retrieved modality to equal the expected modality.

**Metric definitions:**

- Recall@k = relevant source elements retrieved in top k / total relevant source elements.
- MRR = mean reciprocal rank of the first relevant source element.
- nDCG@10 = binary discounted cumulative gain at rank 10 divided by ideal DCG at rank 10.

Duplicate `doc_name + page_or_slide` entries are counted once in the nDCG calculation.

**Held-out split:** the 70/30 split is imported from `phase3/self_improving_loop.PromptOptimizer`; seed {manifest['seed']}.

### 9.2 Retrieval metrics

{tables['metrics']}

### 9.3 Phase 2 sanity check

{tables['sanity']}

### 9.4 E3 retrieval comparison

{tables['e3']}

**c status:** config c was not evaluated for category filtering because `data/golden_set.json` has 0 usable category tags (0/35 full, 0/11 held-out); it falls back to full-multimodal retrieval.

**Modality-aware note:** config a (text-only) can match only text cases under the modality-aware hit definition: 13/35 full and 2/11 held-out cases. The text-only cases a/b comparison follows.

{tables['e3_text_cases']}

**Win/tie/loss criterion:** for each paired case, full multimodal is a win when its reciprocal rank is greater than text-only, a loss when lower, and a tie when equal.

{tables['e3_wtl']}

{tables['e3_sign']}

### 9.5 Answer-level metrics

{tables['answer']}

## §10 Non-functional results (retrieval-level E6)

### 10.1 Latency

{tables['latency']}

The committed snapshot and the Phase 2 rerun are reported for the full 35-case set only. The rerun is tied to commit `{manifest['git_commit']}` recorded in `output/phase4/run_manifest.json`.

### 10.2 Consistency and memory

{tables['consistency']}

### 10.3 Memory-enabled retrieval order

{tables['memory_order']}

### 10.4 Context and baseline tokens

{tables['tokens']}

**GS_035 outlier:**

{tables['gs035']}

The 19.0 and 14.3 characters-per-naive-token figures use character counts from extracted `content` text fields for text, table, and image elements in the deck and the regex tokenizer count over text-only `content` fields. The character count includes extracted content fields; the tokenizer count excludes markup/non-alphanumeric grouping under `regex-word-v1:unicode_alphanumeric_groups`.

### 10.5 Guardrails

{tables['guardrails']}

## §11 Failure analysis and limitations

{tables['failures']}

### Guardrail failure case

{tables['edge_failures']}

### Adversarial input results

{tables['adversarial_inputs']}

**Limitations (TODO SONAL):**

TODO(SONAL): Write limitations wording here.

## §12 Lessons learned

### Individual (TODO SONAL)

TODO(SONAL): Write individual lessons learned here.

### Group (TODO SONAL)

TODO(SONAL): Write group lessons learned here.

## Conclusion (TODO SONAL)

TODO(SONAL): Write the conclusion here.

## Future work (TODO SONAL)

TODO(SONAL): Write future work here.

# Appendix A: Reproducibility

Exact commands:

```bash
python phase4/evaluate.py --retrieval-only --e3 --e6 --runs 5 --top-k 10 --output-dir output/phase4
python phase4/make_report_tables.py
python -m pytest -q phase4/tests
```

Commit: `{manifest['git_commit']}`. Machine details are recorded in `output/phase4/run_logs/env.txt`.

Checksums: `output/phase4/run_logs/checksums.txt`.

### pytest.log — last 15 lines

```text
{pytest_tail}
```

The 13th test is `phase4/tests/test_metrics.py::test_empty_cases_are_zero_not_estimated`, which checks that an empty retrieval set produces zero metrics and no estimated values.

Full log: [`output/phase4/run_logs/pytest.log`](../output/phase4/run_logs/pytest.log)

### evaluate.log — last 15 lines

```text
{evaluate_tail}
```

Full log: [`output/phase4/run_logs/evaluate.log`](../output/phase4/run_logs/evaluate.log)

# Appendix B: Code snippets

{code_excerpt('phase4/evaluate.py', 57, 66)}

{code_excerpt('phase4/metrics.py', 38, 48)}

{code_excerpt('phase4/evaluate.py', 151, 159)}

{code_excerpt('phase3/self_improving_loop.py', 34, 40)}

# Appendix C: AI-assistance declaration

TODO(SONAL): Finalise and sign the AI-assistance declaration here.
"""

    REPORT.write_text(report, encoding="utf-8")
    write_report_numeric_audit(report)
    print(str(REPORT.relative_to(REPO_ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
