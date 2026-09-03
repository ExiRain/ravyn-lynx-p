"""
What Exiled told her about his own account.

The other half of STATUS.md §7's governing principle. `game_state.py` holds
what the API measured; this holds what he said. Both reach the prompt, under
separate headings, because the difference matters:

    She may only assert things you told her, or things the API measured.
    Never anything she would have to know about League.

"You are forty CS down" is measurement. "I never win this lane" is his, and
carries only because he wrote it — she is repeating him, not analysing a
matchup. Blending the two would let her launder an opinion into a fact, which
is the exact failure §7 exists to prevent, so `render()` labels them.

Nothing here is required. A missing champion, a missing role, an empty file:
the line does not fire and she falls back to what she does know. §7 is explicit
that the file is never finished and never needs to be.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# A note still carrying this is the shipped example, not his writing. It must
# never reach the model: the first live run had her open a game with "That only
# when a friend duos comment? It sounds like you're just trying to explain
# away" — she was gamely trying to make sense of the literal word PLACEHOLDER.
# Shipping example text down the same path as real text was the mistake; the
# file is a template, so the template markers have to be inert.
PLACEHOLDER_MARKER = "PLACEHOLDER"


def is_placeholder(value: str) -> bool:
    return PLACEHOLDER_MARKER in (value or "").upper()


def normalise(name: str) -> str:
    """
    'Lee Sin', 'leesin' and "Kai'Sa" all collapse to one key.

    The API's championName is a display name, so it carries spaces, apostrophes
    and ampersands ("Nunu & Willump"). Requiring him to reproduce that exactly
    in a hand-written file guarantees silent misses.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# Wukong is the one champion whose API name is nothing like his display name.
# Kept as an explicit alias rather than a general rule: it is a known quirk, and
# guessing at others would be inventing data.
ALIASES = {
    "monkeyking": "wukong",
}


def key(name: str) -> str:
    n = normalise(name)
    return ALIASES.get(n, n)


