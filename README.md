# RBI Multimodal Retrieval System

Group project for **PCAM* ZG516 - Applied Generative AI, Assignment 2**. The project explores a retrieval-augmented workflow for finding evidence in Reserve Bank of India (RBI) regulatory documents and answering questions with document and page/slide references.

![Part A multimodal RAG architecture](report/architecture_diagram_part_a.png)

## Project workflow

The Part A system is organized into four phases:

1. **Corpus ingestion** - Download and assemble the RBI document collection, maintain its inventory, and provide parsed text, tables, and image descriptions.
2. **Retrieval engine** - Retrieve relevant parsed elements with hybrid TF-IDF/BM25 ranking, metadata filters, reranking, and short-term query memory.
3. **Guardrails and prompting** - Apply input checks and run prompt variants and prompt-optimization experiments.
4. **Evaluation** - Evaluate retrieval against a curated golden set and produce benchmark reports.

This repository currently contains the ingestion assets, the Phase 2 retrieval engine, and Phase 3 guardrail/prompting experiments. It does not contain a complete user-facing chatbot or a live LLM answer-generation service.

## Repository layout

| Path | Purpose |
| --- | --- |
| `data/corpus/` | RBI regulatory PDFs and supplementary PowerPoint briefing decks |
| `data/parsed_elements.json` | Extracted text, table contents, and image descriptions with source metadata |
| `data/corpus_inventory.csv`, `data/corpus_inventory.json` | Corpus inventory and document metadata |
| `data/golden_set.json` | Curated questions, expected answers, modalities, and source locations |
| `data/ontology.yaml` | Domain metadata and prompt-routing rules |
| `download_rbi_corpus.py` | Corpus download and briefing-deck generation script |
| `phase2/` | Hybrid retrieval engine, API, tests, and Phase 2 documentation |
| `phase3/` | Guardrails, prompt templates, self-improvement loop, and benchmark runner |
| `output/` | Benchmark and report output files |
| `report/` | Architecture diagram and project report resources |

### Corpus source note

The `download_rbi_corpus.py` script downloads regulatory PDFs from an RBI archive dataset and generates 10 supplementary briefing decks and diagrams. The generated decks are useful for project examples and multimodal demonstrations, but they are not original RBI publications. Verify regulatory facts against primary RBI documents before relying on them.

## Data ingestion

The current ingestion script is `download_rbi_corpus.py`. From the repository root, run:

```powershell
python download_rbi_corpus.py
```

It requires network access. The script selects up to 92 PDFs from the configured RBI archive dataset, downloads them into `data/corpus/`, generates 10 supplementary PowerPoint briefing decks and diagrams, and writes `data/corpus_inventory.json` and `data/corpus_inventory.csv`.

**Important scope detail:** the downloader does not parse PDFs or presentations into searchable chunks and does not create `data/parsed_elements.json`. That parsed-elements file is an existing project asset consumed by Phase 2. The parser implementation and a complete reproducible parse/rebuild command are not included in this repository yet. If you regenerate or replace corpus files, update/rebuild the parsed-elements data and inventory together before running retrieval.

The parsed-elements format is a JSON list. Each element contains fields such as `element_id`, `doc_id`, `doc_name`, `category`, `doc_format`, `page_or_slide`, `modality`, `content`, and optional metadata. Phase 2 indexes the element content and selected metadata; image records must contain useful extracted descriptions for text-based retrieval.

## Setup

Run commands from the repository root using Python 3.10 or later.

Install the retrieval engine dependencies:

```powershell
python -m pip install -r phase2/requirements.txt
```

The Phase 2 engine reads the parsed corpus at `data/parsed_elements.json`. The benchmark also reads `data/golden_set.json`.

## Run Phase 2 retrieval

Run the retrieval unit tests:

```powershell
python -m pip install pytest
python -m pytest -q phase2/tests/test_retrieval_engine.py
```

Run the retrieval benchmark against the golden set:

```powershell
python phase2/run_demo.py --top-k 10 --output-dir output
```

The engine can also be called from Python:

```python
from phase2.retrieval_engine import RetrievalEngine

engine = RetrievalEngine()
results = engine.search(
    "What is the statutory headline inflation target?",
    top_k=5,
)

for result in results:
    print(result.citation())
    print(result.content)
```

