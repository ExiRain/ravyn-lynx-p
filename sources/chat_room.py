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
from sources.chat_guard import ScamWatch

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

    # What she says when the streamer bans or times someone out. Never the
    # name: a scammer's or a troll's name is often the bait. Rotated.
    MODERATION_LINES = {
        "ban": ["Gone. The air is cleaner already.",
                "And they are out. Good.",
                "Bye. Do not come back.",
                "Removed. Nobody will miss that."],
        "timeout": ["Sit in the corner for a while.",
                    "A little quiet time for that one.",
                    "Timeout. Think about what you did."],
    }
    MODERATION_PRIORITY = 4
    MODERATION_GAP = 30.0       # at most one moderation remark per this

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
        # Moderation, for this stream: key -> until (a time, or inf for a
        # ban). Keys are "platform:login" and the user_key where one exists.
        self._removed: dict[str, float] = {}
        self._mod_turn: dict[str, int] = {}
        self._last_mod_remark = 0.0
        # Likely scammers: flagged once, answered once (warily), then skipped.
        self.scams = ScamWatch()
        self._warned: set[str] = set()

    @staticmethod
    def _keys(platform: str, user: str, user_key: str = "") -> list[str]:
        keys = [f"{platform}:{(user or '').strip().lower()}"] if user else []
        if user_key:
            keys.append(user_key)
        return keys

    def is_removed(self, platform: str, user: str = "",
                   user_key: str = "") -> bool:
        """Banned, or timed out and still serving it."""
        now = time.time()
        return any(self._removed.get(k, 0) > now
                   for k in self._keys(platform, user, user_key))

    def moderate(self, platform: str, user: str = "", user_key: str = "",
                 kind: str = "ban", seconds: float | None = None) -> int:
        """
        The streamer banned or timed someone out; how many waiting messages
        and replies of theirs were dropped.

        On 2026-11-09 she went on answering a scammer after he was banned:
        his messages were still in the batch and her replies in the queue.
        Both are cleared here, his later messages are ignored for as long as
        the ban or timeout lasts, and the dispatcher checks once more right
        before she speaks (Dispatcher.inflight_still_wanted).
        """
        keys = self._keys(platform, user, user_key)
        if not keys:
            return 0
        until = float("inf") if kind == "ban" else time.time() + (seconds or 600)
        for k in keys:
            self._removed[k] = max(self._removed.get(k, 0), until)

        def theirs(platform_, user_, key_):
            return bool(set(self._keys(platform_, user_, key_)) & set(keys))

        with self._buffer_lock:
            before = len(self._buffer)
            self._buffer = [m for m in self._buffer
                            if not theirs(m.platform, m.user, m.user_key)]
            dropped = before - len(self._buffer)
        dropped += self.queue.remove_where(
            lambda sig: sig.source == "chat" and theirs(
                sig.context.get("platform", "twitch"),
                sig.context.get("user", ""), sig.context.get("user_key", "")))
        print(f"[chat][{platform}] {kind}: {user or user_key} — "
              f"{dropped} waiting message(s)/reply(ies) dropped")
        self._remark(kind)
        return dropped

    def delete_message(self, platform: str, user: str, text: str) -> int:
        """One message deleted by a moderator: never answer it."""
        keys = set(self._keys(platform, user))
        text = (text or "").strip()
        with self._buffer_lock:
            before = len(self._buffer)
            self._buffer = [m for m in self._buffer
                            if not (set(self._keys(m.platform, m.user)) & keys
                                    and m.text.strip() == text)]
            dropped = before - len(self._buffer)
        dropped += self.queue.remove_where(
            lambda sig: sig.source == "chat" and sig.text.strip() == text
            and set(self._keys(sig.context.get("platform", "twitch"),
                               sig.context.get("user", ""))) & keys)
        return dropped

    def clear_all(self) -> int:
        """The whole chat was cleared: nothing waiting is answered."""
        with self._buffer_lock:
            dropped = len(self._buffer)
            self._buffer.clear()
        return dropped + self.queue.remove_where(lambda sig: sig.source == "chat")

    def _remark(self, kind: str) -> None:
        lines = self.MODERATION_LINES.get(kind)
        now = time.time()
        if not lines or now - self._last_mod_remark < self.MODERATION_GAP:
            return
        self._last_mod_remark = now
        turn = self._mod_turn.get(kind, 0)
        self._mod_turn[kind] = turn + 1
        self.queue.push(Signal(
            source="chat", priority=self.MODERATION_PRIORITY,
            text=lines[turn % len(lines)], mode="quote", skip_llm=True,
            ttl=60.0, context={"trigger": "moderation", "moderation": kind}))

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
        if self.is_removed(platform, user, user_key):
            return
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

        # Regulars are never flagged; the owner never reaches here.
        key = user_key or f"{platform}:{user.lower()}"
        scam = ([] if user.lower() in self.known_users
                else self.scams.observe(key, text))
        if scam and key in self._warned:
            print(f"[chat][{platform}] {user}: skipped — already answered "
                  f"once as a likely scam ({', '.join(scam)})")
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

    def _scam_context(self, msg: "ScoredMessage", ctx: dict) -> None:
        """Flag a likely scammer for the notebook; he is answered once."""
        if msg.user.lower() in self.known_users:
            return
        key = msg.user_key or f"{msg.platform}:{msg.user.lower()}"
        reasons = self.scams.reasons(key)
        if reasons:
            ctx["scam_suspect"] = True
            ctx["scam_reasons"] = reasons
            self._warned.add(key)
            print(f"[chat] {msg.user} looks like a scam: {', '.join(reasons)}")

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
        self._scam_context(winner, ctx)
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
