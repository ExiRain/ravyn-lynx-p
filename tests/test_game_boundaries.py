"""
Nothing from one game leaks into the next.

    python tests/test_game_boundaries.py

LolGameSource is one class holding a whole game's state across ~40 methods,
and it is reset by hand: __init__ sets every field, and _check_for_game sets
the per-game ones again when a new game starts. A field added to one and
forgotten in the other carries the last game into this one — a death count,
a kill buffer, a "she just spoke" timestamp — and nothing would say so.

So instead of listing fields, this plays a whole game, starts the next one,
and compares the source with a brand-new one that only ever saw the second
game. Any difference is a leak. Only things meant to last the whole stream
(her temper, who he is, the quote pools, which angles she has already used)
are excused, by name.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_identity import real_game, DATA                  # noqa: E402

import sources.lol_game as lol                             # noqa: E402
from orchestrator.priority_queue import SignalQueue        # noqa: E402
from orchestrator.temper import Temper                     # noqa: E402

FAILURES: list[str] = []

# Meant to outlive a game. Anything else that differs is a leak.
STREAM_LONG = {"temper", "_unhandled_logged", "queue", "identity", "client",
               "notes", "_quotes", "on_active_change", "_fetch", "angles"}

ME = "Серый Экран#RU"
A_GAME = [
    {"EventName": "ChampionKill", "KillerName": ME, "VictimName": "darius#RU",
     "Assisters": []},
    {"EventName": "ChampionKill", "KillerName": "darius#RU", "VictimName": ME,
     "Assisters": []},
    {"EventName": "ChampionKill", "KillerName": "darius#RU",
     "VictimName": "jinx#RU", "Assisters": []},
    {"EventName": "Multikill", "KillerName": ME, "KillStreak": 2},
    {"EventName": "DragonKill", "DragonType": "Fire", "KillerName": "leesin#RU"},
    {"EventName": "HeraldKill", "KillerName": "elise#RU"},
    {"EventName": "BaronKill", "KillerName": "elise#RU", "Assisters": []},
    {"EventName": "TurretKilled", "TurretKilled": "Turret_T2_L_03_A",
     "KillerName": ME},
    {"EventName": "InhibKilled", "InhibKilled": "Barracks_T1_L1",
     "KillerName": ""},
    {"EventName": "Ace", "AcingTeam": "CHAOS"},
]


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def snapshot(src) -> dict:
    """Every field, one level into the objects it owns (state, angles...)."""
    out = {}
    for key, value in vars(src).items():
        if key in STREAM_LONG:
            continue
        if hasattr(value, "__dict__") and not callable(value):
            for sub, v in vars(value).items():
                out[f"{key}.{sub}"] = repr(v)
        else:
            out[key] = repr(value)
    return out


def start(src, t):
    src._fetch = lambda: real_game(t=t)
    src._check_for_game()
    src._poll_game()


def main():
    print("\n--- a whole game, then the next: same as starting fresh ---")
    real_random = lol.random.random
    lol.random.random = lambda: 0.0        # every chance roll says yes
    try:
        played = lol.LolGameSource(SignalQueue(), DATA, temper=Temper())
        played.queue.push = lambda s: None
        start(played, 1500.0)
        for i, event in enumerate(A_GAME):
            played._handle_event(dict(event, EventTime=1500 + i), real_game())
        if played._kill_buffer:
            played._flush_kills()
        check("(the game really happened: deaths and drakes were counted)",
              played._death_count == 1 and played.state.theirs.dragons == []
              and len(played.state.ours.dragons) == 1)
        played._handle_event({"EventName": "GameEnd", "Result": "Lose"},
                             real_game())
        played._fetch = lambda: None
        for _ in range(lol.GONE_AFTER_MISSES):
            played._check_for_game()
        start(played, 10.0)

        fresh = lol.LolGameSource(SignalQueue(), DATA, temper=Temper())
        fresh.queue.push = lambda s: None
        start(fresh, 10.0)
    finally:
        lol.random.random = real_random

    a, b = snapshot(played), snapshot(fresh)
    leaks = [f"{k}: {a.get(k, '<missing>')[:60]} vs fresh "
             f"{b.get(k, '<missing>')[:60]}"
             for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    check("game two starts exactly like a fresh source", not leaks,
          "; ".join(leaks[:5]))
    check("and her temper DID carry the lost game (stream-long, on purpose)",
          len(played.temper.games) == 1 and fresh.temper.games == [])
    check("and so did the angles she used, so game two does not open the same",
          len(played.angles._used) > len(fresh.angles._used))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
