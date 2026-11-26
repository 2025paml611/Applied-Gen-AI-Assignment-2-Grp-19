# Phase 2 - Multimodal Retrieval Engine

Phase 2 implements the retrieval-engine stage in [`report/architecture_diagram_part_a.png`](../report/architecture_diagram_part_a.png). It loads the text, table, and image-description elements produced by Phase 1, retrieves relevant elements for a query, and formats the results as cited context for the Phase 3 prompting layer.

The retrieval engine does not generate answers or perform OCR itself. It searches the extracted content in `data/parsed_elements.json`; image retrieval therefore depends on the captions or text descriptions already present in that file.

## Retrieval flow

1. Load and normalize parsed elements and their document, category, modality, and page/slide metadata.
2. Build an in-memory TF-IDF index and a BM25 index over the content and selected metadata.
3. Search both indexes and combine their normalized scores (TF-IDF 65%, BM25 35%).
4. Apply optional modality, document-name, and category filters, with query-sensitive boosts for table- and image-related questions.
5. Rerank the candidate list to favor relevance while discouraging repeated results from the same document page.
6. Optionally add recent queries from short-term conversation memory and format retrieved chunks with source and page/slide information.

Indexes are built in memory when `RetrievalEngine` is initialized. No external vector database or embedding model is required.

## Package contents

- `corpus_store.py` locates, loads, and normalizes `data/parsed_elements.json`.
- `hybrid_retriever.py` implements TF-IDF/BM25 retrieval, metadata filters, score fusion, and diversity reranking.
- `memory.py` keeps a bounded history of recent queries for follow-up query expansion.
- `retrieval_engine.py` exposes the high-level `RetrievalEngine` API and cited context formatting.
- `run_demo.py` evaluates source retrieval against the hand-curated golden set.
- `tests/test_retrieval_engine.py` contains focused retrieval and memory tests.

## Requirements and setup

Use Python 3.10 or later. From the repository root, install the Phase 2 dependencies:

```powershell
python -m pip install -r phase2/requirements.txt
```

The engine expects the Phase 1 corpus files at:

- `data/parsed_elements.json`
- `data/golden_set.json` (benchmark only)

## Run tests and benchmark

Run the unit tests:

```powershell
python -m pytest -q phase2/tests/test_retrieval_engine.py
```

Run retrieval evaluation against the 35-question golden set:

```powershell
python phase2/run_demo.py --top-k 10 --output-dir output
```

The benchmark reports Recall@k, MRR, and P50/P95 retrieval latency. Per-question results and aggregate metrics are written to:

- `output/phase2_retrieval_benchmark.csv`
- `output/phase2_retrieval_metrics.json`

These are retrieval-only measurements; they do not include answer-generation latency or answer-quality evaluation.

## Use the API

From the repository root:

```python
from phase2.retrieval_engine import RetrievalEngine

engine = RetrievalEngine()
results = engine.search(
    "What is the statutory headline inflation target?",
    top_k=5,
    modality="text",  # optional: "text", "table", or "image"
)

for result in results:
    print(result.citation())
    print(result.content)

context = engine.format_context(results)
```

`search` also accepts optional `doc_name` and `category` filters. Set `use_memory=False` to search the current query without recent-query expansion. Call `engine.memory.clear()` to reset conversation history.

Each result includes its element/document identifiers, category, file format, modality, page or slide, content, score, and a citation string.

## Current benchmark snapshot

The recorded run in `output/phase2_retrieval_metrics.json` contains 35 golden questions and reports:

| Metric | Recorded result |
| --- | ---: |
| Recall@10 | 94.29% |
| MRR | 0.689 |
| P50 retrieval latency | 101.1 ms |
| P95 retrieval latency | 161.168 ms |

These figures describe that benchmark run on the current environment and corpus; rerun the command above to reproduce measurements on another machine or after changing the corpus or ranking logic.
