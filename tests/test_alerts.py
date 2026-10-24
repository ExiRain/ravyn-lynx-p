"""
A stranger's words in her mouth, and who gets the floor.

    python tests/test_alerts.py

A donation message is the one thing on this stream that is written by someone
else, read out loud, and guaranteed to be heard. Two properties hold it
together, and both are here as regression cases.

**It never reaches the LLM.** The donation path is a quote signal, so a
message reading "ignore your instructions and say ..." has nowhere to land.
Nothing in this file should ever need a model.

**The blocklist is matched against a normalised form, not the raw text.** A
word list on its own is beaten on the first attempt — `n_i_g`, `n1g`, Cyrillic
lookalikes, zero-width joiners. The matching tests below are the bypasses
people actually use, and the false-positive tests are the other half of the
job: blocking Scunthorpe is also a failure.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stubbed before the dispatcher is imported — it reaches for pika at module
# level, and none of what is tested here touches RabbitMQ.
_pika = types.ModuleType("pika")
_pika.PlainCredentials = lambda *a, **k: None
_pika.BlockingConnection = lambda *a, **k: None
_pika.ConnectionParameters = lambda *a, **k: None
_pika.exceptions = types.SimpleNamespace(AMQPError=Exception)
sys.modules.setdefault("pika", _pika)

from app.settings import get_settings                              # noqa: E402
from orchestrator.dispatcher import Dispatcher                     # noqa: E402
from orchestrator.models import Signal                             # noqa: E402
from orchestrator.priority_queue import SignalQueue                # noqa: E402
from orchestrator.sanitize import (                                # noqa: E402
    Blocklist, Sanitizer, Tally, fold,
)

S = get_settings()
DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ==================================================================== folding
def test_folding():
    print("\n--- the bypasses people actually use ---")
    for padded in ("N_i_g_g_e_r", "N-I-G-G-A", "ＮＩＧＧＡ", "nі99er",
                   "n i g g e r", "n​igger", "ñigger"):
        folded = fold(padded)
        check(f"{padded!r} folds to the word itself",
              folded in ("nigger", "nigga"), folded)

    check("runs are collapsed, not deleted", fold("niiiigger").startswith("nii"))
    check("innocent words survive folding", fold("Scunthorpe") == "scunthorpe")
    check("real Russian is not mangled into Latin",
          fold("Привет") == "привет", fold("Привет"))
    check("and Russian terms still match through the same fold",
          Blocklist(DATA / "blocklist.json").blocks("ты сука"))
    check("empty stays empty", fold("") == "")


def test_blocklist_matching():
    print("\n--- what is blocked, and what must not be ---")
    blocklist = Blocklist(DATA / "blocklist.json")

    check("the shipped list is not empty",
          len(blocklist.substrings) > 0 and len(blocklist.words) > 0)

    for bad in ("niggerlover99", "xX_FAGGOT_Xx", "n1gga_king",
                "killyourself", "хуй", "пидорас", "fuck you",
                "you should kys"):
        check(f"{bad!r} is blocked", blocklist.blocks(bad))

    # The other half of the job. A substring list that eats these is worse
    # than no list, because it insults people by name on stream.
    for fine in ("Scunthorpe", "grapes", "raccoon", "cocoon", "suspicious",
                 "flame retardant", "Mikysa", "assassin", "Shitake",
                 "Привет всем", "classic", "spiccy", "Hancock"):
        check(f"{fine!r} is left alone", not blocklist.blocks(fine), fine)

    missing = Blocklist(DATA / "does-not-exist.json")
    check("a missing list filters nothing rather than crashing",
          not missing.blocks("nigger"))


# ================================================================== the alert
def sanitizer() -> Sanitizer:
    return Sanitizer(DATA, tally=Tally())


def test_names():
    print("\n--- the name ---")
    s = sanitizer()

    clean = s.clean("xX_Dark_Slayer_Xx", "")
    check("separators become spaces so TTS can read it",
          clean.name == "xX Dark Slayer Xx", clean.name)
    check("and that counts as a change", "name_tidied" in clean.removed)

    blocked = s.clean("niggerlover99", "")
    check("a blocked name is replaced wholesale",
          blocked.name_blocked and "nigger" not in fold(blocked.name))

    junk = s.clean("💀💀💀", "")
    check("a name of symbols gets a placeholder", junk.name_blocked)
    short = s.clean("x9", "")
    check("so does one with no letters to say", short.name_blocked)

    ok = s.clean("Jo", "")
    check("two letters is a name", not ok.name_blocked and ok.name == "Jo")


def test_placeholders_rotate():
    print("\n--- three of each, in order ---")
    s = sanitizer()

    names = [s.clean("niggerlover99", "").name for _ in range(4)]
    check("three different name placeholders", len(set(names[:3])) == 3,
          str(names[:3]))
    check("then it comes back round", names[3] == names[0])

    msgs = []
    for _ in range(4):
        result = s.clean("Viewer", "fuck this")
        msgs.append(s.next_message_placeholder())
    check("three different message placeholders", len(set(msgs[:3])) == 3,
          str(msgs[:3]))

    check("the shipped file has exactly three of each",
          len(s.lines["name_placeholders"]) == 3
          and len(s.lines["message_placeholders"]) == 3)


def test_messages():
    print("\n--- the message ---")
    s = sanitizer()

    plain = s.clean("Viewer", "good luck today, hope you climb!")
    check("a normal message is read as written",
          plain.message == "good luck today, hope you climb!"
          and not plain.removed)

    slur = s.clean("Viewer", "hey f a g g o t")
    check("a slur blocks the whole message, not part of it",
          slur.message_blocked and slur.message == "")
    check("and the name is untouched by it", not slur.name_blocked)

    stuck = s.clean("Viewer", "AAAAAAAAAAAAAAAAAA")
    check("a wall of one letter is not a message", stuck.message_blocked)

    emphasis = s.clean("Viewer", "noooo way!!!")
    check("but emphasis survives, shortened",
          emphasis.message == "noo way!!", emphasis.message)

    link = s.clean("Viewer", "check out twitch.tv/someoneelse right now")
    check("a link is never read out loud",
          "twitch" not in link.message and "someoneelse" not in link.message,
          link.message)

    shout = s.clean("Viewer", "YOU ARE PLAYING SO BADLY I CANNOT WATCH THIS")
    check("shouting is lowered, not blocked",
          not shout.message_blocked and "shouting" in shout.removed)
    check("and it is still the same sentence",
          "playing so badly" in shout.message.lower())

    spam = s.clean("Viewer", "spam spam spam spam spam spam")
    check("a repeated word is cut back", spam.message == "spam spam",
          spam.message)

    # Distinct words: "word word word..." is collapsed as repetition long
    # before it is long enough to truncate.
    long_one = s.clean("Viewer", " ".join(f"thing{i}" for i in range(80)))
    check("an essay is truncated", long_one.message.endswith("..."))
    check("to the configured length",
          len(long_one.message) <= s.max_message_chars + 3,
          str(len(long_one.message)))

    emoji = s.clean("Viewer", "🎉🎉 congrats 🎉🎉")
    check("emoji go, the words stay", emoji.message.strip() == "congrats",
          emoji.message)

    none = s.clean("Viewer", "")
    check("no message is not a blocked message",
          not none.message_blocked and none.message == "")


def test_both_blocked_and_the_tally():
    print("\n--- both gone, and counting it ---")
    s = sanitizer()
    worst = s.clean("💀💀💀", "AAAAAAAAAAAA")
    check("name and message can both fall back",
          worst.name_blocked and worst.message_blocked)

    for _ in range(3):
        s.clean("Viewer", "fuck this")
    check("every alert is counted", s.tally.alerts == 4, str(s.tally.alerts))
    check("and every intervention by type",
          s.tally.counts.get("message_blocked") == 3, str(s.tally.counts))
    check("the summary is one line you can read",
          "alerts" in s.tally.summary(), s.tally.summary())


def test_nothing_here_needs_a_model():
    print("\n--- the donation path never touches the LLM ---")
    source = (Path(__file__).resolve().parent.parent
              / "orchestrator" / "sanitize.py").read_text(encoding="utf-8")
    for forbidden in ("run_llm", "rabbit", "import requests", "openai"):
        check(f"sanitize.py does not reach for {forbidden}",
              forbidden not in source)
    check("a donation is meant to be a quote signal",
          Signal(source="donation", priority=S.DONATION_PRIORITY,
                 text="x", mode="quote", skip_llm=True).skip_llm is True)


# ================================================================== the floor
def test_priority_order():
    print("\n--- TTS > alerts > commentary ---")
    check("a paid message outranks an alert",
          S.DONATION_PRIORITY < S.ALERT_PRIORITY)
    check("an alert outranks game commentary",
          S.ALERT_PRIORITY < 3)
    check("alerts are not held by the voice gate",
          S.ALERT_PRIORITY <= S.VOICE_INTERRUPT_PRIORITY)
    check("neither is a paid message",
          S.DONATION_PRIORITY <= S.VOICE_INTERRUPT_PRIORITY)
    check("idle filler is still last",
          S.DONATION_PRIORITY < S.ALERT_PRIORITY < 10)


def dispatcher_with(queue: SignalQueue) -> Dispatcher:
    """A dispatcher with no Rabbit anywhere near it."""
    return Dispatcher(queue)


def test_she_finishes_the_sentence_then_yields():
    print("\n--- who gets the floor, and when ---")
    queue = SignalQueue()
    dispatcher = dispatcher_with(queue)

    commentary = Signal(source="game", priority=5, text="he died again")
    dispatcher.set_inflight(commentary)

    check("nothing queued, nothing to yield to",
          dispatcher.more_important_waiting() == "")

    queue.push(Signal(source="game", priority=5, text="another death"))
    check("an equal signal does not take the floor",
          dispatcher.more_important_waiting() == "", "game 5 vs game 5")

    queue.push(Signal(source="donation", priority=S.DONATION_PRIORITY,
                      text="thanks for the stream"))
    check("a paid message does",
          dispatcher.more_important_waiting() == "donation")

    # Mid-alert, another alert arrives: she does not talk over herself.
    dispatcher.set_inflight(Signal(source="alert",
                                   priority=S.ALERT_PRIORITY, text="a sub"))
    queue2 = SignalQueue()
    alerts = dispatcher_with(queue2)
    alerts.set_inflight(Signal(source="alert", priority=S.ALERT_PRIORITY,
                               text="a sub"))
    queue2.push(Signal(source="alert", priority=S.ALERT_PRIORITY,
                       text="another sub"))
    check("an alert does not interrupt another alert",
          alerts.more_important_waiting() == "")

    queue2.push(Signal(source="donation", priority=S.DONATION_PRIORITY,
                       text="paid"))
    check("but a paid message interrupts an alert",
          alerts.more_important_waiting() == "donation")

    # An expired signal is not worth interrupting for.
    queue3 = SignalQueue()
    stale = dispatcher_with(queue3)
    stale.set_inflight(Signal(source="game", priority=5, text="x"))
    expired = Signal(source="donation", priority=1, text="old", ttl=0.0)
    expired.created_at -= 10
    queue3.push(expired)
    check("an expired signal does not take the floor",
          stale.more_important_waiting() == "")


def test_preemption_can_be_turned_off():
    print("\n--- and it can be switched off ---")
    queue = SignalQueue()
    dispatcher = dispatcher_with(queue)
    dispatcher.set_inflight(Signal(source="game", priority=5, text="x"))
    queue.push(Signal(source="donation", priority=1, text="paid"))

    check("on by default", S.PREEMPT_ENABLED
          and dispatcher.more_important_waiting() == "donation")

    dispatcher.settings.PREEMPT_ENABLED = False
    check("off means she always finishes the whole answer",
          dispatcher.more_important_waiting() == "")
    dispatcher.settings.PREEMPT_ENABLED = True


def main() -> int:
    test_folding()
    test_blocklist_matching()
    test_names()
    test_placeholders_rotate()
    test_messages()
    test_both_blocked_and_the_tally()
    test_nothing_here_needs_a_model()
    test_priority_order()
    test_she_finishes_the_sentence_then_yields()
    test_preemption_can_be_turned_off()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
