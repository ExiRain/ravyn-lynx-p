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
        if not pool:
            return None
        sorted_pool = sorted(pool, key=lambda e: e.get("last_used") or 0)
        candidates = sorted_pool[:max(1, len(sorted_pool) // 2)]
        entry = random.choice(candidates)
        entry["last_used"] = time.time()
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