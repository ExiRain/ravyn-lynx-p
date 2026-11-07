"""
Every event she is supposed to react to actually reaches her.

    python tests/test_event_registration.py

The audit of 2026-11-07, after a new follower went ungreeted. Across the
2026-11-02 and 11-06 sessions (eight games):

  - follows were dropped: StreamElements says "follow", only "follower" counted
  - zero Aces were spoken: an Ace ends a fight, so the 20s gap always ate it
  - 6 of 7 game endings got no line at all: the API went away before GameEnd
  - one game was counted twice: the post-game screen was "detected" as a game
  - YouTube Super Chats and memberships were skipped as "not chat lines"
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# test_identity stubs out requests/urllib3 and has the real-shaped game.
from test_identity import real_game, DATA                  # noqa: E402

import sources.lol_game as lol                             # noqa: E402
from app.settings import get_settings                      # noqa: E402
from orchestrator.priority_queue import SignalQueue        # noqa: E402
from orchestrator.temper import Temper                     # noqa: E402
from sources.lol_game import LolGameSource                 # noqa: E402
from sources.stream_elements import StreamElementsSource   # noqa: E402
from sources import youtube_alerts                         # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def in_game(t=1500.0):
    """A live game, his team ORDER, with whatever it pushes collected."""
    src = LolGameSource(SignalQueue(), DATA, temper=Temper())
    pushed = []
    src.queue.push = lambda sig: pushed.append(sig)
    src._fetch = lambda: real_game(t=t)
    src._check_for_game()
    src._poll_game()
    pushed.clear()
    src._last_game_comment = 0.0       # the GameStart line is not in the way
    return src, pushed


def kinds(pushed):
    return [p.context.get("event_type") for p in pushed]


# ================================================================ league
def test_big_moments_cut_through_the_gap():
    print("\n--- Ace, Baron, soul and Elder are said every time ---")
    for name, event in (
            ("Ace", {"EventName": "Ace", "AcingTeam": "ORDER",
                     "Acer": "riven#RU", "EventTime": 1500}),
            ("BaronKill", {"EventName": "BaronKill", "KillerName": "darius#RU",
                           "Assisters": [], "Stolen": False,
                           "EventTime": 1500})):
        src, pushed = in_game()
        src._last_game_comment = 1495.0        # she JUST said something
        src._handle_event(event, real_game())
        check(f"{name} lands 5s after her last line", name in kinds(pushed),
              str(kinds(pushed)))

    src, pushed = in_game()
    src._last_game_comment = 1495.0
    src._handle_event({"EventName": "DragonKill", "DragonType": "Elder",
                       "KillerName": "darius#RU", "EventTime": 1500},
                      real_game())
    check("so does Elder", "DragonKill" in kinds(pushed), str(kinds(pushed)))

    src, pushed = in_game()
    src._last_game_comment = 1495.0
    src._handle_event({"EventName": "TurretKilled",
                       "TurretKilled": "Turret_T2_L_03_A",
                       "KillerName": "Серый Экран#RU", "EventTime": 1500},
                      real_game())
    check("an ordinary event still waits out the gap", pushed == [],
          str(kinds(pushed)))


def test_structures_are_sided_by_whose_they_were():
    print("\n--- a structure belongs to someone ---")
    lol.random.random = lambda: 0.0     # the chance roll always says yes
    src, pushed = in_game()
    # His team is ORDER; T1 is ORDER's. Killed by minions, no champion name.
    src._handle_event({"EventName": "InhibKilled",
                       "InhibKilled": "Barracks_T1_L1", "KillerName": "",
                       "EventTime": 1500}, real_game())
    check("losing our own inhibitor to minions is the enemy's",
          pushed and "enemy destroyed" in pushed[-1].text,
          pushed[-1].text if pushed else "nothing")

    src, pushed = in_game()
    src._handle_event({"EventName": "InhibKilled",
                       "InhibKilled": "Barracks_T2_R1",
                       "KillerName": "Minion_T100L1S07N0114",
                       "EventTime": 1500}, real_game())
    check("their inhibitor, taken by our minions, is ours",
          pushed and "teammates" in pushed[-1].text,
          pushed[-1].text if pushed else "nothing")
    check("(previously an empty killer read as the enemy)",
          src._structure_side("Barracks_T1_L1", "") == "enemy")


def test_one_missed_poll_is_not_the_end():
    print("\n--- one failed poll does not end the game ---")
    src, _ = in_game()
    src._fetch = lambda: None
    src._poll_game()
    check("still in the game after one miss", src.is_game_active)
    src._fetch = lambda: real_game(t=1502.0)
    src._poll_game()
    check("and the miss count resets when it answers", src._misses == 0)


def test_post_game_screen_is_not_a_new_game():
    print("\n--- the post-game screen is the same game ---")
    temper = Temper()
    src = LolGameSource(SignalQueue(), DATA, temper=temper)
    src.queue.push = lambda sig: None
    src._fetch = lambda: real_game(t=1800.0)
    src._check_for_game()
    src._poll_game()
    src._handle_event({"EventName": "GameEnd", "Result": "Lose"},
                      real_game(t=1800.0))
    check("GameEnd counts the game once", len(temper.games) == 1)
    check("and schedules the summary", src._summary_due > 0)

    src._fetch = lambda: real_game(t=1805.0)     # API still up after the end
    src._check_for_game()
    check("the API still answering is NOT a new game",
          not src.is_game_active, "re-detected")

    src._fetch = lambda: None
    src._check_for_game()
    src._fetch = lambda: real_game(t=10.0)
    src._check_for_game()
    check("after it goes away, the next game is detected",
          src.is_game_active)
    check("and the old game was counted exactly once", len(temper.games) == 1,
          str(len(temper.games)))


class FakeClient:
    def __init__(self, answers=None):
        self.answers = answers or []

    def eog(self):
        return self.answers.pop(0) if self.answers else None

    def game_id(self):
        return 100


def vanished_game(client):
    src = LolGameSource(SignalQueue(), DATA, temper=Temper())
    pushed = []
    src.queue.push = lambda sig: pushed.append(sig)
    src.client = client
    src._fetch = lambda: real_game(t=1800.0)
    src._check_for_game()
    src._poll_game()
    src._fetch = lambda: None
    for _ in range(lol.GONE_AFTER_MISSES):
        src._poll_game()
    pushed.clear()
    return src, pushed


def test_a_game_that_vanished_still_gets_its_ending():
    print("\n--- no GameEnd event, still an ending ---")
    won_block = {"gameId": 101,
                 "teams": [{"isPlayerTeam": True, "isWinningTeam": True}]}
    src, pushed = vanished_game(FakeClient([None, won_block]))
    src._maybe_resolve_result()
    check("nothing yet while the client has no result", pushed == [])
    src._maybe_resolve_result()
    check("the cheer and her line, once the client says who won",
          kinds(pushed) == ["GameCheer", "GameEnd"], str(kinds(pushed)))
    check("framed as a win",
          pushed and pushed[-1].context.get("won") is True)
    src._maybe_resolve_result()
    check("and only once", len(pushed) == 2)

    src, pushed = vanished_game(FakeClient())
    src._maybe_resolve_result()
    check("without a result she waits a little", pushed == [])
    src._end_line_due = time.time() - 1
    src._maybe_resolve_result()
    check("then says something without guessing the result",
          kinds(pushed) == ["GameEnd"]
          and "won" not in pushed[0].context, str(kinds(pushed)))


def test_unknown_league_events_are_reported():
    print("\n--- an event nobody handles is printed, once ---")
    import io
    import contextlib
    src, pushed = in_game()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        src._handle_event({"EventName": "AtakhanKill", "EventTime": 1500},
                          real_game())
        src._handle_event({"EventName": "AtakhanKill", "EventTime": 1501},
                          real_game())
        src._handle_event({"EventName": "MinionsSpawning", "EventTime": 65},
                          real_game())
    text = out.getvalue()
    check("a new event name is logged", "Unhandled event 'AtakhanKill'" in text,
          text)
    check("once", text.count("Unhandled event") == 1, text)


def test_numbers_say_whose_they_are():
    print("\n--- every number in the situation says whose it is ---")
    from orchestrator.game_state import GameState
    g = GameState()
    g.update(real_game(), "ORDER", {"серый экран#ru"})
    text = g.render()
    check("his own score is labelled as his",
          "HIS OWN score: 6 kills, 2 deaths, 3 assists" in text, text)
    check("team totals say they are not his",
          "NOT his own): your team 12, theirs 27" in text, text)
    check("CS rank is a CS rank, not a scoreboard place",
          "most CS of all ten players" in text, text)
    check("she is told not to move or add up numbers",
          "never add them up" in text)


# ================================================================ alerts
def se():
    queue = SignalQueue()
    return StreamElementsSource(queue, DATA), queue


def activity(_id, kind, **data):
    return {"_id": _id, "type": kind, "provider": "twitch", "data": data}


def test_streamelements_type_names():
    print("\n--- StreamElements' own type names ---")
    for kind, expect in (("follow", "follower"), ("subscriber", "subscriber"),
                         ("tip", "tip"), ("cheer", "cheer"), ("raid", "raid"),
                         ("sponsor", "subscriber"), ("superchat", "tip")):
        s, _ = se()
        event = s._parse_activity(activity("x", kind, username="Bob",
                                           amount=5))
        check(f"{kind!r} is read as {expect!r}", event["type"] == expect,
              event["type"])


def test_gift_bombs_and_follow_waves_are_one_line():
    print("\n--- a gift bomb is one thank-you, to the gifter ---")
    s, _ = se()
    gifts = [activity(f"g{i}", "subscriber", username=f"lucky{i}",
                      sender="Generous", gifted=True, amount=1)
             for i in range(20)]
    signals = s.announce(gifts)
    check("twenty gifted subs, one line", len(signals) == 1,
          str([x.text for x in signals]))
    check("thanking the gifter, with the count",
          signals and "Generous" in signals[0].text
          and "20" in signals[0].text, signals[0].text if signals else "")
    check("never a recipient", signals
          and "lucky" not in signals[0].text.lower())

    s, _ = se()
    wave = [activity(f"f{i}", "follow", username=f"bot{i}")
            for i in range(50)]
    signals = s.announce(wave)
    check("a follow wave is one line", len(signals) == 1
          and "50" in signals[0].text,
          str([x.text for x in signals][:3]))

    s, _ = se()
    few = [activity(f"h{i}", "follow", username=name)
           for i, name in enumerate(("Ann", "Ben"))]
    signals = s.announce(few)
    check("two real follows are each greeted by name",
          [("Ann" in x.text, "Ben" in x.text) for x in signals]
          == [(True, False), (False, True)], str([x.text for x in signals]))
    check("and get the face the mock events always did",
          all(x.context.get("event_type") == "follow" for x in signals))

    s, _ = se()
    signals = s.announce([activity("own", "subscriber", username="Self",
                                   amount=3)])
    check("a sub someone bought for themselves is still theirs",
          signals and "Self" in signals[0].text
          and signals[0].context.get("event_type") == "sub")


# ================================================================ youtube
def test_youtube_paid_events():
    print("\n--- YouTube Super Chats and memberships are thanked ---")
    check("$5.00", youtube_alerts.parse_amount("$5.00") == (5.0, "$"))
    check("RUB 1,000.00",
          youtube_alerts.parse_amount("RUB 1,000.00") == (1000.0, "RUB"))
    check("1.000,50 €",
          youtube_alerts.parse_amount("1.000,50 €") == (1000.5, "€"))

    s, queue = se()
    superchat = {"liveChatPaidMessageRenderer": {
        "id": "sc1", "authorName": {"simpleText": "@Patron"},
        "authorExternalChannelId": "UCpatron",
        "purchaseAmountText": {"simpleText": "$10.00"},
        "message": {"runs": [{"text": "keep going"}]}}}
    event = youtube_alerts.from_web_item(superchat)
    sig = s.push_external(event)
    check("a Super Chat is a donation", sig is not None
          and sig.source == "donation" and "Patron" in sig.text, str(sig))
    check("its message read out, sanitised, as a quote",
          sig is not None and "keep going" in sig.text and sig.skip_llm)
    check("the donor note lands on the YouTube viewer",
          sig is not None and sig.context.get("user_key") == "youtube:UCpatron")
    check("never twice", s.push_external(event) is None)

    member = {"liveChatMembershipItemRenderer": {
        "id": "m1", "authorName": {"simpleText": "Joiner"},
        "authorExternalChannelId": "UCjoin"}}
    sig = s.push_external(youtube_alerts.from_web_item(member))
    check("a new member is thanked as a member",
          sig is not None and "Joiner" in sig.text
          and "member" in sig.text.lower(), sig.text if sig else "")

    gift = {"liveChatSponsorshipsGiftPurchaseAnnouncementRenderer": {
        "id": "gm1", "authorExternalChannelId": "UCgift",
        "header": {"liveChatSponsorshipsHeaderRenderer": {
            "authorName": {"simpleText": "Santa"},
            "primaryText": {"runs": [{"text": "Gifted "}, {"text": "5"},
                                     {"text": " memberships"}]}}}}}
    sig = s.push_external(youtube_alerts.from_web_item(gift))
    check("gifted memberships thank the gifter with the count",
          sig is not None and "Santa" in sig.text and "5" in sig.text,
          sig.text if sig else "")

    api = {"id": "api1", "snippet": {
        "type": "superChatEvent",
        "superChatDetails": {"amountMicros": "2000000", "currency": "USD",
                             "userComment": "hi"}},
        "authorDetails": {"displayName": "ApiFan", "channelId": "UCapi"}}
    event = youtube_alerts.from_api_item(api)
    check("the API reader's Super Chat too", event and event["type"] == "tip"
          and event["amount"] == 2.0 and event["user"] == "ApiFan", str(event))
    check("a plain text line is not an alert",
          youtube_alerts.from_api_item(
              {"id": "t", "snippet": {"type": "textMessageEvent"}}) is None)


def main():
    test_big_moments_cut_through_the_gap()
    test_structures_are_sided_by_whose_they_were()
    test_one_missed_poll_is_not_the_end()
    test_post_game_screen_is_not_a_new_game()
    test_a_game_that_vanished_still_gets_its_ending()
    test_unknown_league_events_are_reported()
    test_numbers_say_whose_they_are()
    test_streamelements_type_names()
    test_gift_bombs_and_follow_waves_are_one_line()
    test_youtube_paid_events()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
