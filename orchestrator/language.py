"""
Language resolution — decides what language Ravyn answers in, per signal.

There is one rule, and it splits on whether anyone actually spoke to her:

  ambient   — silence filler, game reactions, promos. Nobody addressed her,
              so there is no language to mirror. These always use a fixed
              language (LANG_AMBIENT). This is what keeps her coherent:
              her own idle voice never flips language mid-stream.

  addressed — chat, voice, Discord. Someone spoke to her, so her reply
              follows them, per the LANG_REPLY policy.

Resolution runs in the dispatcher, once, immediately before publishing, so
no signal source can forget to set it.
"""

from __future__ import annotations

import re

# Sources with no addresser — she is commenting on the world, not replying.
AMBIENT_SOURCES = {"silence_filler", "promotion", "game"}

# Values the notebook understands. See ravyn-nb/persona/context_builder.py:
#   "ru"        -> forced Russian
#   "multilang" -> "respond in the same language the user writes in"
#   anything else (i.e. "en") -> no instruction, she speaks English
VALID_LANGS = {"en", "ru", "multilang"}

# Policies for LANG_REPLY
REPLY_POLICIES = {"en", "ru", "multilang", "detect"}

_CYRILLIC = re.compile(r'[Ѐ-ӿ]')
_LATIN = re.compile(r'[A-Za-z]')
_URL = re.compile(r'https?://\S+|www\.\S+')
_MENTION = re.compile(r'@\w+')

# How much Cyrillic makes a person a Russian speaker.
#
# Deliberately low. This is not "what language is this message" — it is "who
# is this person". Russian chatters mix Latin gaming slang in constantly
# ("gg ez нуб", "ez katka пж"), and Twitch emotes are Latin words, both of
# which drag the ratio down. A message that is a third Cyrillic came from
# someone who would rather be answered in Russian.
CYRILLIC_THRESHOLD = 0.3


def is_ambient(source: str) -> bool:
    return source in AMBIENT_SOURCES


def cyrillic_ratio(text: str) -> float:
    """
    Share of letters that are Cyrillic, 0.0-1.0.

    URLs and @mentions are stripped: a Russian speaker linking an English
    site, or a Latin-named user being pinged, says nothing about the
    language they want back. Returns 0.0 for text with no letters at all
    (pure emotes, punctuation, numbers).
    """
    if not text:
        return 0.0

    text = _URL.sub(' ', text)
    text = _MENTION.sub(' ', text)

    cyr = len(_CYRILLIC.findall(text))
    lat = len(_LATIN.findall(text))
    total = cyr + lat

    if total == 0:
        return 0.0

    return cyr / total


def detect_lang(text: str, fallback: str) -> str:
    """Pick a language from the text itself. Falls back when there's nothing to read."""
    if not text or not text.strip():
        return fallback

    ratio = cyrillic_ratio(text)

    if ratio == 0.0 and not _LATIN.search(text):
        # no letters at all — emotes, "!!!", "123"
        return fallback

    return "ru" if ratio >= CYRILLIC_THRESHOLD else "en"


def resolve(
    source: str,
    text: str,
    context: dict,
    explicit: str | None,
    ambient: str,
    reply_policy: str,
    speaker_langs: dict[str, str] | None = None,
) -> str:
    """
    Decide the language for one signal. Precedence, highest first:

      1. explicit    — the source knew and said so (Signal.lang)
      2. speaker     — a known person, e.g. a Russian Discord duo partner
      3. ambient     — nobody addressed her, use her fixed idle language
      4. reply policy

    Always returns a value the notebook understands.
    """
    if explicit in VALID_LANGS:
        return explicit

    user = (context or {}).get("user", "")
    if user and speaker_langs:
        known = speaker_langs.get(user.lower())
        if known in VALID_LANGS:
            return known

    if is_ambient(source):
        return ambient if ambient in VALID_LANGS else "en"

    if reply_policy == "detect":
        return detect_lang(text, fallback=ambient)

    if reply_policy in VALID_LANGS:
        return reply_policy

    return ambient if ambient in VALID_LANGS else "en"
