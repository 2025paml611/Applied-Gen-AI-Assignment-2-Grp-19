"""High-level Phase 2 retrieval engine."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .corpus_store import load_corpus
from .hybrid_retriever import HybridRetriever, RetrievalResult
from .memory import ConversationMemory


class RetrievalEngine:
    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root or Path(__file__).resolve().parent.parent)
        self.elements = load_corpus(self.repo_root)
        self.retriever = HybridRetriever(self.elements)
        self.memory = ConversationMemory()

    def search(
        self,
        query: str,
        top_k: int = 10,
        modality: str | None = None,
        doc_name: str | None = None,
        category: str | None = None,
        use_memory: bool = True,
    ) -> list[RetrievalResult]:
        expanded_query = self.memory.expanded_query(query) if use_memory else query
        results = self.retriever.retrieve(
            expanded_query,
            top_k=top_k,
            modality=modality,
            doc_name=doc_name,
            category=category,
        )
        if use_memory:
            self.memory.add(query, [result.citation() for result in results])
        return results

    def format_context(self, results: Iterable[RetrievalResult]) -> str:
        blocks = []
        for result in results:
            blocks.append(
                f"[{result.modality.upper()} | "
                f"Source: {result.doc_name}, "
                f"Page/Slide: {result.page_or_slide}]\n{result.content}"
            )
        return "\n\n---\n\n".join(blocks)

