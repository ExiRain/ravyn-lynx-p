"""
Mock LoL game event source for testing.
Fires fake kills, deaths, objectives with 15s TTL.
These should expire if Ravyn is busy — that's the intended behavior.
Replace with real LoL Live Game API integration later.
"""

from __future__ import annotations

import random
import time

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue


GAME_EVENTS = [
    "You just got a double kill on bot lane!",
    "You died to the enemy jungler in river.",
    "Dragon is spawning in 30 seconds.",
    "Your team just took Baron Nashor!",
    "Enemy team got first blood.",
    "You hit a 3-man Riven ult in the teamfight!",
    "Tower destroyed — mid lane is open.",
    "You got ganked top. Again.",
    "Elder dragon is up — this is the fight.",
    "Pentakill! Wait, no, they flashed out.",
]


class MockGameSource:
    """Generates fake game event signals with short TTL for testing."""

    PRIORITY = 3
    TTL = 15.0      # stale extremely fast — if busy, these expire and get dropped

    def __init__(self, queue: SignalQueue, min_interval: float = 20.0, max_interval: float = 60.0):
        self.queue = queue
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._running = True

    def run(self) -> None:
        print(f"[mock_game] Active — interval={self.min_interval}-{self.max_interval}s  TTL={self.TTL}s")

        while self._running:
            wait = random.uniform(self.min_interval, self.max_interval)
            time.sleep(wait)

            event = random.choice(GAME_EVENTS)

            signal = Signal(
                source="game",
                priority=self.PRIORITY,
                text=event,
                mode="improv",
                skip_llm=False,
                ttl=self.TTL,
                context={
                    "trigger": "game_event",
                    "game": "league_of_legends",
                },
            )

            self.queue.push(signal)
            print(f"[mock_game] {event[:50]}...")

    def stop(self) -> None:
        self._running = False