@dataclass
class ChampionRead:
    """Everything the file has to say about one game, already resolved."""

    champion: str = ""
    role: str = ""

    role_skill: str = ""            # his own word: best / worst / ok / none
    role_read: str = ""
    champion_history: str = ""
    offrole: bool = False           # playing a champion outside its main role
    offrole_read: str = ""

    # (enemy champion, his note, how confident we are it is a lane matchup)
    matchups: list[tuple[str, str, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        # `offrole` alone is not content — it is a flag about a note that may
        # itself have been a placeholder. Only actual text counts.
        return bool(self.role_read or self.champion_history
                    or self.offrole_read or self.matchups)

    def render(self) -> str:
        """
        A block for the prompt, explicitly attributed to him.

        The heading is doing real work: the SITUATION block tells her not to
        state anything about the game beyond it, and without this label that
        would silently forbid the very lines this file exists to produce.
        """
        if not self:
            return ""

        lines: list[str] = []

        if self.offrole and self.offrole_read:
            lines.append(f"On playing {self.champion} here: "
                         f"\"{self.offrole_read}\"")
        if self.champion_history:
            lines.append(f"On {self.champion}: \"{self.champion_history}\"")
        if self.role_read:
            where = f"On playing {self.role}" if self.role else "On this role"
            lines.append(f"{where}: \"{self.role_read}\"")

        for enemy, note, confidence in self.matchups:
            if confidence == "lane":
                lines.append(f"On laning against {enemy}: \"{note}\"")
            else:
                lines.append(f"On {enemy}, who is on the enemy team: "
                             f"\"{note}\"")

        return ("WHAT EXILED HAS TOLD YOU — his words about his own account, "
                "not facts the game gave you. You may repeat or refer to these; "
                "do not extend them into opinions of your own about League.\n"
                + "\n".join(f"  {line}" for line in lines))


class ChampionNotes:
    """Loads data/champions.json and answers questions about one game."""

    def __init__(self, path: Path | None = None):
        self.roles: dict = {}
        self.champions: dict = {}
        if path is not None:
            self.load(path)

    def tags(self, champion: str) -> set[str]:
        """
        His tags for a champion — "melee", "heavy_cc", whatever he writes.

        Used by orchestrator/game_theme.py to do arithmetic on HIS data rather
        than form an opinion about a matchup (STATUS.md §7). An untagged
        champion returns nothing and contributes nothing, which is why an
        unwritten file produces no comp theme instead of a guessed one.
        """
        entry = self.champions.get(key(champion)) or {}
        raw = entry.get("tags") or []
        if isinstance(raw, str):
            raw = [raw]
        return {str(t).lower() for t in raw if t and not is_placeholder(str(t))}

    def load(self, path: Path) -> None:
        if not path.exists():
            print(f"[notes] No {path.name} — role and champion lines disabled")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            # A typo in a hand-edited file must not take the game source down.
            print(f"[notes] Could not read {path.name}: {e}")
            return

        self.roles = {k.lower(): v for k, v in (data.get("roles") or {}).items()}
        self.champions = {key(k): v
                          for k, v in (data.get("champions") or {}).items()}

        held = self._count_placeholders()
        print(f"[notes] Loaded {len(self.roles)} roles, "
              f"{len(self.champions)} champions from {path.name}")
        if held:
            print(f"[notes] {held} entries are still PLACEHOLDER — ignored. "
                  f"Overwrite them in {path.name} to switch these lines on.")

    def _count_placeholders(self) -> int:
        total = 0
        for entry in list(self.roles.values()) + list(self.champions.values()):
            if not isinstance(entry, dict):
                continue
            for value in entry.values():
                if isinstance(value, str) and is_placeholder(value):
                    total += 1
                elif isinstance(value, dict):
                    total += sum(1 for v in value.values()
                                 if isinstance(v, str) and is_placeholder(v))
        return total

    # ---------------------------------------------------------

    def read(self, champion: str, role: str, enemy_champions: list[str],
             enemy_roles: dict[str, str] | None = None) -> ChampionRead:
        """
        Resolve the notes that apply to this game.

        enemy_roles maps champion -> role for the enemy team when it is known.
        It is empty today: enemy role detection needs the quest-item ground
        truth §7 is waiting on.

        A note can still be called a lane matchup without it, by a different
        route. When he files a matchup under a champion whose `main_role` is
        the role he is currently playing, HE has scoped that note to that lane
        — writing "Garen" under Riven-top is his assertion that this is a top
        lane matchup, not hers. §7 permits anything he told her, so the lane
        claim is his to make and safe for her to repeat.

        Failing both, the note still fires as "who is on the enemy team": the
        champion being in the game is measured, the lane assignment is not, and
        she must not assert the half nobody has established.
        """
        out = ChampionRead(champion=champion, role=(role or "").lower())

        role_entry = self.roles.get(out.role) or {}
        out.role_skill = _real(role_entry.get("skill"))
        out.role_read = _real(role_entry.get("read"))

        champ_entry = self.champions.get(key(champion)) or {}
        out.champion_history = _real(champ_entry.get("history"))

        main_role = str(champ_entry.get("main_role", "") or "").lower()
        if main_role and out.role and out.role != main_role:
            out.offrole = True
            out.offrole_read = _real(champ_entry.get("offrole_read"))

        matchups = champ_entry.get("matchups") or {}
        if matchups and enemy_champions:
            by_key = {key(k): (k, v) for k, v in matchups.items()}
            enemy_roles = enemy_roles or {}
            for enemy in enemy_champions:
                found = by_key.get(key(enemy))
                if not found:
                    continue
                _, note = found
                note = _real(note)
                if not note:
                    continue    # a placeholder matchup is no matchup

                # Measured: both roles known and equal.
                enemy_role = (enemy_roles.get(enemy) or "").lower()
                measured = bool(out.role and enemy_role
                                and enemy_role == out.role)

                # Asserted by him: he filed this note under a champion whose
                # main role is the one he is playing right now.
                asserted = bool(out.role and main_role
                                and main_role == out.role)

                out.matchups.append(
                    (enemy, note, "lane" if (measured or asserted) else "team"))

        return out


def _real(value) -> str:
    """The value, or "" if it is a template placeholder or missing."""
    text = str(value or "")
    return "" if is_placeholder(text) else text
