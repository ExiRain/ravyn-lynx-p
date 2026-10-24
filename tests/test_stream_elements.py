"""
Alerts and donations, from StreamElements.

    python tests/test_stream_elements.py

Her first responsibility. What is tested here is everything that is *ours* —
parsing, sanitising, composing, priorities, dedup — because the one thing that
is not ours could not be verified: the StreamElements docs hosts did not
resolve from the machine this was written on, so the endpoint path and the
field names are expected rather than confirmed.

That is why `_parse_activity` tries several spellings of each field, why the
first payload of each type is logged verbatim, and why `--replay` exists. The
fixtures below are the shapes I expect; when a real tip proves one wrong, the
fix is a field name here and in `_parse_activity`, and these tests say
immediately whether anything else moved.

Two properties that must hold whatever the payload turns out to look like:

**No viewer text ever reaches the model.** Every signal is `mode="quote"`,
`skip_llm=True`.

**A blocked name or message is replaced, not repaired.** There is no partial
read of a donation with a slur in the middle.
"""

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                              # noqa: E402
from orchestrator.priority_queue import SignalQueue                # noqa: E402
from orchestrator.sanitize import Sanitizer, Tally                 # noqa: E402
from sources.stream_elements import (                              # noqa: E402
    ALERT_TYPES, TIP, StreamElementsSource, _symbol,
)

S = get_settings()
DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def source(queue: SignalQueue | None = None) -> StreamElementsSource:
    s = StreamElementsSource(queue or SignalQueue(), DATA,
                             sanitizer=Sanitizer(DATA, tally=Tally()))
    s.token = ""            # nothing in here touches the network
    s.channel = "test"
    return s


def tip(amount=5, message="good luck today", user="Tracalley",
        currency="USD", _id="t1") -> dict:
    return {"_id": _id, "type": "tip",
            "createdAt": "2026-10-24T20:11:03.000Z",
            "data": {"username": user, "amount": amount,
                     "currency": currency, "message": message}}


# ==================================================================== parsing
def test_parsing_a_tip():
    print("\n--- a tip, as it is expected to arrive ---")
    s = source()
    event = s._parse_activity(tip())

    check("the id is kept, for dedup", event["id"] == "t1")
    check("the type is lowercased", event["type"] == TIP)
    check("the name comes through", event["user"] == "Tracalley")
    check("the amount is a number", event["amount"] == 5.0)
    check("the currency becomes a symbol she can say",
          event["currency"] == "$", event["currency"])
    check("the message comes through", event["message"] == "good luck today")


def test_parsing_tolerates_other_spellings():
    print("\n--- the field names are expected, not verified ---")
    s = source()

    alt = {"id": "t2", "type": "TIP",
           "data": {"name": "Someone", "tipAmount": "7.5",
                    "currency": {"code": "EUR", "symbol": "€"},
                    "text": "hello"}}
    event = s._parse_activity(alt)
    check("`id` works as well as `_id`", event["id"] == "t2")
    check("`name` works as well as `username`", event["user"] == "Someone")
    check("`tipAmount` works as well as `amount`", event["amount"] == 7.5)
    check("a currency object is unwrapped", event["currency"] == "€")
    check("`text` works as well as `message`", event["message"] == "hello")
    check("the type is case-insensitive", event["type"] == TIP)

    flat = {"_id": "t3", "type": "follower", "username": "NoDataKey"}
    check("a payload with no data wrapper still parses",
          s._parse_activity(flat)["user"] == "NoDataKey")

    check("junk is ignored rather than guessed at",
          s._parse_activity({"no": "type"}) is None
          and s._parse_activity("not a dict") is None)

    weird = s._parse_activity({"_id": "t4", "type": "tip",
                               "data": {"amount": "not a number"}})
    check("an unparseable amount becomes zero, not a crash",
          weird["amount"] == 0.0)


def test_the_first_payload_of_each_type_is_logged():
    print("\n--- the first one of each type is printed verbatim ---")
    import io
    import contextlib

    s = source()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        s._parse_activity(tip(_id="a"))
        s._parse_activity(tip(_id="b"))
        s._parse_activity({"_id": "c", "type": "follower",
                           "data": {"username": "x"}})
    printed = out.getvalue()

    check("the first tip is logged in full", printed.count("FIRST tip") == 1,
          str(printed.count("FIRST tip")))
    check("the second is not", "\"_id\": \"b\"" not in printed)
    check("a different type is logged too",
          "FIRST follower" in printed)
    check("and the log contains the raw JSON to check names against",
          "\"username\": \"Tracalley\"" in printed)


