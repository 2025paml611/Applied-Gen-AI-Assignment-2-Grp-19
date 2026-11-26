# Phase 2 - Retrieval Engine

This package implements the retrieval component shown in `report/architecture_diagram_part_a.png`.

## Components

- `corpus_store.py`: loads and cleans multimodal corpus elements.
- `hybrid_retriever.py`: combines TF-IDF dense retrieval and BM25 sparse retrieval, then applies modality and source-aware reranking.
- `memory.py`: retains short-term follow-up query context.
- `retrieval_engine.py`: provides the public search and context-formatting API.
- `run_demo.py`: evaluates the engine on `data/golden_set.json`.

## Run

```powershell
python -m pytest -q phase2/tests/test_retrieval_engine.py
python phase2/run_demo.py --top-k 10 --output-dir output
```

The benchmark writes:

- `output/phase2_retrieval_benchmark.csv`
- `output/phase2_retrieval_metrics.json`
