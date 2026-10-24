"""
What kind of company she is tonight.

    python tests/test_temper.py

`tone.py` decides how hard she goes on this death. Temper decides the register
she is in across the whole evening, and the streamer wrote it down as three
things:

    SUPPORTIVE   "YOU CAN DO THIS! I BELIEVE IN YOU"
    NEUTRAL      what she has always been
    NEGATIVE     "STOP FEEDING, you playing like my grandpa"

Two properties this holds, and they are the reason it exists rather than being
a fourth knob on the tone ladder:

**A register is not an intensity.** Supportive is not "mildly sarcastic" — it
is on his side out loud. So each register carries its own instruction, and the
ladder is clamped underneath it: she cannot roast while supportive whatever
the ninth death says.

**Harder does not mean more often.** A measured session ran 79% of her lines
aimed at him, fifteen in a row. That is what a losing night produces when
every input pushes one way and nothing bounds the total — so NEGATIVE sharpens
and speaks LESS, and no temper gets more than three pointed lines running.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import tone as tone_engine                       # noqa: E402
from orchestrator.temper import (                                  # noqa: E402
    MAX_HARSH_STREAK, NEGATIVE, NEUTRAL, REGISTER_INSTRUCTION, REGISTERS,
    SUPPORTIVE, GameResult, Temper,
)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _toll(games: int) -> float:
    """The session toll alone, for a given number of games."""
    t = Temper()
    for _ in range(games):
        t.record_game(GameResult(won=True, kills=3, deaths=3, assists=3))
    return abs(sum(g.points() for g in t.games) - t.points())


def won(k=8, d=2, a=4) -> GameResult:
    return GameResult(won=True, kills=k, deaths=d, assists=a, minutes=30)


def lost(k=1, d=9, a=1) -> GameResult:
    return GameResult(won=False, kills=k, deaths=d, assists=a, minutes=30)


# ================================================================== the three
def test_three_registers():
    print("\n--- three, starting level ---")
    check("exactly three", len(REGISTERS) == 3, str(REGISTERS))
    check("one instruction each",
          all(r in REGISTER_INSTRUCTION for r in REGISTERS))
    check("a fresh session is neutral", Temper().register() == NEUTRAL)

    supportive = REGISTER_INSTRUCTION[SUPPORTIVE].lower()
    negative = REGISTER_INSTRUCTION[NEGATIVE].lower()
    check("supportive actually encourages rather than softening a jab",
          "encourage" in supportive and "no barb" in supportive)
    check("negative is short and out of patience, not contemptuous",
          "patience" in negative and "never contempt" in negative)


def test_what_moves_it():
    print("\n--- what moves the needle ---")
    good = Temper()
    good.record_game(won())
    good.record_game(won())
    check("two good wins make her supportive",
          good.register() == SUPPORTIVE, good.register())

    bad = Temper()
    bad.record_game(lost())
    bad.record_game(lost())
    check("two bad losses make her negative",
          bad.register() == NEGATIVE, bad.register())

    mixed = Temper()
    mixed.record_game(won())
    mixed.record_game(lost())
    check("a win and a loss cancel out to level",
          mixed.register() == NEUTRAL,
          f"{mixed.register()} at {mixed.points():+.1f}")

    carried = Temper()
    carried.record_game(GameResult(won=False, kills=9, deaths=2, assists=3))
    check("carrying a loss is not the same as being carried through a win",
          carried.points() > lost().points(), f"{carried.points():+.1f}")

    # The streamer asked for this one explicitly: the number of games tolls.
    grind = Temper()
    for _ in range(8):
        grind.record_game(GameResult(won=True, kills=3, deaths=3, assists=3))
    raw = sum(g.points() for g in grind.games)
    check("eight games take a visible toll even when winning",
          grind.points() < raw - 8, f"{grind.points():+.1f} vs raw {raw:+.1f}")
    check("and the toll is progressive, not flat",
          _toll(6) > 2 * _toll(3), f"{_toll(6):.1f} vs {_toll(3):.1f}")

    check("points are bounded, so one bad game can always move her",
          abs(grind.points()) <= 10.0, f"{grind.points():+.1f}")

    # And a long sitting with no game at all, which is a non-league stream.
    import time
    idle = Temper(started_at=time.time() - 6 * 3600)
    check("six hours with no games drifts off neutral",
          idle.register() == NEGATIVE, f"{idle.points():+.1f}")
    check("and an hour does not",
          Temper(started_at=time.time() - 3600).register() == NEUTRAL)


def test_a_session_can_be_reset():
    print("\n--- SET TIME and RESET SESSION ---")
    t = Temper()
    for _ in range(3):
        t.record_game(lost())
    check("three losses in", t.register() == NEGATIVE)

    t.reset_games()
    check("resetting the games clears the grievance",
          t.register() == NEUTRAL and t.games == [])

    t.record_game(lost())
    t.start_session()
    check("starting a session clears everything",
          t.games == [] and t.nudge == 0.0 and t.register() == NEUTRAL)

    nudged = Temper(nudge=-5.0)
    check("and there is a hand on the dial for the streamer",
          nudged.register() == NEGATIVE)


# ================================================================ the clamping
def test_supportive_cannot_roast():
    print("\n--- a register is not an intensity ---")
    t = Temper()
    t.record_game(won())
    t.record_game(won())
    check("supportive, after two good games", t.register() == SUPPORTIVE)

    check("a roast is refused outright", t.clamp("roast") == "dry",
          t.clamp("roast"))
    check("so is sharp", t.clamp("sharp") == "dry")
    check("warm is left alone", t.clamp("warm") == "warm")
    check("light is left alone", t.clamp("light") == "light")

    hard = Temper()
    hard.record_game(lost())
    hard.record_game(lost())
    check("negative, after two bad games", hard.register() == NEGATIVE)
    check("negative may roast", hard.clamp("roast") == "roast")
    check("but does not gush over one good play",
          hard.clamp("warm") == "light", hard.clamp("warm"))

    level = Temper()
    for tone in tone_engine.TONES:
        check(f"neutral leaves {tone} exactly as the rulebook chose it",
              level.clamp(tone) == tone)

    check("something that is not a tone passes through untouched",
          level.clamp("nonsense") == "nonsense")


def test_the_streak_is_bounded():
    print("\n--- fifteen in a row is what this exists to stop ---")
    t = Temper()
    t.record_game(lost())
    t.record_game(lost())

    allowed = [t.allow_harsh("roast") for _ in range(MAX_HARSH_STREAK + 1)]
    check(f"{MAX_HARSH_STREAK} pointed lines run, the next does not",
          allowed[:MAX_HARSH_STREAK] == [True] * MAX_HARSH_STREAK
          and allowed[-1] is False, str(allowed))

    check("and the softened one steps the ladder down",
          t.soften("roast") == "sharp" and t.soften("sharp") == "dry")
    check("stepping down off the bottom stays put",
          t.soften("warm") == "warm")

    fresh = Temper()
    fresh.record_game(lost())
    fresh.record_game(lost())
    fresh.allow_harsh("roast")
    fresh.allow_harsh("roast")
    check("a warm line in between resets the count",
          fresh.allow_harsh("warm") and fresh.allow_harsh("roast")
          and fresh.allow_harsh("roast") and fresh.allow_harsh("roast"))


def test_harder_means_less_often():
    print("\n--- harder temper, fewer lines ---")
    level = Temper()
    check("neutral says as much as it always did",
          level.heat_factor() == 1.0)

    hard = Temper()
    hard.record_game(lost())
    hard.record_game(lost())
    check("negative speaks LESS, not more", hard.heat_factor() < 1.0,
          str(hard.heat_factor()))

    soft = Temper()
    soft.record_game(won())
    soft.record_game(won())
    check("supportive is not rationed", soft.heat_factor() == 1.0)


def test_state_is_loggable():
    print("\n--- what the log records ---")
    t = Temper()
    t.record_game(won())
    state = t.state()
    for key in ("temper", "temper_points", "games", "session_hours"):
        check(f"state carries {key}", key in state, str(state))
    check("the register is one of the three", state["temper"] in REGISTERS)
    check("games are counted", state["games"] == 1)

    instruction = t.instruction()
    check("the instruction matches the register",
          instruction == REGISTER_INSTRUCTION[state["temper"]])


def test_kda_is_honest():
    print("\n--- KDA, including the perfect game ---")
    check("a deathless game is good, not infinite",
          GameResult(won=True, kills=5, deaths=0, assists=0).kda == 5.0)
    check("assists count for half",
          GameResult(won=True, kills=0, deaths=1, assists=4).kda == 2.0)
    check("a nine-death game is bad",
          GameResult(won=False, kills=1, deaths=9, assists=1).kda < 0.6)
    check("a summary reads as a scoreline",
          "W 8/2/4" in won().summary(), won().summary())


def main() -> int:
    test_three_registers()
    test_what_moves_it()
    test_a_session_can_be_reset()
    test_supportive_cannot_roast()
    test_the_streak_is_bounded()
    test_harder_means_less_often()
    test_state_is_loggable()
    test_kda_is_honest()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
