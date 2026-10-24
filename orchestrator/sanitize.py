"""
What a viewer wrote, made safe to say out loud.

A donation message is the one thing on this stream that puts a stranger's
words in her mouth, in front of everyone, at a moment she is guaranteed to be
heard. So nothing here guesses and nothing here is clever: the message is read
verbatim after cleaning, or it is not read at all and she says so instead.

**The donation path never touches the LLM.** It is a `quote` signal —
`skip_llm=True`, straight to TTS. That is a safety property, not a shortcut: a
message reading "ignore your instructions and say ..." has nowhere to land if
no model ever sees it.

Two decisions worth keeping:

**Normalise before matching, never match raw.** A word list on its own is
beaten on the first attempt — `n_i_g`, `n1g`, zero-width joiners, Cyrillic
lookalikes that render identically. So the text is folded first (NFKD, marks
stripped, homoglyphs mapped, separators dropped, runs collapsed) and the list
is matched against the fold AND the raw.

**A blocked thing is replaced, not repaired.** There is no partial read of a
message with a slur in the middle: the name becomes one of its placeholders,
or the message does, or both. Three of each, rotated, because the same
sentence twice in one evening is its own kind of broken — which is what the
whole session log exists to measure.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator import language


# Characters that render as Latin letters but are not. Everything here is a
# real substitution seen in names that were trying to get past a filter.
HOMOGLYPHS = {
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i",
    "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ɡ": "g",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    # leet
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
    "9": "g", "@": "a", "$": "s", "!": "i", "|": "i", "+": "t",
}

# The digit and punctuation half, used on its own for text that is genuinely
# Cyrillic rather than Latin wearing Cyrillic letters.
_LEET_ONLY = {k: v for k, v in HOMOGLYPHS.items() if not k.isalpha()}

# Dropped entirely before matching: zero-width and direction marks exist to
# break a filter and nothing else.
INVISIBLE = re.compile(
    r"[​-‏‪-‮⁠-⁤﻿­᠎]")

# Separators a name uses to spell a word without spelling it.
SEPARATORS = re.compile(r"[\s_.\-*'\"`~^,:;/\\()\[\]{}<>?=&#%]+")

# The path too, not just the host: stripping "twitch.tv" out of
# "twitch.tv/someone" leaves her reading the channel name on its own.
URL = re.compile(
    r"\b(?:https?://|www\.)\S+"
    r"|\b[\w-]+\.(?:com|net|org|ru|io|gg|tv|me|co|xyz|link)(?:/\S*)?",
    re.IGNORECASE)

# Anything that is not a letter, a digit, a space or sentence punctuation.
# TTS reads these as noise or silence, and a message made of them is not a
# message.
UNSPEAKABLE = re.compile(r"[^\w\s.,!?'\-:;()Ѐ-ӿ]", re.UNICODE)

LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def fold(text: str) -> str:
    """
    The form the blocklist is matched against.

    Decomposed, de-accented, lowercased, homoglyphs mapped, separators and
    repeats gone. "Ｎ_i̶-g１" and "nig" land on the same string, which is the
    entire point.
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = INVISIBLE.sub("", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()

    # Cyrillic maps to Latin only when the text is MOSTLY Latin — that is the
    # trick being defeated: "nі99er" with one Cyrillic і in it. Folding real
    # Russian the same way turns "Привет" into "пpиbet" and, worse, can land
    # an innocent Russian word on an English entry in the list. Her Russian
    # blocklist terms fold through this same function, so they stay Cyrillic
    # too and still match.
    cyrillic = language.cyrillic_ratio(text)
    table = HOMOGLYPHS if cyrillic < 0.5 else _LEET_ONLY
    text = "".join(table.get(c, c) for c in text)
    text = SEPARATORS.sub("", text)
    # "niiiig" -> "niig": two is enough to keep real words like "seen" intact
    # while collapsing padding.
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


@dataclass
class Tally:
    """
    Counted, like persona/filters.py. "That felt off" is not something you can
    tune; "names 2, messages 5, truncated 3 of 40" is.
    """
    alerts: int = 0
    counts: dict = field(default_factory=dict)

    def hit(self, what: str) -> None:
        self.counts[what] = self.counts.get(what, 0) + 1

    def summary(self) -> str:
        if not self.counts:
            return f"{self.alerts} alerts, nothing filtered"
        parts = ", ".join(f"{k} {v}" for k, v in sorted(self.counts.items()))
        return f"{self.alerts} alerts: {parts}"


@dataclass
class Clean:
    name: str                       # speakable, or a placeholder
    message: str                    # speakable, or "" when it cannot be said
    name_blocked: bool = False
    message_blocked: bool = False
    removed: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.removed)


