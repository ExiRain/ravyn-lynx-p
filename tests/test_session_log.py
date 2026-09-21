"""
The session record and the numbers drawn from it.

    python tests/test_session_log.py

Two things are being protected here.

The log must never be able to silence her. Every call site is on the hot path
— the dispatch loop and the response thread — so the disabled case, the
uninitialised case and the malformed-record case all have to come back quietly
rather than raise into a consumer callback.

And the repetition numbers have to mean something. The sample below is real:
four death reactions from one live session, which a listener hears as the same
line four times and a `sentence[:50]` scrollback shows as four different ones.
If the analyser ever stops calling those a repeat, it has stopped being worth
running.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.models import Signal                             # noqa: E402
from orchestrator import session_log                               # noqa: E402
from tools import analyze_session, console_import                  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# Real scrollback, trimmed. Four deaths, one repeated voice answer, one line
# dropped at the gate.
SAMPLE = """
[hear] 1.2s audio, 1.9s transcribe [en]: Ravyn.
[dispatch] source=voice  mode=improv  lang=en  skip_llm=False  text=Ravyn....
[20:35:19][response] Speaking 3 sentence(s), mood=0.1 tired=0.2 lang=en
[response]   [1/3] gen 1.21s, audio 2.56s: You're treating me like a menu item again?
[response]   [2/3] gen 2.76s, audio 6.08s: I'm right here talking to you, Exiled, not some ic
[lol] Death #4 (traded 0k/0a) -> roast @ 90%
[lol] MyDeath: Limit test mode is active, I see. Killed by Riven.  [my_death_pattern]
[dispatch] source=game  mode=improv  lang=en  skip_llm=False  text=Limit test mode is active, I see. Killed by Riven. He got no...
[20:37:58][response] Speaking 3 sentence(s), mood=0.1 tired=0.3 lang=en
[response]   [1/3] gen 1.68s, audio 3.84s: Limit test mode doesn't mean you get to run up and
[response]   [2/3] gen 0.49s, audio 0.96s: Exiled...
[response]   [3/3] gen 2.73s, audio 6.32s: you keep making the same mistake of walking straig
[lol] Death #10 (traded 0k/1a) -> sharp @ 100%
[lol] MyDeath: I guess we're limit testing. Killed by Kayn.  [theme_top_comfort]
[dispatch] source=game  mode=improv  lang=en  skip_llm=False  text=I guess we're limit testing. Killed by Kayn. He had 1 assist...
[20:45:49][response] Speaking 4 sentence(s), mood=-0.6 tired=0.2 lang=en
[response]   [1/4] gen 1.69s, audio 3.60s: Limit testing doesn't mean you get to run up and d
[response]   [2/4] gen 0.77s, audio 1.36s: Exiled...
[response]   [3/4] gen 3.01s, audio 6.64s: you keep making the same mistake of walking straig
[response]   [4/4] gen 2.56s, audio 5.68s: Games are won by staying alive, and right now you
[hear] 1.1s audio, 1.7s transcribe [en]: Ravyn. League of Legends.
[dispatch] source=voice  mode=improv  lang=en  skip_llm=False  text=Ravyn. League of Legends....
[20:46:28][response] Speaking 3 sentence(s), mood=0.1 tired=0.2 lang=en
[response]   [1/3] gen 1.16s, audio 2.48s: You're treating me like a menu item again?
[response]   [2/3] gen 3.03s, audio 6.64s: I'm right here talking to you, Exiled, not some ic
[lol] AllyDeath: Exiled's teammate Smolder died to Riven. Sigh.  [ally_death_while_behind]
[dispatch] source=game  mode=improv  lang=en  skip_llm=False  text=Exiled's teammate Smolder died to Riven. Sigh....
[20:55:24][response] Speaking 3 sentence(s), mood=-0.3 tired=0.6 lang=en
[response] Dropped — you are still talking after 8s: Anivia can't do much against that Riven anyway,
[lol] Death #14 (traded 0k/1a) -> sharp @ 100%
[lol] MyDeath: I guess we're limit testing. Killed by Kayn.  [my_death_traded]
[dispatch] source=game  mode=improv  lang=en  skip_llm=False  text=I guess we're limit testing. Killed by Kayn. He had 1 assist...
[20:55:45][response] Speaking 4 sentence(s), mood=-0.3 tired=0.8 lang=en
[response]   [1/4] gen 1.75s, audio 3.84s: Limit testing doesn't mean you get to run up and d
[response]   [2/4] gen 0.73s, audio 1.44s: Exiled...
[response]   [3/4] gen 3.20s, audio 7.12s: you keep making the same mistake of walking straig
[response]   [4/4] gen 2.64s, audio 5.92s: Games are won by staying alive, and right now you
"""


def game_signal(text: str, **ctx) -> Signal:
    base = {"event_type": "MyDeath", "config_key": "MyDeath",
            "angle_id": "my_death_plain", "tone": "roast", "death_count": 4}
    base.update(ctx)
    return Signal(source="game", priority=3, text=text, lang="en", context=base)


# ================================================================= the record
def test_writes_one_record_per_line():
    print("\n--- one record per dispatched signal ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        log = session_log.init(tmp, enabled=True)

        log.dispatched(game_signal("You died. Killed by Riven."))
        log.responded("Games are won by staying alive.", mood=-0.6, tired=0.2,
                      lang="en")
        log.spoke_sentence("Games are won by staying alive.", gen_s=1.2,
                           audio_s=3.4)
        log.finished("spoken")

        records = [json.loads(x) for x in
                   log.path.read_text(encoding="utf-8").splitlines() if x]
        lines = [r for r in records if r.get("kind") == "line"]

        check("session_start is written first",
              records[0].get("kind") == "session_start")
        check("one line record", len(lines) == 1, str(len(lines)))

        rec = lines[0]
        check("her full text is kept",
              rec.get("said") == "Games are won by staying alive.")
        check("outcome recorded", rec.get("outcome") == "spoken")
        check("the trigger is kept",
              rec.get("trigger_text") == "You died. Killed by Riven.")
        check("the knobs are kept",
              (rec.get("angle_id"), rec.get("tone"), rec.get("config_key"))
              == ("my_death_plain", "roast", "MyDeath"))
        check("death count is kept", rec.get("death_count") == 4)
        check("audio time is summed", rec.get("audio_s") == 3.4)
        check("spoken text is reassembled",
              rec.get("spoken_text") == "Games are won by staying alive.")
        check("mood and tired travel", rec.get("mood") == -0.6
              and rec.get("tired") == 0.2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_outcomes():
    print("\n--- every fate is recorded, including the silent ones ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        log = session_log.init(tmp, enabled=True)

        log.dispatched(game_signal("one"))
        log.responded("dropped line")
        log.finished("dropped_gate")

        log.dispatched(game_signal("two"))
        log.responded("")
        log.finished("empty")

        # никто не ответил — the notebook died mid-request
        log.dispatched(game_signal("three"))
        log.dispatched(game_signal("four"))
        log.responded("fourth")
        log.finished("spoken")

        lines = [json.loads(x) for x in
                 log.path.read_text(encoding="utf-8").splitlines()
                 if x and json.loads(x).get("kind") == "line"]
        outcomes = [r["outcome"] for r in lines]

        check("dropped line is in the log", outcomes[0] == "dropped_gate")
        check("her dropped words are kept too",
              lines[0].get("said") == "dropped line")
        check("empty reply is recorded", outcomes[1] == "empty")
        check("a request with no reply is marked lost",
              outcomes[2] == "lost", str(outcomes))
        check("the next line is unaffected", outcomes[3] == "spoken")
        check("sequence numbers are contiguous",
              [r["seq"] for r in lines] == [1, 2, 3, 4])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_never_raises():
    print("\n--- a logging bug must not be able to mute her ---")
    log = session_log.SessionLog("", enabled=False)
    log.dispatched(game_signal("x"))
    log.responded("y")
    log.spoke_sentence("z")
    log.finished("spoken")
    check("a disabled log does nothing, quietly", log.path is None)

    session_log._LOG = None
    fresh = session_log.get()
    check("get() before init returns a disabled log", not fresh.enabled)
    fresh.responded("orphan")           # must not raise

    tmp = Path(tempfile.mkdtemp())
    try:
        live = session_log.init(tmp, enabled=True)
        live.responded("an answer to a request we never saw")
        live.finished("spoken")
        lines = [json.loads(x) for x in
                 live.path.read_text(encoding="utf-8").splitlines()
                 if x and json.loads(x).get("kind") == "line"]
        check("an orphan response is still recorded",
              len(lines) == 1 and lines[0].get("orphan") is True)

        broken = Signal(source="game", priority=3, text="t")
        broken.context = None           # a source that set it wrong
        live.dispatched(broken)
        live.finished("spoken")
        check("a malformed signal does not raise", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def last_line(log) -> dict:
    lines = [json.loads(x) for x in
             log.path.read_text(encoding="utf-8").splitlines()
             if x and json.loads(x).get("kind") == "line"]
    return lines[-1]


def test_full_context_is_opt_in():
    print("\n--- the situation block is opt-in ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        sig = game_signal("died", situation="Minute 14. He is 0/9.",
                          angle="Talk about the drake count.")

        log = session_log.init(tmp, enabled=True)
        log.dispatched(sig)
        log.finished("spoken")
        check("off by default", "context" not in last_line(log))

        log = session_log.init(tmp, enabled=True, full_context=True)
        log.dispatched(sig)
        log.finished("spoken")
        check("on when asked, with the situation verbatim",
              last_line(log).get("context", {}).get("situation")
              == "Minute 14. He is 0/9.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ========================================================== console scrollback
def test_console_import():
    print("\n--- rebuilding a session from scrollback ---")
    records = console_import.parse(SAMPLE)

    check("every dispatch became a record", len(records) == 6, str(len(records)))

    by_seq = {r["seq"]: r for r in records}
    death = by_seq[2]
    check("the pool key is recovered", death.get("config_key") == "MyDeath")
    check("the angle is recovered",
          death.get("angle_id") == "my_death_pattern")
    check("the death count is recovered", death.get("death_count") == 4)
    check("the verdict tone is recovered", death.get("verdict_tone") == "roast")
    check("mood is recovered", death.get("mood") == 0.1)
    check("her sentences are joined",
          death["spoken_text"].startswith("Limit test mode doesn't mean"))
    check("truncation is flagged", death.get("truncated") is True)

    dropped = [r for r in records if r.get("outcome") == "dropped_gate"]
    check("the dropped line is kept, with its text",
          len(dropped) == 1 and "Anivia" in dropped[0]["spoken_text"],
          str(dropped))

    voice = [r for r in records if r["source"] == "voice"]
    check("voice lines are separated from game lines", len(voice) == 2)
    check("the trigger text survives",
          voice[0]["trigger_text"] == "Ravyn." and voice[0]["trigger_truncated"])

    ally = by_seq[5]
    check("an ally angle is recovered",
          ally.get("angle_id") == "ally_death_while_behind")
    check("a death verdict does not leak onto the next event",
          "death_count" not in ally)


# ==================================================================== analysis
def test_finds_the_repeats():
    print("\n--- the numbers that say she repeated herself ---")
    records = console_import.parse(SAMPLE)
    report = analyze_session.analyse(records, analyze_session.DEFAULT_SIMILARITY)

    sizes = sorted((c["size"] for c in report["clusters"]), reverse=True)
    check("the three limit-testing deaths cluster together",
          sizes and sizes[0] >= 3, str(sizes))
    check("the repeated voice answer is caught too",
          len([c for c in report["clusters"] if c["size"] == 2]) >= 1)
    check("repeat rate is reported", report["repeat_rate"] > 0.3,
          f"{report['repeat_rate']:.2f}")

    phrases = {p[0] for p in report["phrases"]}
    check("the catchphrase is named",
          any("games are won by" in p for p in phrases), str(sorted(phrases)[:5]))
    check("so is the recycled scolding",
          any("you keep making the same mistake" in p for p in phrases))

    check("repeats are attributed to the pool that produced them",
          report["by_knob"]["config_key"].get("MyDeath", 0) >= 2,
          str(report["by_knob"]["config_key"]))
    check("and to a source", report["by_knob"]["source"].get("voice", 0) == 1)

    check("heat is counted", report["hot_lines"] >= 3)
    check("lines aimed at him are counted", report["at_him"] >= 3)
    check("standing grievances are named",
          report["grievances"].get("games are won", 0) >= 2)
    check("truncation is carried into the report",
          report["truncated"] is True)


def test_similarity_is_not_a_hair_trigger():
    print("\n--- similar means similar ---")
    w = analyze_session.words
    same = analyze_session.similarity(
        w("Games are won by staying alive, and right now you are losing."),
        w("Games are won by not dying, and so far you're losing."))
    different = analyze_session.similarity(
        w("Briar finally got lucky enough to tag one of theirs."),
        w("Kayn took Baron while you were looking at the wrong lane."))
    identical = analyze_session.similarity(w("Moving on."), w("Moving on."))

    check("a rephrasing of the same line scores high",
          same >= analyze_session.DEFAULT_SIMILARITY, f"{same:.2f}")
    check("two unrelated lines do not", different < 0.4, f"{different:.2f}")
    check("identical text is 1.0", identical == 1.0)

    opening = analyze_session.similarity(
        w("Briar finally got lucky enough to tag one of theirs, I guess."),
        w("Briar finally got lucky enough to tag one of theirs, though "
          "honestly that was a solid play from the hardstucks."))
    check("the same opening with a different tail is still a repeat",
          opening >= analyze_session.DEFAULT_SIMILARITY, f"{opening:.2f}")


def test_reads_its_own_log():
    print("\n--- the analyser reads what the logger writes ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        log = session_log.init(tmp, enabled=True)
        for i in range(3):
            log.dispatched(game_signal(f"death {i}"))
            log.responded("Games are won by staying alive, and you are not.")
            log.spoke_sentence("Games are won by staying alive, and you are not.",
                               audio_s=3.0)
            log.finished("spoken")

        records, kind = analyze_session.load(log.path)
        check("the JSONL loads", len(records) == 3, str(len(records)))
        check("it is recognised as a session log", kind == "session log")

        report = analyze_session.analyse(records,
                                         analyze_session.DEFAULT_SIMILARITY)
        check("three identical lines are one cluster of three",
              [c["size"] for c in report["clusters"]] == [3])
        check("nothing is marked truncated", not report["truncated"])
        check("outcomes are counted", report["outcomes"]["spoken"] == 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_writes_one_record_per_line()
    test_outcomes()
    test_never_raises()
    test_full_context_is_opt_in()
    test_console_import()
    test_finds_the_repeats()
    test_similarity_is_not_a_hair_trigger()
    test_reads_its_own_log()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
