"""
Mock Twitch EventSub source for testing.
Fires fake subs and follows at random intervals.
Replace with real EventSub integration later.
"""

from __future__ import annotations

import random
import time

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue


FAKE_SUBS = [
    ("WhaleLord99", "just subscribed with a Tier 1 sub!"),
    ("BigDonor_", "subscribed for 6 months in a row!"),
    ("LoyalFan2025", "gifted 5 subs to the community!"),
]

FAKE_FOLLOWS = [
    "NewViewer_123",
    "JustPassingBy",
    "CuriousCat77",
    "FirstTimeHere",
]


class MockEventSource:
    """Generates fake sub/follow signals for orchestrator testing."""

    def __init__(self, queue: SignalQueue, min_interval: float = 30.0, max_interval: float = 90.0):
        self.queue = queue
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._running = True

    def run(self) -> None:
        print(f"[mock_events] Active — interval={self.min_interval}-{self.max_interval}s")

        while self._running:
            wait = random.uniform(self.min_interval, self.max_interval)
            time.sleep(wait)

            # 40% sub, 60% follow
            if random.random() < 0.4:
                self._fire_sub()
            else:
                self._fire_follow()

    def _fire_sub(self) -> None:
        user, event_text = random.choice(FAKE_SUBS)

        signal = Signal(
            source="eventsub",
            priority=1,        # highest priority
            text=f"{user} {event_text}",
            mode="improv",
            skip_llm=False,
            ttl=None,          # never expires
            context={
                "trigger": "subscription",
                "event_type": "sub",
                "user": user,
            },
        )

        self.queue.push(signal)
        print(f"[mock_events] SUB: {user} {event_text}")

    def _fire_follow(self) -> None:
        user = random.choice(FAKE_FOLLOWS)

        signal = Signal(
            source="eventsub",
            priority=1,
            text=f"{user} just followed the channel!",
            mode="improv",
            skip_llm=False,
            ttl=None,
            context={
                "trigger": "follow",
                "event_type": "follow",
                "user": user,
            },
        )

        self.queue.push(signal)
        print(f"[mock_events] FOLLOW: {user}")

    def stop(self) -> None:
        self._running = False