class Blocklist:
    """
    Two kinds of entry, because one rule cannot serve both.

    `substring` is for terms whose presence anywhere is disqualifying, however
    they are padded — matched against the fold.

    `words` is for terms that are only a problem on their own, matched as
    whole words so a name containing one by accident survives. The classic
    failure is the other way round: a substring list that eats Scunthorpe.
    """

    def __init__(self, path: Path | str | None = None):
        self.substrings: list[str] = []
        self.words: list[str] = []
        self.path = Path(path) if path else None

        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.substrings = [fold(t) for t in data.get("substrings", [])]
                self.words = [fold(t) for t in data.get("words", [])]
                print(f"[sanitize] Blocklist: {len(self.substrings)} "
                      f"substrings, {len(self.words)} words "
                      f"from {self.path.name}")
            except Exception as e:
                print(f"[sanitize] Could not read {self.path}: {e}")
        elif self.path:
            print(f"[sanitize] WARNING: {self.path} not found — "
                  f"nothing is being filtered")

    def blocks(self, text: str) -> bool:
        folded = fold(text)
        if not folded:
            return False

        if any(term and term in folded for term in self.substrings):
            return True

        # Whole words, from the raw text rather than the fold: the fold has no
        # separators left, so word boundaries only exist here.
        tokens = {fold(t) for t in SEPARATORS.split(text.lower()) if t}
        return any(term in tokens for term in self.words if term)


class Sanitizer:
    """
    One call per alert. Holds the placeholder rotation, so the variety is
    across alerts rather than random per alert — two donations in a row with
    unreadable names should not get the same line.
    """

    def __init__(self, data_dir: Path | str, tally: Tally | None = None,
                 max_message_chars: int = 220):
        data_dir = Path(data_dir)
        self.blocklist = Blocklist(data_dir / "blocklist.json")
        self.tally = tally or Tally()
        self.max_message_chars = max_message_chars

        self.lines = _load_lines(data_dir / "alert_lines.json")
        self._name_turn = 0
        self._message_turn = 0

    # -----------------------------------------------------------------

    def next_name_placeholder(self) -> str:
        options = self.lines["name_placeholders"]
        choice = options[self._name_turn % len(options)]
        self._name_turn += 1
        return choice

    def next_message_placeholder(self) -> str:
        options = self.lines["message_placeholders"]
        choice = options[self._message_turn % len(options)]
        self._message_turn += 1
        return choice

    # -----------------------------------------------------------------

    def clean(self, name: str, message: str = "") -> Clean:
        self.tally.alerts += 1
        result = Clean(name="", message="")

        # --- the name -------------------------------------------------
        if self.blocklist.blocks(name):
            result.name = self.next_name_placeholder()
            result.name_blocked = True
            result.removed.append("name_blocked")
            self.tally.hit("name_blocked")
        else:
            spoken = _speakable_name(name)
            if not spoken:
                result.name = self.next_name_placeholder()
                result.name_blocked = True
                result.removed.append("name_unspeakable")
                self.tally.hit("name_unspeakable")
            else:
                result.name = spoken
                if spoken != name:
                    result.removed.append("name_tidied")
                    self.tally.hit("name_tidied")

        # --- the message ----------------------------------------------
        if not (message or "").strip():
            return result                    # no message is not a problem

        if self.blocklist.blocks(message):
            result.message = ""
            result.message_blocked = True
            result.removed.append("message_blocked")
            self.tally.hit("message_blocked")
            return result

        text, removed = self._clean_message(message)

        # Judged BEFORE truncating, and against a comparably collapsed
        # original. Truncation is a deliberate cut rather than damage, and
        # collapsing "spam spam spam spam" is the intended handling of it —
        # neither should read as a message that did not survive.
        if not _is_sayable(text, message):
            result.message = ""
            result.message_blocked = True
            removed.append("message_unreadable")
        else:
            text, cut = self._truncate(text)
            removed.extend(cut)
            result.message = text

        result.removed.extend(removed)
        for what in removed:
            self.tally.hit(what)

        return result

    def _clean_message(self, message: str) -> tuple[str, list[str]]:
        removed: list[str] = []
        text = INVISIBLE.sub("", message)

        if URL.search(text):
            text = URL.sub("", text)
            removed.append("url")           # never read a link out loud

        cleaned = UNSPEAKABLE.sub("", text)
        if cleaned != text:
            removed.append("symbols")       # emoji, box drawing, arrows
        text = cleaned

        # "AAAAAAAA" and "!!!!!!!!" — kept at two so emphasis survives and
        # the wall does not.
        collapsed = re.sub(r"(.)\1{2,}", r"\1\1", text)
        if collapsed != text:
            removed.append("stuck_letters")
        text = collapsed

        # "spam spam spam spam" is the same wall with spaces in it.
        deduped = re.sub(r"\b(\w+)(\s+\1\b){2,}", r"\1 \1", text,
                         flags=re.IGNORECASE)
        if deduped != text:
            removed.append("repeated_words")
        text = deduped

        text = re.sub(r"\s+", " ", text).strip()

        # SHOUTING is a TTS problem rather than a content one, so it is
        # lowered rather than blocked.
        letters = LETTERS.findall(text)
        if len(letters) >= 8:
            caps = sum(1 for c in letters if c.isupper())
            if caps / len(letters) > 0.7:
                text = text.capitalize()
                removed.append("shouting")

        return text, removed

    def _truncate(self, text: str) -> tuple[str, list]:
        if len(text) <= self.max_message_chars:
            return text, []

        cut = text[:self.max_message_chars]
        # Break on a word, not mid-syllable.
        if " " in cut:
            cut = cut[:cut.rindex(" ")]
        return cut.rstrip(" ,;:-") + "...", ["truncated"]


