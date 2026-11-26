"""Small in-process conversation memory for follow-up retrieval."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class ConversationMemory:
    max_turns: int = 6
    turns: deque[dict] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.turns = deque(maxlen=self.max_turns)

    def add(self, query: str, context: list[str]) -> None:
        self.turns.append({"query": query, "context": list(context)})

    def expanded_query(self, query: str) -> str:
        prior = " ".join(
            turn["query"] for turn in list(self.turns)[-2:]
            if turn["query"]
        )
        if not prior:
            return query
        return f"{prior} {query}"

    def clear(self) -> None:
        self.turns.clear()

