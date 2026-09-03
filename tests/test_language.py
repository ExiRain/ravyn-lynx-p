"""
Which language she answers in, per person.

    python tests/test_language.py

The mechanism was already there — Cyrillic ratio on the message, resolved
before the LLM runs so the TTS can be told too. What it could not do was hold
an opinion about a *person*.

Detection sees one message at a time, and most of chat is too short to judge:
"gg", "+", "ez", "?" and bare emotes all read as English because they are
Latin. A Russian chatter would get Russian for "как дела" and English for the
"+" that followed. So a confident read is remembered per name, and reused only
when the current message cannot be judged at all.

Order matters: detection beats memory. Somebody who switches language
mid-conversation should be followed, not corrected.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                          # noqa: E402
from orchestrator import language                              # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def resolve(text, user="alice", source="chat", memory=None, policy="detect"):
    return language.resolve(
        source=source, text=text, context={"user": user}, explicit=None,
        ambient="en", reply_policy=policy,
        speaker_langs={}, remembered=memory,
    )


def test_detection():
    print("\n--- reading one message ---")
    check("a Russian sentence is Russian", resolve("привет как дела") == "ru")
    check("an English sentence is English", resolve("hey how are you") == "en")
    check("mixed Russian slang still reads Russian",
          resolve("gg ez нуб играй нормально") == "ru")

    # The threshold is deliberately low: it asks "who is this person", not
    # "what language is this string".
    check("a mostly-Latin message with real Cyrillic reads Russian",
          resolve("ez katka пж давай еще") == "ru")

    check("a URL does not decide it",
          resolve("смотри вот тут https://example.com/some-long-english-path") == "ru")
    check("a Latin @mention does not decide it",
          resolve("@SomeLatinName да согласен полностью") == "ru")


def test_short_messages_are_not_judged():
    print("\n--- messages too thin to judge ---")
    # Latin tokens that say nothing about the writer. Emotes are the important
    # case: they are all Latin, there are a lot of them, and a pure length
    # threshold cannot tell KEKW (4) from "hey man" (6).
    for thin in ("gg", "+", "?", "ez", "!!!", "123", "xd",
                 "KEKW", "LULW", "Pog", "monkaS", "OMEGALUL", "gg !!!"):
        check(f"{thin!r} is not confidently judged",
              not language.confident(thin))

    for real in ("hey how are you", "nice play there", "that was rough man"):
        check(f"{real!r} is judged", language.confident(real))

    # Cyrillic is strong evidence on its own — nobody types it by accident.
    for one_word in ("привет", "спасибо", "нуб"):
        check(f"a single Cyrillic word {one_word!r} is enough",
              language.confident(one_word))


def test_language_sticks_per_person():
    print("\n--- a person's language sticks ---")
    memory = language.SpeakerMemory()

    check("her first real sentence sets it",
          resolve("привет как твои дела", user="boris", memory=memory) == "ru")
    check("a bare 'gg' after it stays Russian",
          resolve("gg", user="boris", memory=memory) == "ru")
    check("so does '+'", resolve("+", user="boris", memory=memory) == "ru")
    check("and an emote", resolve("KEKW", user="boris", memory=memory) == "ru")

    # Somebody else is unaffected.
    check("another viewer is judged on their own words",
          resolve("hey how are you", user="alice", memory=memory) == "en")
    check("and boris is still remembered as Russian",
          memory.recall("boris") == "ru", memory.recall("boris"))

    # A real sentence in the other language switches them.
    check("a real English sentence switches him",
          resolve("actually let me switch to english now",
                  user="boris", memory=memory) == "en")
    check("and the memory follows", memory.recall("boris") == "en")

    check("names are case-insensitive",
          memory.recall("BORIS") == memory.recall("boris"))

    # An unknown viewer with a thin message falls back rather than guessing.
    check("an unknown viewer's 'gg' falls back to ambient",
          resolve("gg", user="stranger", memory=memory) == "en")


def test_memory_is_bounded_and_only_confident():
    print("\n--- the speaker memory ---")
    memory = language.SpeakerMemory(limit=4)
    for i in range(6):
        resolve("привет как дела друзья", user=f"v{i}", memory=memory)
    check("it is bounded", len(memory) == 4, str(len(memory)))
    check("the earliest is evicted", memory.recall("v0") == "")
    check("the latest is kept", memory.recall("v5") == "ru")

    # A thin message must never overwrite a real read.
    memory = language.SpeakerMemory()
    resolve("привет как твои дела", user="boris", memory=memory)
    resolve("gg", user="boris", memory=memory)
    check("a thin message does not overwrite a confident read",
          memory.recall("boris") == "ru", memory.recall("boris"))

    memory.clear()
    check("clear empties it", len(memory) == 0)

    check("an invalid language is refused",
          (memory.remember("x", "klingon"), memory.recall("x"))[1] == "")


def test_precedence_is_unchanged():
    print("\n--- precedence ---")
    memory = language.SpeakerMemory()
    memory.remember("boris", "ru")

    check("an explicit signal language wins over everything",
          language.resolve(source="chat", text="привет", context={"user": "boris"},
                           explicit="en", ambient="en", reply_policy="detect",
                           speaker_langs={}, remembered=memory) == "en")

    check("configured SPEAKER_LANG beats detection",
          language.resolve(source="chat", text="hey how are you doing",
                           context={"user": "boris"}, explicit=None,
                           ambient="en", reply_policy="detect",
                           speaker_langs={"boris": "ru"},
                           remembered=memory) == "ru")

    check("her idle voice never follows a chatter",
          resolve("привет как дела", source="game", memory=memory) == "en")
    check("nor does the silence filler",
          resolve("привет как дела", source="silence_filler",
                  memory=memory) == "en")

    check("a forced policy ignores the text",
          resolve("привет как дела", policy="en", memory=memory) == "en")
    check("and so does multilang",
          resolve("hey there", policy="multilang", memory=memory) == "multilang")

    check("resolve works with no memory at all",
          resolve("привет как дела", memory=None) == "ru")


def test_settings_are_wired():
    print("\n--- settings ---")
    check("the reply policy is detect", S.LANG_REPLY == "detect", S.LANG_REPLY)
    check("her idle voice is fixed English", S.LANG_AMBIENT == "en")
    check("the policy is one the resolver knows",
          S.LANG_REPLY in language.REPLY_POLICIES)


def main():
    test_detection()
    test_short_messages_are_not_judged()
    test_language_sticks_per_person()
    test_memory_is_bounded_and_only_confident()
    test_precedence_is_unchanged()
    test_settings_are_wired()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
