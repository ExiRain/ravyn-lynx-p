from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Signal:
    """A single unit of work for Ravyn to process."""

    source: str                         # "silence_filler", "chat", "eventsub", etc.
    priority: int                       # lower = higher priority (1 = highest)
    text: str                           # prompt seed, chat message, event text
    mode: str = "improv"                # "improv" (LLM) or "quote" (TTS direct)
    skip_llm: bool = False              # True = bypass LLM, send text straight to TTS
    created_at: float = field(default_factory=time.time)
    ttl: float | None = None            # seconds until expiry, None = never
    context: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl

    def to_request(self) -> dict:
        """Serialize to JSON for ravyn.request queue."""
        return {
            "text": self.text,
            "source": self.source,
            "mode": self.mode,
            "skip_llm": self.skip_llm,
            "context": self.context,
        }

    def __lt__(self, other: Signal) -> bool:
        """Fallback comparison for heapq tiebreaking."""
        return self.created_at < other.created_at