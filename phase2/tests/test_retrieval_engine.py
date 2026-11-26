import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from phase2.retrieval_engine import RetrievalEngine


def test_retrieval_finds_inflation_source():
    engine = RetrievalEngine()
    results = engine.search(
        "What is the statutory headline inflation target?",
        top_k=5,
        use_memory=False,
    )
    assert results
    assert results[0].doc_name == "RBI_Presentation_Monetary_Policy_Framework_2024.pptx"
    assert results[0].page_or_slide >= 1


def test_follow_up_memory_expands_query():
    engine = RetrievalEngine()
    engine.search("What is the RBI inflation target?", top_k=3)
    expanded = engine.memory.expanded_query("What is the tolerance band?")
    assert "inflation" in expanded.lower()
    assert "tolerance" in expanded.lower()


def test_context_contains_citation_fields():
    engine = RetrievalEngine()
    results = engine.search("KYC periodic updation cycle", top_k=3, use_memory=False)
    context = engine.format_context(results)
    assert "Source:" in context
    assert "Page/Slide:" in context
