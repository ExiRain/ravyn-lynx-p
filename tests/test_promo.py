"""
Asking for a follow or a sub, and all the reasons not to.

    python tests/test_promo.py

A promo is the one thing she says that nobody asked for, so it is the one
thing with a cost when it lands badly: mid-teamfight, twice in ten minutes, or
over the top of him explaining something. The source is therefore almost
entirely gates, and the two streams are governed differently in KIND, not just
in numbers — which is the thing these tests pin down.

**League is measured in games and the clock does not apply.** Never during a
game, one to three minutes after one ends, and ONE ask per session — after the
2nd or the 3rd game, rolled at startup. Past four games she wonders aloud
about the end instead, once, and that outranks an ask that never found a gap.

**A variety stream has no games, so the clock is the whole rule** — once every
50-120 minutes, rolled fresh.

Five lines per pool either way, rotated, so none can land twice in a night.
"""

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import Settings, get_settings                   # noqa: E402
from orchestrator.priority_queue import SignalQueue               # noqa: E402
from orchestrator.temper import GameResult, Temper                # noqa: E402
from sources.promo import (                                        # noqa: E402
    END_WONDER, FOLLOW, SUBSCRIBE, PromoSource,
)
import sources.promo as promo_module                               # noqa: E402

S = get_settings()
DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeRandom:
    """
    Deterministic: the midpoint of any range, the first of any choice, and a
    dial for the coin flips. Tests that care about the ask slot set
    `_ask_after` directly rather than leaning on this.
    """

    def __init__(self, coin: float = 0.99):
        self.coin = coin

    def uniform(self, low, high):
        return (low + high) / 2.0

    def choice(self, options):
        return list(options)[0]

    def random(self):
        return self.coin


SHORT = 20.0        # minutes — an ordinary game


def game(minutes: float = SHORT) -> GameResult:
    return GameResult(won=True, kills=3, deaths=3, assists=3, minutes=minutes)


def source(games: int = 0, league: bool = True, coin: float = 0.99,
           temper: Temper | None = None, minutes: float = SHORT) -> PromoSource:
    Settings.LEAGUE_MODE = league
    promo_module.random = FakeRandom(coin)

    temper = temper or Temper()
    for _ in range(games):
        temper.record_game(game(minutes))

    return PromoSource(SignalQueue(), DATA, temper=temper)


def ready(p: PromoSource, now=None) -> str:
    """The gate's answer, with the silent 'not yet' marker stripped."""
    import time
    reason = p._blocked(now or time.time())
    return reason[len(p.QUIET):] if reason.startswith(p.QUIET) else reason


def restore() -> None:
    import random
    promo_module.random = random
    Settings.LEAGUE_MODE = True


# ===================================================================== timing
def test_the_clock_is_a_variety_stream_rule():
    print("\n--- the clock: 50-120 minutes, and only off League ---")
    import time
    p = source(league=False)
    wait = p._due - time.time()

    check("the first one is inside the range",
          S.PROMO_MIN_INTERVAL <= wait + 1 <= S.PROMO_MAX_INTERVAL,
          f"{wait / 60:.0f} min")
    check("the range is 50 to 120 minutes",
          (S.PROMO_MIN_INTERVAL, S.PROMO_MAX_INTERVAL) == (3000.0, 7200.0),
          f"{S.PROMO_MIN_INTERVAL}-{S.PROMO_MAX_INTERVAL}")
    check("rolled, not fixed",
          "uniform" in promo_module.PromoSource._interval.__code__.co_names)

    check("before it is due she says nothing",
          "not due" in ready(p), ready(p))
    check("and holding for the clock is silent in the log",
          p._blocked(time.time()).startswith(p.QUIET))

    p._due = time.time() - 1
    check("once due, nothing else is in the way", ready(p) == "", ready(p))
    restore()


