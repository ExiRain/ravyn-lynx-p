"""
Mock Twitch chat source for testing.
Fires fake chat messages at random intervals.
Replace with real Twitch IRC integration later.
"""

from __future__ import annotations

import random
import time

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


FAKE_USERS = [
    "CoolViewer42", "xX_Shadow_Xx", "fluffycat99",
    "NightOwl_", "PixelDemon", "StreamFan2024",
]

FAKE_MESSAGES = [
    "hey ravyn!",
    "what are you thinking about?",
    "do you like foxes?",
    "your ears are cute",
    "who's winning?",
    "play something fun",
    "are you an AI?",
    "hello from chat!",
    "ravyn do a backflip",
    "what's your favorite color?",
    "tell us a joke",
    "can you sing?",
]


class MockChatSource:
    """Generates fake chat signals for orchestrator testing."""

    PRIORITY = 5
    TTL = 120.0

    def __init__(self, queue: SignalQueue, min_interval: float = 15.0, max_interval: float = 45.0):
        self.queue = queue
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._running = True

    def run(self) -> None:
        print(f"[mock_chat] Active — interval={self.min_interval}-{self.max_interval}s")

        while self._running:
            wait = random.uniform(self.min_interval, self.max_interval)
            time.sleep(wait)

            user = random.choice(FAKE_USERS)
            message = random.choice(FAKE_MESSAGES)

            signal = Signal(
                source="chat",
                priority=self.PRIORITY,
                text=message,
                mode="improv",
                skip_llm=False,
                ttl=self.TTL,
                context={
                    "trigger": "chat_message",
                    "user": user,
                },
            )

            self.queue.push(signal)
            print(f"[mock_chat] {user}: {message}")

    def stop(self) -> None:
        self._running = False
