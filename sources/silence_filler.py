from __future__ import annotations

import json
import random
import time
from pathlib import Path

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


class SilenceFiller:

    PRIORITY = 10

    def __init__(self, queue: SignalQueue, data_dir: Path):
        self.queue = queue
        self.settings = get_settings()
        self._running = True

        self.last_activity = time.time()
        self.last_stunt = 0.0
        self.game_active = False   # set externally — completely disables filler

        self.seeds = self._load_json(data_dir / "stunts.json", "seeds")
        self.quotes = self._load_json(data_dir / "quotes.json", "quotes")

        print(f"[silence] Loaded {len(self.seeds)} seeds, {len(self.quotes)} quotes")

    @staticmethod
    def _load_json(path: Path, key: str) -> list[dict]:
        if not path.exists():
            print(f"[silence] WARNING: {path} not found")
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key, [])

    def on_activity(self, signal: Signal) -> None:
        if signal.source != "silence_filler":
            self.last_activity = time.time()
            if signal.source == "game":
                self.last_stunt = time.time()

    def _pick_signal(self) -> Signal | None:
        use_improv = self._should_improv()
        if use_improv:
            entry = self._pick_entry(self.seeds)
            if entry is None:
                return None
            return Signal(
                source="silence_filler", priority=self.PRIORITY,
                text=entry["text"], mode="improv", skip_llm=False,
                ttl=self.settings.SILENCE_SIGNAL_TTL,
                context={
                    "trigger": "silence_timer",
                    "seed_id": entry.get("id", ""),
                    "instruction": "This is your own thought. Nobody is talking to you. Riff on this in your own voice, one or two sentences max.",
                },
            )
        else:
            entry = self._pick_entry(self.quotes)
            if entry is None:
                return None
            return Signal(
                source="silence_filler", priority=self.PRIORITY,
                text=entry["text"], mode="quote", skip_llm=True,
                ttl=self.settings.SILENCE_SIGNAL_TTL,
                context={"trigger": "silence_timer", "quote_id": entry.get("id", "")},
            )

    def _should_improv(self) -> bool:
        s = self.settings
        improv_ok = s.IMPROV_ENABLED and len(self.seeds) > 0
        quote_ok = s.QUOTE_ENABLED and len(self.quotes) > 0
        if improv_ok and quote_ok:
            return random.random() < s.IMPROV_WEIGHT
        return improv_ok

    def _pick_entry(self, pool: list[dict]) -> dict | None:
        """
        A shuffled deck: every entry once, in random order, before any repeat.

        It used to pick at random from the least recently used HALF, so with
        ten seeds one could come back after five others — on 2026-11-02 six
        seeds were heard twice in one stream. Now a repeat needs the whole
        pool to have gone by first, and each new round deals the half used
        longest ago first, so even across the seam at least half the pool
        separates two uses of one entry.
        """
        if not pool:
            return None
        decks = self.__dict__.setdefault("_decks", {})
        deck = decks.get(id(pool))
        if not deck:
            by_age = sorted(pool, key=lambda e: e.get("last_used") or 0)
            half = len(by_age) // 2
            older, newer = by_age[:half], by_age[half:]
            random.shuffle(older)
            random.shuffle(newer)
            deck = newer + older            # pop() takes from the end: older first
            decks[id(pool)] = deck
        entry = deck.pop()
        # Strictly increasing, so two picks in the same instant still order.
        entry["last_used"] = max(time.time(), max(
            (e.get("last_used") or 0) for e in pool) + 1e-6)
        return entry

    def run(self) -> None:
        s = self.settings
        print(f"[silence] Filler active — threshold={s.SILENCE_THRESHOLD}s  interval={s.SILENCE_MIN_INTERVAL}s")

        while self._running:
            # completely skip during active games
            if self.game_active:
                time.sleep(10)
                continue

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

            time.sleep(10)

    def stop(self) -> None:
        self._running = False