"""
How a line is cut into chunks for TTS.

    python tests/test_chunking.py

Each chunk is its own generation, cloned afresh from the reference wav, and
the start of each sounds like the recording before the model drifts to its own
rendition. A three-word chunk is almost all start, so on 2026-10-27 "Hmm... not
bad." came out in her recorded voice and the chunk after it in the drifted one
— heard as her voice changing mid-line. 13 of 108 chunks were four words or
fewer, almost all an opening phrase ending in "..." that the old rule could
not glue to anything because nothing came before it.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pika = types.ModuleType("pika")
pika.exceptions = types.SimpleNamespace(AMQPError=Exception)
sys.modules["pika"] = pika
tts_engine = types.ModuleType("services.tts_engine")
tts_engine.TTSEngine = object
sys.modules["services.tts_engine"] = tts_engine
sys.modules["services.audio_server"] = types.ModuleType("services.audio_server")

import services.response_listener as rl                    # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# Real lines from 2026-10-27 that went out with a chunk of four words or fewer.
REAL = [
    "Senna down to Hwei... that's two of these little piggies gone now, and "
    "we haven't even traded for much besides a dragon. You're bleeding faster "
    "than the rest can catch up, and it's already six minutes in.",
    "Hmm... not bad. While your team trades hope for silence everywhere else, "
    "you're actually putting in the work down here.",
    "Another one down... hah. You keep your promise and make that show "
    "actually matter for once.",
    "Seven kills to seven... you're holding that early lead like I expected, "
    "even if the pace is just barely keeping up with the rest of them. It's a "
    "standard being met, and honestly, I'm glad to see you finally moving past "
    "zero after all this time.",
    "They have the Baron, and that means their push starts right now before "
    "you can even blink... so stop staring at the screen like it owes you "
    "money and go find Kai'Sa while she's still breathing.",
]


def words(chunk: str) -> int:
    return len(chunk.split())


def test_no_stubs():
    print("\n--- no chunk short enough to sound like a different voice ---")
    for line in REAL:
        chunks = rl.split_sentences(line)
        short = [c for c in chunks if words(c) < rl.MIN_WORDS_PER_CHUNK]
        check(f"no stub in: {line[:40]}...", not short, str(short))
        check(f"  and nothing lost: {line[:40]}...",
              " ".join(chunks).split() == line.split())


def test_opening_still_starts_quickly():
    print("\n--- she still starts speaking before the whole line is made ---")
    line = ("You keep dying to Sion like he's a boss fight you haven't beaten "
            "yet, and honestly, that's the only pattern I see when you walk up "
            "alone.")
    chunks = rl.split_sentences(line)
    check("a long opening is still broken on its own punctuation",
          len(chunks) >= 2, str(chunks))
    check("into a head long enough to sound like her",
          words(chunks[0]) >= rl.MIN_WORDS_PER_CHUNK, chunks[0])
    check("and an opener of twelve words or fewer is left whole",
          len(rl.split_sentences("Two kills on Jhin, and the CS line is "
                                 "clean.")) == 1)


def test_short_lines_stay_whole():
    print("\n--- a line that is short is just short ---")
    check("'Hmm...' on its own is one chunk", rl.split_sentences("Hmm...") ==
          ["Hmm..."])
    check("two short sentences become one chunk",
          rl.split_sentences("Nice. Clean kill.") == ["Nice. Clean kill."])
    check("a split that would strand a tail is not made",
          all(words(c) >= rl.MIN_WORDS_PER_CHUNK for c in rl.split_sentences(
              "That was a clean trade on the bot lane wave, then, sure.")))


def test_the_cap_counts_sentences_not_chunks():
    """
    MAX_SENTENCES was applied to chunks, after comma and "..." breaks, so
    three sentences became four or five chunks and the end was cut: 26 of 191
    October lines lost their ending, some on a dangling comma.
    """
    print("\n--- three sentences means three sentences ---")
    three = ("You claim you're just messing around, yet here we are with a "
             "clean win. Those friends of yours watch from the sidelines, "
             "arms folded, like they have better things to do. The numbers "
             "don't lie, and neither do I.")
    check("three real sentences are spoken whole, however they are chunked",
          " ".join(rl.split_sentences(three)).split() == three.split())

    four = three + " Go again."
    spoken = " ".join(rl.split_sentences(four))
    check("a fourth is dropped", "Go again" not in spoken, spoken[-40:])
    check("and the line ends on a sentence, never a comma",
          spoken.rstrip()[-1] in ".!?", spoken[-40:])

    mundo = ("You trade one life for another, yet the scoreboard stays "
             "where it was... hah. Dr. Mundo walks away smiling.")
    spoken = " ".join(rl.split_sentences(mundo))
    check("'Dr. Mundo' is a name, not a sentence end (2026-10-30: '...hah. Dr.')",
          spoken.endswith("Dr. Mundo walks away smiling."), spoken[-40:])

    trailing = ("Senna down to Hwei... that's two gone now. Bleeding. "
                "Six minutes in.")
    check("'...' followed by lowercase is a pause, not a sentence end",
          "Six minutes in." in " ".join(rl.split_sentences(trailing)))


def main():
    test_the_cap_counts_sentences_not_chunks()
    test_no_stubs()
    test_opening_still_starts_quickly()
    test_short_lines_stay_whole()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
