from __future__ import annotations

import json
import random
import time
from pathlib import Path

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


class SilenceFiller:
    """
    Generates signals when chat has been quiet for too long.

    Two modes:
      improv  — sends a seed prompt to LLM, Ravyn improvises
      quote   — sends a literal line straight to TTS, no LLM

    Selection is random weighted by IMPROV_WEIGHT.
    Recently used entries are deprioritized.
    Either mode can be toggled on/off at runtime.
    """

    PRIORITY = 10       # lowest priority — anything from a viewer wins

    def __init__(self, queue: SignalQueue, data_dir: Path):
        self.queue = queue
        self.settings = get_settings()
        self._running = True

        self.last_activity = time.time()
        self.last_stunt = 0.0

        # load data files
        self.seeds = self._load_json(data_dir / "stunts.json", "seeds")
        self.quotes = self._load_json(data_dir / "quotes.json", "quotes")

        print(f"[silence] Loaded {len(self.seeds)} seeds, {len(self.quotes)} quotes")

    # ---------------------------------------------------------
    # data loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_json(path: Path, key: str) -> list[dict]:
        if not path.exists():
            print(f"[silence] WARNING: {path} not found — empty pool")
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key, [])

    # ---------------------------------------------------------
    # activity tracking — called by dispatcher on every dispatch
    # ---------------------------------------------------------

    def on_activity(self, signal: Signal) -> None:
        """Reset silence timer on any non-self dispatch."""
        if signal.source != "silence_filler":
            self.last_activity = time.time()

    # ---------------------------------------------------------
    # selection logic
    # ---------------------------------------------------------

    def _pick_signal(self) -> Signal | None:

        use_improv = self._should_improv()

        if use_improv:
            entry = self._pick_entry(self.seeds)
            if entry is None:
                return None
            return Signal(
                source="silence_filler",
                priority=self.PRIORITY,
                text=entry["text"],
                mode="improv",
                skip_llm=False,
                context={
                    "trigger": "silence_timer",
                    "seed_id": entry.get("id", ""),
                    "instruction": (
                        "This is your own thought. Nobody is talking to you. "
                        "Riff on this idea in your own voice, one or two sentences max."
                    ),
                },
            )
        else:
            entry = self._pick_entry(self.quotes)
            if entry is None:
                return None
            return Signal(
                source="silence_filler",
                priority=self.PRIORITY,
                text=entry["text"],
                mode="quote",
                skip_llm=True,
                context={
                    "trigger": "silence_timer",
                    "quote_id": entry.get("id", ""),
                },
            )

    def _should_improv(self) -> bool:
        """Decide improv vs quote based on settings and what's enabled."""

        s = self.settings

        improv_ok = s.IMPROV_ENABLED and len(self.seeds) > 0
        quote_ok = s.QUOTE_ENABLED and len(self.quotes) > 0

        if improv_ok and quote_ok:
            return random.random() < s.IMPROV_WEIGHT
        elif improv_ok:
            return True
        elif quote_ok:
            return False
        else:
            return False    # nothing available

    def _pick_entry(self, pool: list[dict]) -> dict | None:
        """Pick a random entry, deprioritizing recently used ones."""

        if not pool:
            return None

        now = time.time()

        # sort by last_used (None/null = never used = highest priority)
        sorted_pool = sorted(
            pool,
            key=lambda e: e.get("last_used") or 0,
        )

        # take the older half (at least 1)
        candidate_count = max(1, len(sorted_pool) // 2)
        candidates = sorted_pool[:candidate_count]

        entry = random.choice(candidates)
        entry["last_used"] = now

        return entry

    # ---------------------------------------------------------
    # main loop — run in daemon thread
    # ---------------------------------------------------------

    def run(self) -> None:
        s = self.settings

        print(f"[silence] Filler active — threshold={s.SILENCE_THRESHOLD}s  "
              f"interval={s.SILENCE_MIN_INTERVAL}s")

        while self._running:
            now = time.time()
            silence_duration = now - self.last_activity
            since_last_stunt = now - self.last_stunt

            if (silence_duration >= s.SILENCE_THRESHOLD
                    and since_last_stunt >= s.SILENCE_MIN_INTERVAL):

                signal = self._pick_signal()

                if signal is not None:
                    self.queue.push(signal)
                    self.last_stunt = now
                    print(f"[silence] Queued {signal.mode}: {signal.text[:50]}...")

            time.sleep(10)    # check every 10 seconds

    def stop(self) -> None:
        self._running = False