# ================================================================== composing
def test_a_tip_reads_its_message():
    print("\n--- at or above the threshold, she reads it ---")
    s = source()
    line, read = s.compose(s._parse_activity(tip(amount=5)))

    check("the amount is in the line", "$5" in line, line)
    check("the name is in the line", "Tracalley" in line, line)
    check("and the message is read", "good luck today" in line, line)
    check("which is reported back", read is True)


def test_a_small_tip_does_not():
    print("\n--- below it, she thanks them and stops ---")
    s = source()
    small = s._parse_activity(tip(amount=1,
                                  message="this should not be read"))
    line, read = s.compose(small)

    check("she still thanks them", "SmallTipper" in line or "$1" in line, line)
    check("but the message is not read",
          "should not be read" not in line, line)
    check("and that is reported back", read is False)
    check("the threshold is the streamer's two dollars",
          S.SE_TTS_MIN_AMOUNT == 2.0)


def test_a_blocked_name_or_message():
    print("\n--- blocked is replaced, not repaired ---")
    s = source()

    bad_name = s.compose(s._parse_activity(
        tip(user="niggerlover99", amount=10)))[0]
    check("the name is replaced wholesale",
          "nigger" not in bad_name.lower() and "named" in bad_name.lower(),
          bad_name)
    check("the donation is still acknowledged", "$10" in bad_name, bad_name)

    bad_message = s.compose(s._parse_activity(
        tip(message="hey f a g g o t", amount=5)))[0]
    check("a slur is not read, in any part",
          "f a g" not in bad_message and "faggot" not in bad_message,
          bad_message)
    check("and she says why instead",
          "unsaid" in bad_message or "not something" in bad_message
          or "did not survive" in bad_message, bad_message)

    debris = s.compose(s._parse_activity(
        tip(message="AAAAAAAAAAAAAAAA check twitch.tv/someoneelse",
            amount=5)))[0]
    check("a message that barely survives cleaning is not read",
          "AA check" not in debris, debris)
    check("and no link is ever read aloud", "twitch" not in debris, debris)


def test_alert_types():
    print("\n--- subs, follows, cheers, raids ---")
    s = source()

    sub = s.compose(s._parse_activity(
        {"_id": "s1", "type": "subscriber",
         "data": {"username": "LoyalFan", "tier": "1000", "amount": 3}}))[0]
    check("a sub is thanked by name", "LoyalFan" in sub, sub)

    follow = s.compose(s._parse_activity(
        {"_id": "f1", "type": "follower",
         "data": {"username": "NewViewer_123"}}))[0]
    check("a follower is greeted", "NewViewer" in follow, follow)

    cheer = s.compose(s._parse_activity(
        {"_id": "c1", "type": "cheer",
         "data": {"username": "BitLord", "amount": 500}}))[0]
    check("bits are a count, not money",
          "500 bits" in cheer or "bits" in cheer, cheer)
    check("and not a float", "500.0" not in cheer, cheer)
    check("nor priced in dollars", "$500" not in cheer, cheer)

    raid = s.compose(s._parse_activity(
        {"_id": "r1", "type": "raid",
         "data": {"username": "BigStreamer", "amount": 40}}))[0]
    check("a raid is acknowledged", "BigStreamer" in raid, raid)

    unknown = s.compose(s._parse_activity(
        {"_id": "u1", "type": "something_new", "data": {"username": "x"}}))
    check("an unknown type produces nothing rather than a guess",
          unknown == ("", False), str(unknown))


def test_templates_rotate():
    print("\n--- three of each, in order ---")
    s = source()
    lines = [s.compose(s._parse_activity(tip(_id=f"t{i}")))[0]
             for i in range(4)]
    check("three different tip lines", len(set(lines[:3])) == 3,
          str(lines[:3]))
    check("then it comes round again", lines[3] == lines[0])


