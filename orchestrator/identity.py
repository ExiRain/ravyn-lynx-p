"""
Who Exiled is — one file, one loader, every consumer.

His name was being matched in three unrelated places: `data/identity.json` for
League event names, a hardcoded tuple in `sources/twitch_chat.py` scoring, and
another hardcoded tuple in the notebook's `context_builder`. Three copies of
one fact is three chances for it to drift, and the notebook's copy could not be
edited without a deploy.

Two name lists, because they are genuinely different identities:

  names        League accounts, including the RU server. Matched against EVENT
               names, whose format differs from `allPlayers` and which have
               already been seen non-Latin in the wild.
  chat_names   Twitch login, and whatever the voice source resolves to when it
               lands. This is the one that decides she is talking to HIM.

Matching ignores case, spaces and punctuation and treats a "#TAG" suffix as
optional, so a spacing typo in a hand-written file cannot silently cost a
stream.
"""

from __future__ import annotations

import json
from pathlib import Path


def normalise(name: str) -> str:
    """
    Case, spaces and punctuation removed. Letters of ANY script are kept.

    An ASCII-only version of this silently dropped "Серый Экран" to the empty
    string, so his RU account was never in the known-names set at all — the
    startup log said "4 known account name(s)" for a five-name file, which is
    the kind of off-by-one nobody reads. `isalnum` is Unicode-aware; a
    character-class of [a-z0-9] is not.
    """
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


class Identity:
    """His names. Reload-free: read once at startup, edited between runs."""

    def __init__(self, path: Path | None = None):
        self.game_names: set[str] = set()
        self.chat_names: set[str] = set()
        if path is not None:
            self.load(path)

    def load(self, path: Path) -> None:
        if not path.exists():
            print(f"[identity] No {path.name} — falling back to API matching "
                  f"only, and no owner recognition in chat")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception as e:
            print(f"[identity] Could not read {path.name}: {e}")
            return

        self.game_names = self._names(data.get("names"))
        self.chat_names = self._names(data.get("chat_names"))

        print(f"[identity] {len(self.game_names)} game name(s), "
              f"{len(self.chat_names)} chat name(s) from {path.name}")

    @staticmethod
    def _names(raw) -> set[str]:
        if isinstance(raw, str):
            raw = [raw]
        out = set()
        for name in raw or []:
            key = normalise(name)
            if key:
                out.add(key)
                # "Exiled Rain#EUW" should also match "Exiled Rain"
                if "#" in str(name):
                    short = normalise(str(name).split("#")[0])
                    if short:
                        out.add(short)
        return out

    # ---------------------------------------------------------

    def is_owner_chat(self, user: str) -> bool:
        """Is this chat/voice speaker him?"""
        return self._matches(user, self.chat_names)

    def is_owner_game(self, name: str) -> bool:
        """Is this League event name him?"""
        return self._matches(name, self.game_names)

    @staticmethod
    def _matches(name: str, against: set[str]) -> bool:
        if not name or not against:
            return False
        key = normalise(name)
        if key in against:
            return True
        if "#" in name:
            return normalise(name.split("#")[0]) in against
        return False