Optional search filters include `modality` (`text`, `table`, or `image`), `doc_name`, and `category`. Use `engine.format_context(results)` to assemble citation-bearing context for a downstream prompt.

## Run Phase 3 experiments

From the repository root:

```powershell
python phase3/run_benchmark.py
```

Phase 3 contains:

- `phase3/guardrails.py` - request-size/rate checks, prompt-injection detection, finance-domain scope checks, PII masking, and citation/grounding output checks.
- `phase3/prompt_templates.py` - zero-shot, f-string, three-shot, ontology/Jinja2, and CREATE-style prompt renderers.
- `phase3/self_improving_loop.py` - a seeded 70/30 development/held-out split and three prompt variants/iterations.
- `phase3/run_benchmark.py` - runs the guardrail, prompt-ablation, self-improvement, and consistency demonstrations, then writes a summary report.

The runner writes `guardrails_benchmark.csv`, `prompt_ablation_results.csv`, `self_improving_iterations.json`, `self_improving_log.csv`, `consistency_benchmark.csv`, and `phase3_report_summary.md` under the root `output/` directory. The prompt renderer can use `PyYAML` and `Jinja2` when installed; it has fallback behavior if either optional package is unavailable.

**Evaluation caveat:** the Phase 3 benchmark runner currently uses predefined sample responses, heuristic scores, and estimated token/latency values in places; these are not results from live model inference. Treat them as prototype/demo evidence, not as independently measured LLM performance.

## Current Phase 2 benchmark snapshot

The recorded run in `output/phase2_retrieval_metrics.json` evaluates 35 golden-set questions:

| Metric | Recorded result |
| --- | ---: |
| Recall@10 | 94.29% |
| MRR | 0.689 |
| P50 retrieval latency | 101.1 ms |
| P95 retrieval latency | 161.168 ms |

These are retrieval-only measurements from one environment and corpus snapshot. They do not measure answer-generation quality or latency. Rerun the benchmark after corpus or ranking changes.

## Phase 4: Evaluation

Validation:

```powershell
python phase4/validate_golden_set.py --edge-cases data/phase4_edge_cases.json --output output/phase4_golden_validation.json
```

Retrieval-only evaluation with E3 and E6:

```powershell
python phase4/evaluate.py --retrieval-only --e3 --e6 --runs 5 --top-k 10 --output-dir output/phase4
```

Generate report tables:

```powershell
python phase4/make_report_tables.py
```

Run Phase 4 tests:

```powershell
python -m pytest -q phase4/tests
```

Outputs are written under `output/phase4/`, including `retrieval_metrics.json`, `e3_text_vs_multimodal.csv`, `e6_nonfunctional.csv`, `failure_candidates.csv`, `run_manifest.json`, `phase4_summary.md`, and `run_logs/`. The group report is `docs/phase4_report.md`.

## Limitations

- The retrieval engine builds its TF-IDF and BM25 indexes in memory at startup; it does not persist an index or use a hosted vector database.
- The repository does not include the parser that produced `data/parsed_elements.json`; re-running the downloader alone is not enough to rebuild the complete retrieval corpus.
- Retrieval of image content depends on captions/descriptions already extracted into `data/parsed_elements.json`; Phase 2 does not perform OCR or image understanding.
- Query memory is in-process and short-term. It is not persistent across application restarts.
- Benchmark scores depend on the curated golden set and should be reviewed alongside per-question results in `output/phase2_retrieval_benchmark.csv`.
- This README documents the implemented Part A prototype; it is not a substitute for the assignment report, design diagrams, contribution statement, demonstration, or the individual Part B deliverables.


## Phase 4: Evaluation

Phase 4 evaluates the RBI multimodal retrieval system at **retrieval level**. It doesn't change any Phase 2 or Phase 3 code. It reuses the Phase 2 retrieval engine and the Phase 3 guardrails and `PromptOptimizer` 70/30 split (seed 42).

### What Phase 4 includes

- **Retrieval evaluation** on the 35-case golden set (13 text, 12 table, 10 image): Recall@1/5/10, MRR and nDCG@10, overall and per modality, on the full set and the held-out split.
- **E3: text-only vs full multimodal retrieval** (configs a and b) under two hit definitions (`doc_name + page_or_slide`, and the same plus a modality match), with per-case win/tie/loss counts and an exact two-sided sign test.
- **E6: retrieval-level non-functional checks**: search latency (P50/P95), consistency with memory off and on, memory and query-order effects, context vs naive baseline token ratios, and input guardrail overhead and DoS (FR4) behaviour.
- **Edge and adversarial case validation**: a separate set in `data/phase4_edge_cases.json` (2 edge, 2 adversarial), each with provenance and an expected outcome.
- **Report generator**: `phase4/make_report_tables.py` builds every table in `docs/phase4_report.md` from the saved outputs and writes a numeric audit.

