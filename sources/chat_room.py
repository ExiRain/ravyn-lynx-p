"""
One chat room, however many platforms feed it.

Twitch (sources/twitch_chat.py) and YouTube (sources/youtube_chat.py) only
READ their chat and post each message here. Scoring, the batch window, the
one-winner contest and the owner fast path all live here, once — so a quiet
YouTube message and a busy Twitch chat compete for the same single answer.
Two rooms would each pick a winner per window and she would answer twice as
often whenever both were live.

Every message carries its platform, and a per-platform `user_key` where the
platform has a stable id: a "bob" on YouTube is not the "bob" on Twitch, and
the notebook keys per-person memory on that key when it is present.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.settings import get_settings
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue

settings = get_settings()


# =========================================================
# MESSAGE SCORING
# =========================================================

@dataclass
class ScoredMessage:
    user: str
    text: str
    score: float
    platform: str = "twitch"
    user_key: str = ""
    timestamp: float = field(default_factory=time.time)


def score_message(user: str, text: str, known_users: set) -> float | None:
    """Score a chat message. Returns None if filtered."""
    lower = text.strip().lower()

    if lower.startswith("!"):
        return None

    if len(lower) < 2:
        return None

    score = 0.0

    # mentions ravyn
    if "ravyn" in lower or "@ravyn" in lower:
        score += 10.0

    # question
    if "?" in text:
        score += 5.0

    # greeting
    greetings = {"hey", "yo", "hello", "hi", "sup", "hiya", "howdy"}
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in greetings:
        score += 3.0

    # substantive message
    word_count = len(text.split())
    if word_count > 5:
        score += 2.0
    elif word_count <= 2:
        score -= 1.0

    # known user
    if user.lower() in known_users:
        score += 1.0

    # Exiled does not go through scoring at all any more — see
    # ChatRoom.post. This bonus is left for the case where the identity file
    # is missing, so he is still favoured rather than ignored.
    #
    # Exact login only. "exiled" and "exiledr" are handles somebody else could
    # register, and a bonus is the mild version of the same mistake the owner
    # list makes: it would let an impersonator win batches against real chat.
    if user.lower() == "exiledra1n":
        score += 8.0

    return score


# =========================================================
# DYNAMIC BATCH WINDOW
# =========================================================

class BatchWindow:

    MIN_WINDOW = 5.0
    MAX_WINDOW = 15.0
    RATE_THRESHOLD = 6
    RATE_LOOKBACK = 30.0

    def __init__(self):
        self._timestamps: list[float] = []

    def record_message(self):
        now = time.time()
        self._timestamps.append(now)
        cutoff = now - self.RATE_LOOKBACK
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def get_window(self) -> float:
        rate = len(self._timestamps)
        if rate >= self.RATE_THRESHOLD:
            return self.MAX_WINDOW
        t = rate / self.RATE_THRESHOLD
        return self.MIN_WINDOW + t * (self.MAX_WINDOW - self.MIN_WINDOW)


# =========================================================
# THE ROOM
# =========================================================

class ChatRoom:

    PRIORITY = 5
    TTL = 120.0
    MAX_CONTEXT_MESSAGES = 3

    def __init__(self, queue: SignalQueue, known_users: set = None,
                 identity=None):
        self.queue = queue
        self.known_users = known_users or set()
        # Who the owner is on platforms that identify him by login (Twitch).
        # None means nobody is treated as owner there.
        self.identity = identity
        self._running = True
        self._buffer: list[ScoredMessage] = []
        self._buffer_lock = threading.Lock()
        self._batch_window = BatchWindow()
        self._batches_started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        """Start the batch processor once, whichever platform asks first."""
        with self._start_lock:
            if self._batches_started:
                return
            self._batches_started = True
        threading.Thread(target=self._batch_processor, daemon=True,
                         name="chat-batch").start()

    @staticmethod
    def _label(platform: str, user: str) -> str:
        """How a message is shown to her in recent_chat."""
        return user if platform == "twitch" else f"{user} ({platform})"

    def post(self, platform: str, user: str, text: str, *,
             user_key: str = "", is_owner: bool = False) -> None:
        """One message from any platform."""
        self._batch_window.record_message()

        # His messages bypass the contest AND the batch window.
        #
        # Scoring is a contest with one winner and the losers are thrown away,
        # so a viewer asking "hey ravyn, what do you think?" (10 + 5 + 3 + 2)
        # beat his "gg" (8 - 1) and his message was silently dropped. Waiting
        # out the batch window on top of that is latency he has no reason to
        # pay: he is one person, not a flood to be sampled.
        if is_owner:
            self._push_owner(platform, user, text, user_key)
            return

        score = score_message(user, text, self.known_users)
        if score is None:
            return

        msg = ScoredMessage(user=user, text=text, score=score,
                            platform=platform, user_key=user_key)
        with self._buffer_lock:
            self._buffer.append(msg)

        print(f"[chat][{platform}] {user} (score={score:.1f}): {text[:60]}")

    def _context(self, platform: str, user: str, user_key: str) -> dict:
        ctx = {"trigger": "chat_message", "user": user, "platform": platform}
        if user_key:
            ctx["user_key"] = user_key
        return ctx

    def _push_owner(self, platform: str, user: str, text: str,
                    user_key: str = "") -> None:
        """Straight to the queue, at OWNER_PRIORITY, never dropped."""
        with self._buffer_lock:
            context_msgs = [f"{self._label(m.platform, m.user)}: {m.text}"
                            for m in self._buffer[-self.MAX_CONTEXT_MESSAGES:]]

        ctx = self._context(platform, user, user_key)
        ctx.update({
            # Authoritative. The notebook keys her "this is your person"
            # framing off this rather than pattern-matching his name, so the
            # answer lives in one place on one machine.
            "is_owner": True,
            "recent_chat": context_msgs,
            "batch_size": 1,
        })
        self.queue.push(Signal(
            source="chat",
            priority=settings.OWNER_PRIORITY,
            text=text,
            mode="improv",
            skip_llm=False,
            ttl=self.TTL,
            context=ctx,
        ))
        print(f"[chat][{platform}] OWNER {user}: {text[:60]}")

    def flush(self) -> Signal | None:
        """Pick this window's winner across every platform, or None."""
        with self._buffer_lock:
            if not self._buffer:
                return None
            batch = list(self._buffer)
            self._buffer.clear()

        batch.sort(key=lambda m: m.score, reverse=True)
        winner = batch[0]

        context_msgs = [f"{self._label(m.platform, m.user)}: {m.text}"
                        for m in batch[1:self.MAX_CONTEXT_MESSAGES + 1]]

        ctx = self._context(winner.platform, winner.user, winner.user_key)
        ctx.update({
            "is_owner": False,
            "recent_chat": context_msgs,
            "batch_size": len(batch),
        })
        signal = Signal(
            source="chat",
            priority=self.PRIORITY,
            text=winner.text,
            mode="improv",
            skip_llm=False,
            ttl=self.TTL,
            context=ctx,
        )
        self.queue.push(signal)
        print(f"[chat] Picked {winner.platform}:{winner.user} "
              f"(score={winner.score:.1f}) from {len(batch)} messages")
        return signal

    def _batch_processor(self):
        """Periodically flush the buffer and push the winner."""
        time.sleep(3)   # let the platforms connect
        while self._running:
            time.sleep(self._batch_window.get_window())
            self.flush()

    def stop(self):
        self._running = False