def test_league_ignores_the_clock_entirely():
    """
    The streamer's correction: a League stream is measured in games. An ask
    that arrives because an hour has passed can land in champion select or on
    a loading screen.
    """
    print("\n--- League does not watch the clock ---")
    import time
    p = source(games=2)
    p._games_seen = 2
    p._last_game_end = time.time() - 600
    p._due = time.time() + 99 * 3600       # due in four days

    check("two games is enough even with the timer nowhere near",
          ready(p) == "", ready(p))

    fresh = source(games=0, league=True)
    fresh._due = time.time() - 99 * 3600   # overdue by days
    check("and an overdue timer does not earn an ask on its own",
          "no game has finished" in ready(fresh), ready(fresh))
    restore()


def test_firing_resets_the_clock():
    print("\n--- and the counting starts again ---")
    import time
    p = source(games=4, league=False)
    p._games_seen = 4

    before = p._due
    signal = p.fire(FOLLOW)
    check("something was queued", signal is not None and p.queue.pop() is not None)
    check("the next one is a fresh interval away", p._due > before,
          f"{(p._due - time.time()) / 60:.0f} min")
    check("and her one ask is spent", p._asked is True)
    restore()


# ====================================================================== gates
def test_not_during_a_game():
    print("\n--- never while he is playing ---")
    import time
    p = source(games=2)
    p._games_seen = 2
    p._last_game_end = time.time() - 600
    p.game_active = True

    check("a live game holds it", "game is running" in ready(p), ready(p))

    p.game_active = False
    check("and once the game is gone she may speak", ready(p) == "", ready(p))
    restore()


def test_the_wait_after_a_game():
    print("\n--- 1-3 minutes after one ends ---")
    import time
    p = source(games=2)
    p._games_seen = 2
    now = time.time()

    p._last_game_end = now - 10
    p._after_game_wait = 120.0
    check("ten seconds after a loss is too soon",
          "since the game ended" in ready(p, now), ready(p, now))

    p._last_game_end = now - 130
    check("two minutes later is fine", ready(p, now) == "", ready(p, now))

    check("the wait is inside the streamer's one-to-three minutes",
          S.PROMO_AFTER_GAME_MIN <= p._post_game_delay()
          <= S.PROMO_AFTER_GAME_MAX)
    check("and it is rolled per game, not fixed once",
          "uniform" in
          promo_module.PromoSource._post_game_delay.__code__.co_names)
    restore()


def test_one_ask_after_game_two_or_three():
    """
    The streamer's correction: a session is four or five games, so ONE ask is
    the whole budget, after the 2nd or the 3rd game, which of the two rolled
    at startup.
    """
    print("\n--- one ask, after game 2 or 3 ---")
    import time

    check("the two slots are the streamer's", S.PROMO_ASK_AFTER_GAMES == (2, 3))

    slots = set()
    for _ in range(40):
        import random as real_random
        promo_module.random = real_random
        slots.add(PromoSource(SignalQueue(), DATA, temper=Temper())._ask_after)
    check("and it is rolled between them, not fixed", slots == {2, 3},
          str(slots))

    early = source(games=1)
    early._ask_after = 2
    early._games_seen = 1
    early._last_game_end = time.time() - 600
    check("one game is too early for a slot-2 ask",
          "waiting for game 2" in ready(early), ready(early))

    early._games_seen = 2
    check("two games is the slot", ready(early) == "", ready(early))

    late = source(games=2)
    late._ask_after = 3
    late._games_seen = 2
    late._last_game_end = time.time() - 600
    check("a slot-3 ask waits past the second game",
          "waiting for game 3" in ready(late), ready(late))

    late._games_seen = 3
    check("and lands on the third", ready(late) == "", ready(late))

    # The budget is one.
    spent = source(games=3)
    spent._ask_after = 2
    spent._games_seen = 3
    spent._last_game_end = time.time() - 600
    spent._asked = True
    check("having asked once, she does not ask again",
          "one ask this session" in ready(spent), ready(spent))

    check("the slot is fixed for the evening, not re-rolled per check",
          "_ask_after" in promo_module.PromoSource.__init__.__code__.co_names)
    restore()


