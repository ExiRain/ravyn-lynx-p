"""
Twitch chat source — raw IRC, anonymous read-only.

No OAuth, no 2FA, no twitchio. Just reads chat.
Uses justinfan anonymous login — Twitch allows read-only
connections without authentication.

Runs in its own thread. It only READS: every message is posted to the shared
ChatRoom (sources/chat_room.py), where scoring, batching and the owner fast
path happen once for every platform. TwitchChatSource IS that room when
Twitch runs, so other platforms (sources/youtube_chat.py) post into it too.
"""

from __future__ import annotations

import re
import socket
import ssl
import time

from app.settings import get_settings
from orchestrator.priority_queue import SignalQueue
from sources.chat_room import (  # noqa: F401  (re-exported for callers)
    BatchWindow, ChatRoom, ScoredMessage, score_message,
)

settings = get_settings()

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697  # TLS
NICK = "justinfan12345"

# parse PRIVMSG: :username!username@username.tmi.twitch.tv PRIVMSG #channel :message
PRIVMSG_RE = re.compile(r'^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.+)$')


class TwitchChatSource(ChatRoom):

    def __init__(self, queue: SignalQueue, known_users: set = None,
                 identity=None):
        super().__init__(queue, known_users=known_users, identity=identity)

    def run(self):
        """Entry point — runs in its own thread."""
        channel = settings.TWITCH_CHANNEL
        self.start()

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

    def _is_owner(self, user: str) -> bool:
        return bool(self.identity and self.identity.is_owner_chat(user))

    def _on_message(self, user: str, text: str):
        self.post("twitch", user, text, is_owner=self._is_owner(user))
