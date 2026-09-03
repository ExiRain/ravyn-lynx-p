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

Under the "detect" policy a person's language STICKS. Detection reads one
message, and a Russian chatter's next message is as likely as not to be "gg",
"+", "xd" or a Latin emote — which reads as English and would flip her
mid-conversation. So the first confident read is remembered per name and reused
whenever the current message is too thin to judge. See SpeakerMemory.
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

# Judging a message is ASYMMETRIC, and the asymmetry is the whole point.
#
# Cyrillic is strong evidence: nobody types it by accident, so two Cyrillic
# letters settle the question on their own.
#
# Latin is weak evidence, because Twitch chat is full of Latin tokens that say
# nothing about the writer — "gg", "ez", "+", "xd", and every emote there is:
# KEKW, LULW, Pog, monkaS, OMEGALUL. A length threshold cannot separate those
# from real speech (KEKW is four letters, "hey man" is six), but a WORD count
# can: an emote is one token, a sentence is not. Treating a single Latin token
# as English is what would drag Russian chatters toward English one "KEKW" at
# a time.
MIN_CYRILLIC_LETTERS = 2
MIN_LATIN_LETTERS = 4
MIN_LATIN_WORDS = 2

# How many chatters to remember a language for. Same reasoning as the
# notebook's history cap: a long stream would otherwise grow one entry per name
# forever.
MAX_REMEMBERED_SPEAKERS = 64


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


def letter_count(text: str) -> int:
    """Letters that carry language, after stripping URLs and mentions."""
    if not text:
        return 0
    text = _URL.sub(' ', text)
    text = _MENTION.sub(' ', text)
    return len(_CYRILLIC.findall(text)) + len(_LATIN.findall(text))


def detect_lang(text: str, fallback: str) -> str:
    """Pick a language from the text itself. Falls back when there's nothing to read."""
    if not text or not text.strip():
        return fallback

    ratio = cyrillic_ratio(text)

    if ratio == 0.0 and not _LATIN.search(text):
        # no letters at all — emotes, "!!!", "123"
        return fallback

    return "ru" if ratio >= CYRILLIC_THRESHOLD else "en"


def confident(text: str) -> bool:
    """
    Does this message say anything about who wrote it?

    Any real Cyrillic does. Latin needs to look like a sentence rather than a
    token, because "gg", "ez" and every emote in chat are Latin and none of
    them mean the writer wants English. See the constants above.
    """
    if not text:
        return False

    cleaned = _MENTION.sub(' ', _URL.sub(' ', text))

    if len(_CYRILLIC.findall(cleaned)) >= MIN_CYRILLIC_LETTERS:
        return True

    latin = len(_LATIN.findall(cleaned))
    if latin < MIN_LATIN_LETTERS:
        return False

    # Words that actually contain letters — punctuation and numbers do not
    # make "gg !!!" into a sentence.
    words = [w for w in cleaned.split() if _LATIN.search(w) or _CYRILLIC.search(w)]
    return len(words) >= MIN_LATIN_WORDS


class SpeakerMemory:
    """
    Remembers which language each chatter writes in, for the session.

    Detection sees one message at a time, so without this a Russian chatter
    gets Russian for "как дела" and English for the "+" that follows. In
    memory only, and deliberately: a name means a different person on a
    different day, and `SPEAKER_LANG` in settings is the place for a lasting
    answer.

    Only confident reads are stored, so a thin message never overwrites what a
    real sentence established.
    """

    def __init__(self, limit: int = MAX_REMEMBERED_SPEAKERS):
        self._limit = limit
        self._langs: dict[str, str] = {}

    def remember(self, user: str, lang: str) -> None:
        if not user or lang not in VALID_LANGS:
            return
        key = user.lower()
        if key in self._langs:
            self._langs.pop(key)
        elif len(self._langs) >= self._limit:
            self._langs.pop(next(iter(self._langs)), None)
        self._langs[key] = lang

    def recall(self, user: str) -> str:
        return self._langs.get((user or "").lower(), "")

    def clear(self) -> None:
        self._langs.clear()

    def __len__(self) -> int:
        return len(self._langs)


def resolve(
    source: str,
    text: str,
    context: dict,
    explicit: str | None,
    ambient: str,
    reply_policy: str,
    speaker_langs: dict[str, str] | None = None,
    remembered: "SpeakerMemory | None" = None,
) -> str:
    """
    Decide the language for one signal. Precedence, highest first:

      1. explicit    — the source knew and said so (Signal.lang)
      2. configured  — SPEAKER_LANG, a lasting answer you wrote yourself
      3. ambient     — nobody addressed her, use her fixed idle language
      4. detected    — this message, if it is long enough to judge
      5. remembered  — what this person wrote in last time
      6. reply policy

    4 before 5 on purpose: someone who switches language mid-conversation
    should be followed, not corrected. 5 exists only for the messages that
    cannot be judged at all.

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
        if confident(text):
            found = detect_lang(text, fallback=ambient)
            if remembered is not None:
                remembered.remember(user, found)
            return found

        # Too thin to judge — "gg", "+", an emote. Fall back on what this
        # person has written before rather than defaulting them to English.
        if remembered is not None:
            recalled = remembered.recall(user)
            if recalled in VALID_LANGS:
                return recalled

        return detect_lang(text, fallback=ambient)

    if reply_policy in VALID_LANGS:
        return reply_policy

    return ambient if ambient in VALID_LANGS else "en"
