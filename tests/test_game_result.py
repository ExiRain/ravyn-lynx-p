"""
Who won, and what temper does with it.

    python tests/test_game_result.py

On 2026-10-25 15:06 none of three games delivered a GameEnd event, so all three
were recorded with no result, scored no win or loss points, and temper sat at
neutral all night (peak 2.43 of the 2.5 needed). And even a moving temper was
drowned out: her teammate vocabulary escalated on his deaths alone and rode
along with every event, so "piggies" came back 34 times in one session.
"""

import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

requests = types.ModuleType("requests")
requests.ConnectionError = type("ConnectionError", (Exception,), {})
requests.Timeout = type("Timeout", (Exception,), {})
requests.get = lambda *a, **k: None
sys.modules["requests"] = requests

urllib3 = types.ModuleType("urllib3")
urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
urllib3.disable_warnings = lambda *a, **k: None
sys.modules["urllib3"] = urllib3

from orchestrator import league_client                     # noqa: E402
from orchestrator.priority_queue import SignalQueue        # noqa: E402
from orchestrator.temper import (GameResult, Temper,       # noqa: E402
                                 NEGATIVE, NEUTRAL, SUPPORTIVE)
from sources.lol_game import LolGameSource                 # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def block(game_id, won):
    return {"gameId": game_id,
            "teams": [{"isPlayerTeam": False, "isWinningTeam": not won},
                      {"isPlayerTeam": True, "isWinningTeam": won}]}


# ================================================================ the parser
def test_reading_the_block():
    print("\n--- reading the client's end-of-game block ---")
    r = league_client.result
    check("his team won", r(block(1, True)) is True)
    check("his team lost", r(block(1, False)) is False)
    check("localPlayer WIN when there are no teams",
          r({"localPlayer": {"stats": {"WIN": 1}}}) is True)
    check("localPlayer LOSE when there are no teams",
          r({"localPlayer": {"stats": {"LOSE": 1}}}) is False)
    check("a block that does not say is unknown, not a guess",
          r({"gameId": 3, "teams": [{"isWinningTeam": True}]}) is None)
    check("nothing is unknown", r(None) is None and r({}) is None)

    missing = league_client.LeagueClient("/no/such/lockfile")
    check("no lockfile is survivable", missing.eog() is None)


# ============================================ filling in a missed result
class FakeClient:
    def __init__(self):
        self.answers: list = []

    def eog(self):
        return self.answers.pop(0) if self.answers else None

    def game_id(self):
        return 100      # the previous game's block, there at game start


def ended_without_gameend(temper: Temper) -> LolGameSource:
    """A game recorded the way the 15:06 games were: no result."""
    src = LolGameSource(SignalQueue(), DATA, temper=temper)
    src.client = FakeClient()
    src._eog_before = src.client.game_id()
    src._record_game(None)
    src._result_wanted_until = time.time() + 60
    return src


def test_a_missed_result_is_filled_in():
    print("\n--- the client fills in what GameEnd never said ---")
    temper = Temper()
    src = ended_without_gameend(temper)

    src.client.answers = [None]                 # not posted yet
    src._maybe_resolve_result()
    check("still waiting while the client has nothing",
          temper.games[-1].won is None and src._result_wanted_until > 0)

    src.client.answers = [block(100, False)]    # the PREVIOUS game's block
    src._maybe_resolve_result()
    check("the previous game's block is never taken for this one",
          temper.games[-1].won is None)

    src.client.answers = [block(101, True)]
    src._maybe_resolve_result()
    check("this game's block resolves it", temper.games[-1].won is True)
    check("and asking stops", src._result_wanted_until == 0.0)

    temper = Temper()
    src = ended_without_gameend(temper)
    src._result_wanted_until = time.time() - 1
    src._maybe_resolve_result()
    check("past the wait it stays unknown rather than guessed",
          temper.games[-1].won is None and src._result_wanted_until == 0.0)


def test_results_move_her_temper():
    print("\n--- with results, temper does what it was built to ---")
    ok = dict(kills=3, deaths=4, assists=2, minutes=30)    # KDA 1.0: plain

    t = Temper()
    for _ in range(3):
        t.record_game(GameResult(won=None, **ok))
    check("three games with no result: stuck at neutral, as on 15:06",
          t.register() == NEUTRAL, t.register())
    for _ in range(3):
        t.games[[g.won for g in t.games].index(None)].won = True
    check("the same three games, won: supportive", t.register() == SUPPORTIVE,
          t.register())

    t = Temper()
    t.record_game(GameResult(won=None, kills=1, deaths=9, assists=2))
    check("resolve_last fills in the latest unknown", t.resolve_last(False))
    check("a bad loss turns her harsh", t.register() == NEGATIVE, t.register())
    check("and a known result is never overwritten",
          not t.resolve_last(True) and t.games[-1].won is False)


# =========================================================== teammate words
def test_teammate_words_follow_temper():
    print("\n--- what she calls his team follows her temper ---")
    import sources.lol_game as lol

    def words_for(register_points: float, config_key: str, deaths: int):
        temper = Temper()
        temper.nudge = register_points
        src = LolGameSource(SignalQueue(), DATA, temper=temper)
        src._death_count = deaths
        src._current_game_time = 600.0
        pushed = []
        src.queue.push = lambda sig: pushed.append(sig)
        original = lol.random.random
        lol.random.random = lambda: 0.0
        try:
            src._push_event(config_key, "x", {}, config_key)
        finally:
            lol.random.random = original
        return pushed[0].context if pushed else {}

    many = 9    # deaths: the death count alone would ask for rank 4

    ctx = words_for(+5, "AllyDeath", many)
    check("supportive: no words for his team at all",
          "teammate_words" not in ctx, str(ctx.get("teammate_words")))

    ctx = words_for(0, "AllyDeath", many)
    check("neutral: capped at rank 2, however many deaths",
          ctx.get("teammate_rank") == 2, str(ctx.get("teammate_rank")))

    ctx = words_for(-5, "AllyDeath", many)
    check("negative: the full escalation", ctx.get("teammate_rank") == 4,
          str(ctx.get("teammate_rank")))

    ctx = words_for(-5, "DragonKill", many)
    check("never on events that are not about his team",
          "teammate_words" not in ctx, str(ctx.get("teammate_words")))


def main():
    test_reading_the_block()
    test_a_missed_result_is_filled_in()
    test_results_move_her_temper()
    test_teammate_words_follow_temper()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
