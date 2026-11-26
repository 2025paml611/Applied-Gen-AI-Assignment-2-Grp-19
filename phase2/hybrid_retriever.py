"""Hybrid TF-IDF/BM25 retrieval with modality-aware reranking."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-+.][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


@dataclass(frozen=True)
class RetrievalResult:
    element_id: str
    doc_id: str
    doc_name: str
    category: str
    doc_format: str
    modality: str
    page_or_slide: int
    content: str
    score: float

    def citation(self) -> str:
        return f"[Source: {self.doc_name}, Page/Slide: {self.page_or_slide}]"


class BM25Index:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.tokenized = [tokenize(document) for document in documents]
        self.doc_freq = Counter()
        self.doc_lengths = np.array([len(tokens) for tokens in self.tokenized], dtype=np.float32)
        self.avg_length = float(self.doc_lengths.mean()) if len(self.doc_lengths) else 1.0
        self.k1 = k1
        self.b = b

        for tokens in self.tokenized:
            self.doc_freq.update(set(tokens))

        self.doc_count = len(documents)
        self.term_frequencies = [Counter(tokens) for tokens in self.tokenized]

    def search(self, query: str) -> np.ndarray:
        scores = np.zeros(self.doc_count, dtype=np.float32)
        query_terms = set(tokenize(query))

        for term in query_terms:
            df = self.doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.doc_count - df + 0.5) / (df + 0.5))
            for index, frequencies in enumerate(self.term_frequencies):
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * self.doc_lengths[index] / max(self.avg_length, 1.0)
                )
                scores[index] += idf * (frequency * (self.k1 + 1)) / denominator
        return scores


class HybridRetriever:
    def __init__(self, elements: Sequence[dict]):
        self.elements = list(elements)
        if not self.elements:
            raise ValueError("Cannot build a retriever from an empty corpus")

        self.documents = [
            " ".join(
                [
                    str(item.get("doc_name", "")),
                    str(item.get("category", "")),
                    str(item.get("modality", "")),
                    str(item.get("content", "")),
                ]
            )
            for item in self.elements
        ]
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_df=0.90,
        )
        self.tfidf = self.vectorizer.fit_transform(self.documents)
        self.bm25 = BM25Index(self.documents)

    @staticmethod
    def _normalize(scores: np.ndarray) -> np.ndarray:
        maximum = float(scores.max()) if len(scores) else 0.0
        minimum = float(scores.min()) if len(scores) else 0.0
        if maximum <= minimum:
            return np.zeros_like(scores)
        return (scores - minimum) / (maximum - minimum)

    def _modality_multiplier(self, query: str, modality: str) -> float:
        query_lower = query.lower()
        table_terms = ("ratio", "percentage", "rate", "threshold", "capital", "limit", "bps", "spread")
        image_terms = ("corridor", "diagram", "chart", "workflow", "process", "architecture", "timeline")

        if modality == "table" and any(term in query_lower for term in table_terms):
            return 1.18
        if modality == "image" and any(term in query_lower for term in image_terms):
            return 1.22
        return 1.0

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        modality: str | None = None,
        doc_name: str | None = None,
        category: str | None = None,
    ) -> list[RetrievalResult]:
        query_vector = self.vectorizer.transform([query])
        dense_scores = np.asarray((self.tfidf @ query_vector.T).toarray()).ravel()
        sparse_scores = self.bm25.search(query)

        dense_scores = self._normalize(dense_scores)
        sparse_scores = self._normalize(sparse_scores)
        fused = 0.65 * dense_scores + 0.35 * sparse_scores

        candidates: list[tuple[int, float]] = []
        for index, item in enumerate(self.elements):
            if modality and item["modality"] != modality.lower():
                continue
            if doc_name and item["doc_name"].lower() != doc_name.lower():
                continue
            if category and item["category"].lower() != category.lower():
                continue

            score = float(fused[index])
            score *= self._modality_multiplier(query, item["modality"])
            candidates.append((index, score))

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        selected = candidates[: max(top_k * 3, top_k)]
        if not selected:
            return []

        reranked = self._rerank(query, selected, top_k)
        results = []
        for index, score in reranked:
            item = self.elements[index]
            results.append(
                RetrievalResult(
                    element_id=str(item.get("element_id", "")),
                    doc_id=str(item.get("doc_id", "")),
                    doc_name=str(item.get("doc_name", "")),
                    category=str(item.get("category", "")),
                    doc_format=str(item.get("doc_format", "")),
                    modality=str(item.get("modality", "text")),
                    page_or_slide=int(item.get("page_or_slide", 0) or 0),
                    content=str(item.get("content", "")),
                    score=score,
                )
            )
        return results

    def _rerank(
        self,
        query: str,
        candidates: Sequence[tuple[int, float]],
        top_k: int,
    ) -> list[tuple[int, float]]:
        """Apply MMR-style diversity reranking to avoid duplicate page chunks."""
        remaining = list(candidates)
        selected: list[tuple[int, float]] = []

        while remaining and len(selected) < top_k:
            if not selected:
                best = max(remaining, key=lambda pair: pair[1])
            else:
                best = None
                best_score = -math.inf
                for candidate in remaining:
                    index, relevance = candidate
                    max_similarity = 0.0
                    candidate_doc = self.elements[index]["doc_name"] + ":" + str(
                        self.elements[index]["page_or_slide"]
                    )
                    for chosen_index, _ in selected:
                        chosen_doc = self.elements[chosen_index]["doc_name"] + ":" + str(
                            self.elements[chosen_index]["page_or_slide"]
                        )
                        if candidate_doc == chosen_doc:
                            max_similarity = 1.0
                            break
                    mmr_score = 0.82 * relevance - 0.18 * max_similarity
                    if mmr_score > best_score:
                        best_score = mmr_score
                        best = candidate
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
        return selected

