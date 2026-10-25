"""
Asking for a follow or a sub, and all the reasons not to.

    python tests/test_promo.py

A promo is the one thing she says that nobody asked for, so it is the one
thing with a cost when it lands badly: mid-teamfight, twice in ten minutes, or
over the top of him explaining something. The source is therefore almost
entirely gates, and these are the streamer's rules as he wrote them:

    once every 40-80 minutes      rolled fresh, never a fixed cadence
    never during a game           he is playing; she is not interrupting
    1-3 minutes after one ends    the post-game screen, not the instant of defeat
    after every 2nd game          games are short
    after 4 games                 she may wonder aloud about the end instead
    five lines per pool           rotated, so none can land twice in a night

Outside League only the clock applies, which is what a non-League stream is.
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
    """Deterministic: midpoint of any range, and a dial for the coin flips."""

    def __init__(self, coin: float = 0.99):
        self.coin = coin

    def uniform(self, low, high):
        return (low + high) / 2.0

    def random(self):
        return self.coin


def source(games: int = 0, league: bool = True, coin: float = 0.99,
           temper: Temper | None = None) -> PromoSource:
    Settings.LEAGUE_MODE = league
    promo_module.random = FakeRandom(coin)

    temper = temper or Temper()
    for _ in range(games):
        temper.record_game(GameResult(won=True, kills=3, deaths=3, assists=3))

    return PromoSource(SignalQueue(), DATA, temper=temper)


def restore() -> None:
    import random
    promo_module.random = random
    Settings.LEAGUE_MODE = True


# ===================================================================== timing
def test_the_interval():
    print("\n--- once every 40-80 minutes ---")
    p = source()
    import time
    wait = p._due - time.time()

    check("the first one is inside the range",
          S.PROMO_MIN_INTERVAL <= wait + 1 <= S.PROMO_MAX_INTERVAL,
          f"{wait / 60:.0f} min")
    check("the range is the streamer's 40 to 80 minutes",
          (S.PROMO_MIN_INTERVAL, S.PROMO_MAX_INTERVAL) == (2400.0, 4800.0),
          f"{S.PROMO_MIN_INTERVAL}-{S.PROMO_MAX_INTERVAL}")
    check("and it is rolled, not fixed",
          "uniform" in promo_module.PromoSource._interval.__code__.co_names)

    check("she is not due at startup", p._blocked(p._due - 60) == "")
    restore()


def test_firing_resets_the_clock():
    print("\n--- and the clock starts again ---")
    import time
    p = source(games=4)
    p._games_seen = 4

    before = p._due
    signal = p.fire(FOLLOW)
    check("something was queued", signal is not None and p.queue.pop() is not None)
    check("the next one is a fresh interval away", p._due > before,
          f"{(p._due - time.time()) / 60:.0f} min")
    check("and the game count is remembered, for the every-2nd-game rule",
          p._games_at_last_promo == 4)
    restore()


# ====================================================================== gates
def test_not_during_a_game():
    print("\n--- never while he is playing ---")
    import time
    p = source()
    p._due = time.time() - 1          # due now
    p.game_active = True

    check("a live game holds it", "game is running" in p._blocked(time.time()),
          p._blocked(time.time()))

    p.game_active = False
    p._last_game_end = 0.0
    check("and once the game is gone it may speak",
          p._blocked(time.time()) == "", p._blocked(time.time()))
    restore()


def test_the_wait_after_a_game():
    print("\n--- 1-3 minutes after one ends ---")
    import time
    p = source()
    p._due = time.time() - 1
    now = time.time()

    p._last_game_end = now - 10
    p._after_game_wait = 120.0
    check("ten seconds after a loss is too soon",
          "since the game ended" in p._blocked(now), p._blocked(now))

    p._last_game_end = now - 130
    check("two minutes later is fine", p._blocked(now) == "", p._blocked(now))

    check("the wait is inside the streamer's one-to-three minutes",
          S.PROMO_AFTER_GAME_MIN <= p._post_game_delay()
          <= S.PROMO_AFTER_GAME_MAX)
    check("and it is rolled per game, not fixed once",
          "uniform" in
          promo_module.PromoSource._post_game_delay.__code__.co_names)
    restore()


def test_every_second_game():
    print("\n--- games are short, so not after every one ---")
    import time
    p = source()
    p._due = time.time() - 1
    p._last_game_end = time.time() - 600        # long past the wait
    p._games_seen = 3
    p._games_at_last_promo = 2

    check("one game since the last promo is not enough",
          "game(s) since" in p._blocked(time.time()), p._blocked(time.time()))

    p._games_seen = 4
    check("two games is", p._blocked(time.time()) == "",
          p._blocked(time.time()))
    check("the gap is the streamer's every-2nd-game", S.PROMO_GAMES_GAP == 2)
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

    check("no game gates at all", p._blocked(time.time()) == "",
          p._blocked(time.time()))
    check("and she never wonders about game four",
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

    # coin=0.99 is above PROMO_END_WONDER_CHANCE, so the wondering is refused
    p._games_seen = 4
    check("after four games it may still ask normally",
          p._pool() in (FOLLOW, SUBSCRIBE))

    eager = source(coin=0.0)
    eager._games_seen = 4
    check("and may wonder about the end instead",
          eager._pool() == END_WONDER)

    eager._games_seen = 3
    check("but not before there have been enough games",
          eager._pool() in (FOLLOW, SUBSCRIBE))
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
    test_the_interval()
    test_firing_resets_the_clock()
    test_not_during_a_game()
    test_the_wait_after_a_game()
    test_every_second_game()
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
