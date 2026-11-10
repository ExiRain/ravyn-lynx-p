"""
Who in chat is probably trying to scam the streamer.

On 2026-11-09 a first-time chatter opened with flattery ("you're amazing and
I have dropped a follow"), asked to "connect after work", then "Let's connect
on discord", then posted a Discord handle — the shape of the scam small
streamers get every week. Ravyn answered all four warmly, and kept talking
about him after he was banned.

This only FLAGS. Nothing is blocked on a guess: a flagged chatter still gets
one reply, and the notebook frames it (ravyn-nb persona/context_templates.py,
CHAT_SCAM) so she is dry and does not take the bait or repeat a handle or a
link. After that one reply, his flagged messages are skipped.

Strong signs flag on their own. Weak ones (a Discord mention, "let's
connect") are things regulars say too, so it takes two different ones from
the same person — over the stream, not in one message, because the pitch is
spread across several.
"""

from __future__ import annotations

import re

# (label, pattern, strong). Matched case-insensitively against one message.
SIGNS = [
    ("sells viewers or followers",
     r"\b(buy|cheap|best|real|free|get)\s+(more\s+)?(viewers|followers|views|primes|subs)\b"
     r"|\bview\s?bots?\b|\b(followers|viewers),?\s+(primes|and viewers)\b", True),
    ("pitches design work",
     r"\bgraphic designer\b|\b(make|design|create)\s+(you\s+)?(an?\s+|some\s+)?"
     r"(logo|overlay|emotes?|panels?|banner|alerts)\b|\bcommissions?\s+open\b", True),
    ("offers promotion",
     r"\bpromot(e|ion|ing)\s+(your|ur)\b|\bgrow\s+(your|ur)\s+(channel|stream)\b"
     r"|\bbecome\s+famous\b", True),
    ("talks money or crypto",
     r"\b(crypto|bitcoin|btc|nft|forex)\b|\binvest(ment|ing)?\s+(opportunity|plan)\b"
     r"|\byou\s+(have\s+)?won\b", True),
    ("moves you to a private app",
     r"\b(discord|telegram|whats\s?app|snapchat|snap)\b", False),
    ("asks you to DM",
     r"\b(dm|message|text|add)\s+me\b|\bcheck\s+(your\s+)?(dms?|inbox)\b"
     r"|\bsent\s+you\s+a\s+(dm|message)\b", False),
    ("wants to 'connect' or collab",
     r"\blet'?s\s+connect\b|\bconnect\s+(with\s+you|after|on|via|later)\b"
     r"|\bcollab(oration|orate)?\b|\bwork\s+together\b"
     r"|\bbusiness\s+(proposal|offer|inquiry|opportunity)\b|\bpartnership\b", False),
    ("posts a link",
     r"https?://|\bwww\.|\b\w+\s?(\.|\(dot\)|\bdot\b)\s?(com|gg|ly|ru|xyz|io|me)\b", False),
]

_COMPILED = [(label, re.compile(rx, re.IGNORECASE), strong)
             for label, rx, strong in SIGNS]


def signs_in(text: str) -> list[tuple[str, bool]]:
    """(label, strong) for every sign in one message."""
    return [(label, strong) for label, rx, strong in _COMPILED
            if rx.search(text or "")]


class ScamWatch:
    """Per-person tally over one stream."""

    def __init__(self):
        self._seen: dict[str, dict[str, bool]] = {}

    def observe(self, key: str, text: str) -> list[str]:
        """Record one message; the person's reasons if they are now flagged."""
        found = self._seen.setdefault(key, {})
        for label, strong in signs_in(text):
            found[label] = found.get(label, False) or strong
        return self.reasons(key)

    def reasons(self, key: str) -> list[str]:
        found = self._seen.get(key, {})
        if any(found.values()) or len(found) >= 2:
            return sorted(found)
        return []