### Requirements

- Python 3.14 (tested on macOS arm64)
- Dependencies from the existing `requirements.txt` (Phase 4 adds none)
- Phase 2 index and parsed corpus already built (`data/parsed_elements.json` and the vector store)

### Run order

Run every command from the repository root, one at a time.

```bash
# 1. Validate the golden set and the edge/adversarial cases
python3 phase4/validate_golden_set.py

# 2. Run the retrieval-only evaluation with E3 and E6
python3 phase4/evaluate.py --retrieval-only --e3 --e6 --runs 5 --top-k 10 --output-dir output/phase4 2>&1 | tee output/phase4/run_logs/evaluate.log

# 3. Run the tests
python3 -m pytest -v phase4/tests 2>&1 | tee output/phase4/run_logs/pytest.log

# 4. Generate the report tables and the numeric audit
python3 phase4/make_report_tables.py
```

### Key outputs

| File | Written by | Contents |
|---|---|---|
| `output/phase4_golden_validation.json` | `validate_golden_set.py` | Case counts by modality and type, validation result, provenance check |
| `output/phase4/retrieval_metrics.json` | `evaluate.py` | Recall@1/5/10, MRR, nDCG@10 (full and held-out, per modality) |
| `output/phase4/per_case_results.csv` | `evaluate.py` | Per-case ranks, reciprocal rank and hits |
| `output/phase4/e3_text_vs_multimodal.csv` | `evaluate.py --e3` | Config a vs b metrics, win/tie/loss, sign-test p-values |
| `output/phase4/failure_candidates.csv` | `evaluate.py --e3` | Recall@10 misses, b-vs-a losses and lowest-RR hits, with top-3 results under a and b |
| `output/phase4/e6_nonfunctional.csv` | `evaluate.py --e6` | Latency, consistency, memory order, token ratios (incl. GS_035 detail), guardrail overhead |
| `output/phase4/run_manifest.json` | `evaluate.py` | Commit hash, seed, flags, environment, answer-level status |
| `docs/phase4_report.md` | `make_report_tables.py` | Phase 4 report sections (§9–§12, appendices) |

### Run logs (`output/phase4/run_logs/`)

| File | Purpose |
|---|---|
| `evaluate.log` | Full console output of the evaluate run |
| `pytest.log` | Full test output |
| `env.txt` | Python version, OS and machine details |
| `git_commit.txt` | Commit hash the run was made from |
| `phase2_temp.json` | Phase 2 latency rerun on this machine (written by E6) |
| `checksums.txt` | SHA-256 hashes of the output CSV and JSON files |
| `report_numeric_audit.csv` | Every number in the report checked against its source file and field |

### Interpretation notes

- **Phase 4 is retrieval-only.** Answer-level metrics (correctness, faithfulness, citation accuracy, refusal accuracy, answer consistency, answer tokens, end-to-end latency, output guardrails) are reported as `NOT_RUN` because no LLM backend is configured.
- **Config c (category filtering) is not evaluated.** None of the 35 golden-set cases has a category label.
- **Config a can only score on text cases** under the modality-aware hit definition, so the a-vs-b comparison is also reported on text cases only.
- **Edge and adversarial cases are kept separate** from the 35-case golden set. They test input guardrails through `InputGuardrails.validate_input()`, not retrieval quality.
- **Latency depends on the machine.** Quote only numbers from the run tied to the commit in `run_manifest.json`.
- **Token counts use a regex word counter** (`regex-word-v1`), not a model tokenizer.

### Quick verification checklist

- [ ] `python3 -m pytest -q phase4/tests` reports 13 passed.
- [ ] The commit in `output/phase4/run_manifest.json` matches `git log -1`.
- [ ] `output/phase4/run_logs/report_numeric_audit.csv` has no non-`MATCH` rows.
- [ ] `shasum -a 256 -c` against `checksums.txt` succeeds for the output files.
- [ ] `git diff --stat phase2 phase3` is empty.