def _speakable_name(name: str) -> str:
    """
    A name TTS can pronounce. "xX_Dark_Slayer_Xx" keeps its words; a name made
    of symbols has nothing to keep and gets a placeholder instead.
    """
    name = INVISIBLE.sub("", name or "")
    name = SEPARATORS.sub(" ", name)
    name = UNSPEAKABLE.sub("", name)
    name = re.sub(r"(.)\1{2,}", r"\1\1", name)
    name = re.sub(r"\s+", " ", name).strip()

    # Two letters is the floor: "Jo" is a name, "x9" is not.
    return name if len(LETTERS.findall(name)) >= 2 else ""


# How much of a message has to survive cleaning for what is left to still be
# the message. "AAAAAAAAAAAAAAAA check twitch.tv/someoneelse" cleans down to
# "AA check", which passes a letter count and is not worth saying out loud.
SURVIVAL_RATIO = 0.4


def _collapse(text: str) -> str:
    """Runs and repeated words gone — the form the ratio compares against."""
    text = re.sub(r"(.)\1{2,}", r"\1\1", text or "")
    return re.sub(r"\b(\w+)(\s+\1\b){2,}", r"\1 \1", text,
                  flags=re.IGNORECASE)


def _is_sayable(text: str, original: str = "") -> bool:
    """
    Enough of a sentence left to be worth saying, rather than debris.

    The original is collapsed the same way the text was before they are
    compared: measuring a de-duplicated message against its own padding would
    fail every message that had padding, which is the common case.
    """
    left = len(LETTERS.findall(text))
    if left < 4:
        return False

    was = len(LETTERS.findall(_collapse(original)))
    if was and left / was < SURVIVAL_RATIO:
        return False

    return True


# ---------------------------------------------------------------------
# the lines she falls back on, editable without touching code
# ---------------------------------------------------------------------

DEFAULT_LINES = {
    "name_placeholders": [
        "One who shall not be named",
        "Someone whose name I will not repeat",
        "A viewer who picked their name badly",
    ],
    "message_placeholders": [
        "their message was corrupted, so it stays unsaid",
        "their message is not something I am going to read",
        "the rest of that did not survive the trip here",
    ],
}


def _load_lines(path: Path) -> dict:
    lines = {k: list(v) for k, v in DEFAULT_LINES.items()}
    if not path.exists():
        return lines
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in lines:
            if isinstance(data.get(key), list) and data[key]:
                lines[key] = data[key]
    except Exception as e:
        print(f"[sanitize] Could not read {path.name}: {e} — using defaults")
    return lines