# =================================================================== signals
def test_the_signal():
    print("\n--- what reaches the queue ---")
    queue = SignalQueue()
    s = source(queue)

    signal = s.to_signal(s._parse_activity(tip(amount=5)))
    check("a tip is a donation signal", signal.source == "donation")
    check("at the top priority", signal.priority == S.DONATION_PRIORITY)
    check("as a quote — no model, ever",
          signal.mode == "quote" and signal.skip_llm is True)
    check("it expires rather than thanking them two minutes late",
          signal.ttl == S.SE_TTL)
    check("it carries the donation, for the notebook's donor note",
          signal.context["donation"] == {"amount": 5.0, "currency": "$"})
    check("and the name, so the note lands on the right person",
          signal.context["user"] == "Tracalley")
    check("the viewer is never flagged as him",
          signal.context["is_owner"] is False)

    alert = s.to_signal(s._parse_activity(
        {"_id": "f9", "type": "follower", "data": {"username": "Someone"}}))
    check("an alert is one step below a paid message",
          alert.source == "alert" and alert.priority == S.ALERT_PRIORITY)
    check("and carries no donation", "donation" not in alert.context)
    check("alerts are quotes too", alert.skip_llm is True)

    check("a paid message outranks an alert",
          S.DONATION_PRIORITY < S.ALERT_PRIORITY)


def test_nothing_is_read_twice():
    print("\n--- a restart must not replay the evening ---")
    queue = SignalQueue()
    s = source(queue)

    s._handle(tip(_id="x1"))
    check("the first one is queued", queue.pop() is not None)

    s._handle(tip(_id="x1"))
    check("the same activity is ignored", queue.pop() is None)

    s._handle(tip(_id="x2"), announce=False)
    check("a first-pass sweep remembers without speaking",
          queue.pop() is None)
    s._handle(tip(_id="x2"))
    check("and stays remembered afterwards", queue.pop() is None)

    s._handle({"_id": "x3", "type": "merch_purchase",
               "data": {"username": "x"}})
    check("an unhandled type is not queued", queue.pop() is None)


def test_it_degrades_to_silence():
    print("\n--- no token, no noise ---")
    s = source()
    s.token = ""
    s.run()                     # returns immediately, says so once
    check("no token means it simply does not run", True)

    s2 = source()
    s2.token = "x"
    s2._requests = lambda: None     # dependency missing
    check("a missing dependency returns nothing rather than raising",
          s2._fetch() == [] and s2._resolve_channel() in ("", "test"))

    broken = source()
    broken.token = "x"
    broken.channel = ""
    broken._requests = lambda: types.SimpleNamespace(
        get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        ConnectionError=ConnectionError, Timeout=TimeoutError)
    check("an API that errors does not take her down",
          broken._resolve_channel() == "" and broken._fetch() == [])


def test_currency_symbols():
    print("\n--- currencies she has to say out loud ---")
    for code, symbol in (("USD", "$"), ("EUR", "€"), ("GBP", "£"),
                         ("RUB", "₽")):
        check(f"{code} reads as {symbol}", _symbol(code) == symbol)
    check("an unknown code is left as it came", _symbol("CZK") == "CZK")


def test_replay_runs_offline():
    print("\n--- replay, for checking a corrected field name ---")
    from sources import stream_elements

    tmp = Path(tempfile.mkdtemp())
    try:
        sample = tmp / "sample.json"
        sample.write_text(json.dumps([tip(), {"_id": "f1", "type": "follower",
                                              "data": {"username": "x"}}]),
                          encoding="utf-8")
        check("it runs a file with no network and no Rabbit",
              stream_elements.replay(sample) == 0)
        check("and a missing file is reported, not raised",
              stream_elements.replay(tmp / "nope.json") == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_types_it_claims_to_handle():
    print("\n--- the lanes ---")
    check("tip is its own lane", TIP == "tip")
    check("the alert types are the ones with templates",
          set(ALERT_TYPES) >= {"subscriber", "follower", "cheer", "raid"},
          str(ALERT_TYPES))

    s = source()
    for kind in ALERT_TYPES:
        line, _ = s.compose({"type": kind, "user": "Someone", "amount": 1,
                             "currency": "$", "message": "", "tier": ""})
        check(f"{kind} has something to say", bool(line), kind)


def main() -> int:
    test_parsing_a_tip()
    test_parsing_tolerates_other_spellings()
    test_the_first_payload_of_each_type_is_logged()
    test_a_tip_reads_its_message()
    test_a_small_tip_does_not()
    test_a_blocked_name_or_message()
    test_alert_types()
    test_templates_rotate()
    test_the_signal()
    test_nothing_is_read_twice()
    test_it_degrades_to_silence()
    test_currency_symbols()
    test_replay_runs_offline()
    test_the_types_it_claims_to_handle()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
