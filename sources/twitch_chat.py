"""
Twitch chat source — raw IRC, anonymous read-only.
No OAuth, no 2FA, no twitchio. Just reads chat.

Uses justinfan anonymous login — Twitch allows read-only
connections without authentication.

Runs in its own thread.
"""

from __future__ import annotations

import socket
import ssl
import time
import threading
import re
from dataclasses import dataclass, field

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


settings = get_settings()

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697  # TLS
NICK = "justinfan12345"

# parse PRIVMSG: :username!username@username.tmi.twitch.tv PRIVMSG #channel :message
PRIVMSG_RE = re.compile(r'^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.+)$')


# =========================================================
# MESSAGE SCORING
# =========================================================

@dataclass
class ScoredMessage:
    user: str
    text: str
    score: float
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

    # exiled always gets attention
    if user.lower() in ("exiled", "exiledr","exiledra1n"):
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
# TWITCH CHAT SOURCE
# =========================================================

class TwitchChatSource:

    PRIORITY = 5
    TTL = 120.0
    MAX_CONTEXT_MESSAGES = 3

    def __init__(self, queue: SignalQueue, known_users: set = None):
        self.queue = queue
        self.known_users = known_users or set()
        self._running = True
        self._buffer: list[ScoredMessage] = []
        self._buffer_lock = threading.Lock()
        self._batch_window = BatchWindow()

    def add_known_user(self, user: str):
        self.known_users.add(user.lower())

    def run(self):
        """Entry point — runs in its own thread."""
        channel = settings.TWITCH_CHANNEL

        # start batch processor in a separate thread
        batch_thread = threading.Thread(
            target=self._batch_processor,
            daemon=True,
            name="twitch-batch",
        )
        batch_thread.start()

        while self._running:
            try:
                self._connect_and_listen(channel)
            except Exception as e:
                print(f"[twitch] Connection error: {e}")

            if self._running:
                print("[twitch] Reconnecting in 5s...")
                time.sleep(5)

    def _connect_and_listen(self, channel: str):
        """Connect to Twitch IRC and read messages."""

        print(f"[twitch] Connecting to {IRC_HOST}:{IRC_PORT}...")

        # TLS socket
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(300)  # 5 min timeout for reads
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(raw_sock, server_hostname=IRC_HOST)
        sock.connect((IRC_HOST, IRC_PORT))

        def send(msg: str):
            sock.sendall((msg + "\r\n").encode("utf-8"))

        # anonymous auth
        send(f"NICK {NICK}")
        send(f"JOIN #{channel}")

        print(f"[twitch] Connected as {NICK}, joined #{channel}")

        buf = ""

        while self._running:
            try:
                data = sock.recv(4096).decode("utf-8", errors="replace")
            except socket.timeout:
                # send a ping to keep alive
                send("PING :tmi.twitch.tv")
                continue
            except Exception as e:
                print(f"[twitch] Read error: {e}")
                break

            if not data:
                print("[twitch] Connection closed by server")
                break

            buf += data
            lines = buf.split("\r\n")
            buf = lines.pop()  # incomplete last line stays in buffer

            for line in lines:
                if not line:
                    continue

                # respond to PING to stay connected
                if line.startswith("PING"):
                    send("PONG :tmi.twitch.tv")
                    continue

                # parse PRIVMSG
                match = PRIVMSG_RE.match(line)
                if match:
                    user = match.group(1)
                    text = match.group(2).strip()
                    self._on_message(user, text)

        try:
            sock.close()
        except Exception:
            pass

    def _on_message(self, user: str, text: str):
        self._batch_window.record_message()

        score = score_message(user, text, self.known_users)
        if score is None:
            return

        msg = ScoredMessage(user=user, text=text, score=score)

        with self._buffer_lock:
            self._buffer.append(msg)

        print(f"[twitch] {user} (score={score:.1f}): {text[:60]}")

    def _batch_processor(self):
        """Periodically flush buffer, pick best message, push signal."""

        time.sleep(3)  # wait for connection

        while self._running:
            window = self._batch_window.get_window()
            time.sleep(window)

            with self._buffer_lock:
                if not self._buffer:
                    continue
                batch = list(self._buffer)
                self._buffer.clear()

            batch.sort(key=lambda m: m.score, reverse=True)
            winner = batch[0]

            # context from other messages
            context_msgs = []
            for msg in batch[1:self.MAX_CONTEXT_MESSAGES + 1]:
                context_msgs.append(f"{msg.user}: {msg.text}")

            signal = Signal(
                source="chat",
                priority=self.PRIORITY,
                text=winner.text,
                mode="improv",
                skip_llm=False,
                ttl=self.TTL,
                context={
                    "trigger": "chat_message",
                    "user": winner.user,
                    "recent_chat": context_msgs,
                    "batch_size": len(batch),
                },
            )

            self.queue.push(signal)
            print(f"[twitch] Picked: {winner.user} (score={winner.score:.1f}) "
                  f"from {len(batch)} messages, window={window:.1f}s")

    def stop(self):
        self._running = False