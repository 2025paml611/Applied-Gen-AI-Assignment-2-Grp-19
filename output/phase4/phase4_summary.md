# Phase 4 Retrieval-Only Evaluation

## Hit definition
A hit is defined exactly as in `phase2/run_demo.py`: the retrieved result's `doc_name` equals the golden case's source document and `page_or_slide` equals the golden case's source page/slide.

## Case counts

| Split | Total | Text | Table | Image |
|---|---:|---:|---:|---:|
| Full | 35 | 13 | 12 | 10 |
| Held-out | 11 | 2 | 6 | 3 |

## Retrieval metrics

| Split | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| Full | 0.542857 | 0.914286 | 0.942857 | 0.689320 | 0.752094 |
| Held-out | 0.545455 | 1.000000 | 1.000000 | 0.703030 | 0.775960 |

## Phase 2 baseline sanity check

| Metric | Recorded Phase 2 | Current full run | Status |
|---|---:|---:|---|
| Recall@10 | 0.942857 | 0.942857 | MATCH |
| MRR | 0.689320 | 0.689320 | MATCH |

## E3: Text-only vs full multimodal
**Full** — win/tie/loss compares per-case reciprocal rank: win when full-multimodal RR is greater, loss when it is lower, tie when equal (ties excluded from the sign test). Overall: wins 16, ties 17, losses 2; exact two-sided sign-test p=0.00131226 (n=18 excluding ties).
| Modality | n | Wins | Ties | Losses |
|---|---:|---:|---:|---:|
| text | 13 | 3 | 9 | 1 |
| table | 12 | 10 | 2 | 0 |
| image | 10 | 3 | 6 | 1 |
Config (c) category coverage: 0/35 usable cases; fallback for remaining cases: no category filter; full-multimodal behavior.
Case-changing outcomes are listed in `e3_text_vs_multimodal.csv` with `record_type=pair`.
| Config | Hit definition | Recall@10 (n) | MRR (n) |
|---|---|---:|---:|
| text_only | doc_page | 0.714286 (n=35) | 0.501111 (n=35) |
| full_multimodal | doc_page | 0.942857 (n=35) | 0.689320 (n=35) |
| multimodal_metadata_filtered | doc_page | 0.942857 (n=35) | 0.689320 (n=35) |
| text_only | doc_page_modality | 0.371429 (n=35) | 0.309524 (n=35) |
| full_multimodal | doc_page_modality | 0.885714 (n=35) | 0.515510 (n=35) |
| multimodal_metadata_filtered | doc_page_modality | 0.885714 (n=35) | 0.515510 (n=35) |
Detailed per-modality metrics and n counts are reported in `e3_text_vs_multimodal.csv`.
**Heldout** — win/tie/loss compares per-case reciprocal rank: win when full-multimodal RR is greater, loss when it is lower, tie when equal (ties excluded from the sign test). Overall: wins 7, ties 4, losses 0; exact two-sided sign-test p=0.015625 (n=7 excluding ties).
| Modality | n | Wins | Ties | Losses |
|---|---:|---:|---:|---:|
| text | 2 | 1 | 1 | 0 |
| table | 6 | 5 | 1 | 0 |
| image | 3 | 1 | 2 | 0 |
Config (c) category coverage: 0/11 usable cases; fallback for remaining cases: no category filter; full-multimodal behavior.
Case-changing outcomes are listed in `e3_text_vs_multimodal.csv` with `record_type=pair`.
| Config | Hit definition | Recall@10 (n) | MRR (n) |
|---|---|---:|---:|
| text_only | doc_page | 0.545455 (n=11) | 0.354545 (n=11) |
| full_multimodal | doc_page | 1.000000 (n=11) | 0.703030 (n=11) |
| multimodal_metadata_filtered | doc_page | 1.000000 (n=11) | 0.703030 (n=11) |
| text_only | doc_page_modality | 0.181818 (n=11) | 0.136364 (n=11) |
| full_multimodal | doc_page_modality | 0.909091 (n=11) | 0.563636 (n=11) |
| multimodal_metadata_filtered | doc_page_modality | 0.909091 (n=11) | 0.563636 (n=11) |
Detailed per-modality metrics and n counts are reported in `e3_text_vs_multimodal.csv`.