def test_the_end_question_outranks_a_missed_ask():
    print("\n--- on the fourth game, a late advert is worse than none ---")
    import time
    p = source(games=4)
    p._ask_after = 3
    p._games_seen = 4
    p._last_game_end = time.time() - 600
    p._asked = False               # the slot came and went without a gap

    check("she is allowed to speak", ready(p) == "", ready(p))
    check("and what she says is the end question, not the ask",
          p._pool() == END_WONDER)
    restore()


def test_a_session_gets_one_of_each():
    """
    Four games: one ask, then the wondering. The streamer's arithmetic, and
    the reason neither is a coin flip.
    """
    print("\n--- four games, one ask and one wondering ---")
    import time

    for slot in (2, 3):
        temper = Temper()
        p = source(temper=temper)
        p._ask_after = slot
        said = []

        for number in range(1, 6):
            temper.record_game(game(SHORT))
            p._watch_games()
            p._last_game_end = time.time() - 600    # past the post-game wait
            if ready(p) == "":
                said.append(p.fire().context["promo"])

        check(f"slot {slot}: she speaks exactly twice in five games",
              len(said) == 2, str(said))
        check(f"slot {slot}: an ask first",
              said and said[0] in (FOLLOW, SUBSCRIBE), str(said))
        check(f"slot {slot}: then the end question",
              len(said) > 1 and said[1] == END_WONDER, str(said))

    # The honest consequence of his rule: a short session can miss the ask.
    temper = Temper()
    p = source(temper=temper)
    p._ask_after = 3
    said = []
    for _ in range(2):
        temper.record_game(game(SHORT))
        p._watch_games()
        p._last_game_end = time.time() - 600
        if ready(p) == "":
            said.append(p.fire().context["promo"])
    check("a two-game session with a slot-3 ask gets nothing, by design",
          said == [], str(said))
    restore()


def test_a_game_ending_is_noticed_without_being_told():
    print("\n--- it reads the game count rather than being told ---")
    temper = Temper()
    p = source(temper=temper)

    check("nothing seen yet", p._games_seen == 0 and p._last_game_end == 0.0)

    temper.record_game(GameResult(won=False, kills=1, deaths=9, assists=1))
    p._watch_games()
    check("a finished game is noticed", p._games_seen == 1)
    check("and the moment it ended is recorded", p._last_game_end > 0)

    stamp = p._last_game_end
    p._watch_games()
    check("the same game is not noticed twice", p._last_game_end == stamp)
    restore()


def test_outside_league_only_the_clock_applies():
    print("\n--- a stream that is not League ---")
    import time
    p = source(league=False)
    p._due = time.time() - 1
    p.game_active = True              # nothing is setting this; it is stale
    p._games_seen = 0

    check("no game gates at all", ready(p) == "", ready(p))
    check("and she never wonders about game four",
          p._pool() in (FOLLOW, SUBSCRIBE))

    p._games_seen = 9
    check("not even with a stale game count",
          p._pool() in (FOLLOW, SUBSCRIBE))
    restore()


# ====================================================================== lines
def test_the_pools():
    print("\n--- what she actually says ---")
    p = source()
    data = json.loads((DATA / "promo.json").read_text(encoding="utf-8"))

    for pool in (FOLLOW, SUBSCRIBE, END_WONDER):
        check(f"{pool} has the five variations asked for",
              len(data.get(pool, [])) == 5, str(len(data.get(pool, []))))
        check(f"{pool} is loaded", len(p.lines[pool]) == 5)

    lines = [p._line(FOLLOW) for _ in range(6)]
    check("five different lines before any repeat",
          len(set(lines[:5])) == 5, str(len(set(lines[:5]))))
    check("then it comes round again", lines[5] == lines[0])

    check("the streamer's own wondering line is in there",
          any("wonders" in line.lower() for line in p.lines[END_WONDER]))
    restore()