## E6: Retrieval Non-functional Evaluation
**Full** (5 runs per query): identical top-10 IDs/order: same engine 100.00%, fresh engine 100.00%; retrieval P50 26.489 ms, P95 35.734 ms; phase2-equivalent warm P50 23.719 ms, P95 36.106 ms.
Tokens (regex-word-v1:unicode_alphanumeric_groups): context mean 1977.514, median 2084.000; naive top-3-document mean 59408.286, median 27045.000; ratio mean 0.097131, median 0.072849, min 0.004598, max 0.854452.
Guardrail overhead: P50 0.009 ms, P95 0.014 ms; FR4 (<6 s): PASS. Timed checks ran: DoSProtection.check() and InputGuardrails.validate_input(); validate_input ran prompt-injection/domain-scope/PII checks.
Reused engine with `use_memory=True`: identical top-10 100.00% across 5 runs; memory changed ranking versus no-memory for 34/35 queries. Timed DoSProtection.check() calls blocked: 0; reasons: {}.
Memory-enabled Recall@10/MRR by query order: golden: Recall@10=1.000000, MRR=0.659002 (n=35); seed_42: Recall@10=0.857143, MRR=0.399864 (n=35); seed_43: Recall@10=0.800000, MRR=0.443401 (n=35); seed_44: Recall@10=0.828571, MRR=0.457449 (n=35).
Maximum token ratio case: GS_035 = 0.854452 (1497 context tokens / 1752 naive tokens). Top-3 document size: RBI_Presentation_Payment_Vision_2025_Settlement.pptx (5 elements, 1730 text characters); 2025-09-25_Master-Direction_12898_Reserve Bank of India (Authentication mechanisms for digital payment transactions) Directions, 2025.pdf (9 elements, 12397 text characters); RBI_Presentation_Monetary_Policy_Framework_2024.pptx (6 elements, 1925 text characters).
Memory initialization: each of the 5 memory consistency runs starts with `memory.clear()`; queries then accumulate prior turns within that run via `use_memory=True`. Each golden/shuffle memory-order evaluation creates a fresh engine and clears memory before the first query.
Query memory: disabled (`use_memory=False`) in the original reused-engine consistency runs; memory-active ranking: no; ranking-effect check: not applicable because memory was not active.
**Heldout** (5 runs per query): identical top-10 IDs/order: same engine 100.00%, fresh engine 100.00%; retrieval P50 26.622 ms, P95 41.646 ms; phase2-equivalent warm P50 23.815 ms, P95 35.663 ms.
Tokens (regex-word-v1:unicode_alphanumeric_groups): context mean 2049.909, median 2142.000; naive top-3-document mean 56127.818, median 32087.000; ratio mean 0.128692, median 0.062412, min 0.009068, max 0.854452.
Guardrail overhead: P50 0.009 ms, P95 0.018 ms; FR4 (<6 s): PASS. Timed checks ran: DoSProtection.check() and InputGuardrails.validate_input(); validate_input ran prompt-injection/domain-scope/PII checks.
Reused engine with `use_memory=True`: identical top-10 100.00% across 5 runs; memory changed ranking versus no-memory for 10/11 queries. Timed DoSProtection.check() calls blocked: 0; reasons: {}.
Memory-enabled Recall@10/MRR by query order: golden: Recall@10=0.818182, MRR=0.462987 (n=11); seed_42: Recall@10=1.000000, MRR=0.387879 (n=11); seed_43: Recall@10=0.909091, MRR=0.461364 (n=11); seed_44: Recall@10=0.818182, MRR=0.401515 (n=11).
Maximum token ratio case: GS_035 = 0.854452 (1497 context tokens / 1752 naive tokens). Top-3 document size: RBI_Presentation_Payment_Vision_2025_Settlement.pptx (5 elements, 1730 text characters); 2025-09-25_Master-Direction_12898_Reserve Bank of India (Authentication mechanisms for digital payment transactions) Directions, 2025.pdf (9 elements, 12397 text characters); RBI_Presentation_Monetary_Policy_Framework_2024.pptx (6 elements, 1925 text characters).
Memory initialization: each of the 5 memory consistency runs starts with `memory.clear()`; queries then accumulate prior turns within that run via `use_memory=True`. Each golden/shuffle memory-order evaluation creates a fresh engine and clears memory before the first query.
Query memory: disabled (`use_memory=False`) in the original reused-engine consistency runs; memory-active ranking: no; ranking-effect check: not applicable because memory was not active.
Latency coverage: phase2/run_demo.py starts its timer immediately before `engine.search(..., use_memory=False, top_k=10)` and does not include engine construction or `format_context`; reranking is inside `search`. A cold engine search additionally includes TF-IDF/BM25 index construction only outside the Phase 2 timer, while that construction occurs when `RetrievalEngine` is created. The general E6 retrieval timer covers the same `search` span, plus fresh-engine searches also include engine construction in their loop; phase2-equivalent values below isolate the warm `search` span.
Phase 2 temp rerun on this machine (macOS-26.6.2-arm64-arm-64bit-Mach-O; CPU arm; Python 3.14.0): P50 25.492 ms, P95 40.985 ms.
Named timing runs: 23.592/31.416 ms was the direct temp-directory `phase2/run_demo.py` rerun performed earlier; 26.851/36.587 ms was the later temp rerun after verification changes. Both cover the same Phase 2 `run_demo.py` search-only span.
Committed Phase 2 baseline: P50 101.100 ms, P95 161.168 ms. The gap from the warm Phase 4 measurements is due to the timer span and machine/environment differences: the committed baseline records one Phase 2 `run_demo.py` search-only run per query, while Phase 4 also has fresh-engine loop timing that may include engine construction and warm-search timing with reranking. Neither timer includes `format_context`.
Answer consistency, answer-token count, and end-to-end latency are `NOT_RUN`: `no LLM backend` is configured.

## Answer-level metrics

| Metric | Status | Reason |
|---|---|---|
| Correctness | NOT_RUN | no LLM backend configured |
| Faithfulness | NOT_RUN | no LLM backend configured |
| Citation accuracy | NOT_RUN | no LLM backend configured |
| Refusal accuracy | NOT_RUN | no LLM backend configured |

No answer quality or LLM latency numbers are claimed in retrieval-only mode.