def test_which_ask():
    print("\n--- follow, sub, or wondering about the end ---")
    p = source()
    p._games_seen = 0

    picks = [p._pool() for _ in range(4)]
    check("it alternates rather than favouring one",
          picks == [FOLLOW, SUBSCRIBE, FOLLOW, SUBSCRIBE], str(picks))

    p._games_seen = 3
    check("three games is not yet the end of anything",
          p._pool() in (FOLLOW, SUBSCRIBE))

    p._games_seen = 4
    check("after four games she wonders about the end",
          p._pool() == END_WONDER)

    # The budget is spent when a line GOES OUT, not when one is chosen — a
    # signal that failed to build would otherwise burn the session's only ask
    # with nobody hearing it. So the chooser keeps offering the wondering
    # until it has actually been said.
    p.fire()
    check("and then never again this session — an observation repeated is a "
          "nag",
          END_WONDER not in [p._pool() for _ in range(3)])

    check("four is the streamer's number", S.PROMO_END_WONDER_AFTER == 4)
    restore()


def test_a_missing_file_does_not_silence_her():
    print("\n--- and it degrades rather than crashing ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        p = PromoSource(SignalQueue(), tmp)
        check("every pool still has something",
              all(p.lines[pool] for pool in (FOLLOW, SUBSCRIBE, END_WONDER)))
        check("and a line comes out", bool(p._line(FOLLOW)))

        (tmp / "promo.json").write_text("{not json", encoding="utf-8")
        broken = PromoSource(SignalQueue(), tmp)
        check("malformed JSON falls back rather than raising",
              bool(broken._line(SUBSCRIBE)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================== signal
def test_the_signal():
    print("\n--- what reaches the queue ---")
    p = source()
    signal = p.build(FOLLOW)

    check("it is its own source", signal.source == "promo")
    check("spoken verbatim — a call to action is not paraphrased",
          signal.mode == "quote" and signal.skip_llm is True)
    check("under everything that matters",
          signal.priority == S.PROMO_PRIORITY
          and signal.priority > S.ALERT_PRIORITY
          and signal.priority > 5)
    check("but HELD rather than discarded while he talks",
          signal.priority < S.VOICE_AMBIENT_PRIORITY,
          f"{signal.priority} vs {S.VOICE_AMBIENT_PRIORITY}")
    check("it expires rather than arriving after the moment",
          signal.ttl == S.PROMO_TTL)
    check("the ask is on the record, for the session log",
          signal.context["promo"] == FOLLOW)
    check("and so is how many games had been played",
          "games" in signal.context)
    check("it is her own voice, not a mirror of a chatter",
          signal.lang == S.LANG_AMBIENT)

    empty = PromoSource(SignalQueue(), DATA)
    empty.lines = {FOLLOW: []}
    check("no line means no signal rather than an empty one",
          empty.build(FOLLOW) is None)
    restore()


def test_it_can_be_turned_off():
    print("\n--- and switched off entirely ---")
    check("on by default", S.PROMO_ENABLED)

    Settings.PROMO_ENABLED = False
    p = source()
    p.run()                 # returns immediately
    check("disabled means it does not run", True)
    Settings.PROMO_ENABLED = True
    restore()


def main() -> int:
    test_the_clock_is_a_variety_stream_rule()
    test_league_ignores_the_clock_entirely()
    test_firing_resets_the_clock()
    test_not_during_a_game()
    test_the_wait_after_a_game()
    test_one_ask_after_game_two_or_three()
    test_the_end_question_outranks_a_missed_ask()
    test_a_session_gets_one_of_each()
    test_a_game_ending_is_noticed_without_being_told()
    test_outside_league_only_the_clock_applies()
    test_the_pools()
    test_which_ask()
    test_a_missing_file_does_not_silence_her()
    test_the_signal()
    test_it_can_be_turned_off()
    restore()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
