"""
Game commentary variety — the properties that stop her repeating herself.

The complaint this exists to prevent: three games in a row where the second one
sounded like the first, because fifteen ally deaths produced fifteen prompts
that differed only in a seed drawn from five strings. See STATUS.md §7.

    python tests/test_game_variety.py

What is actually being protected:

  1. The measured state reaches the prompt at all. It used to be collected
     every two seconds and discarded.
  2. Consecutive events of the same type get different angles.
  3. An angle never fires on facts that are not true — no invented reads.
  4. Bursts decay, so one teamfight is one comment and not four.
  5. Unknown values are omitted, never guessed or defaulted into a claim.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# lol_game pulls in the HTTP stack it does not need for policy tests
requests = types.ModuleType("requests")
requests.ConnectionError = type("ConnectionError", (Exception,), {})
requests.Timeout = type("Timeout", (Exception,), {})
requests.get = lambda *a, **k: None
sys.modules["requests"] = requests

urllib3 = types.ModuleType("urllib3")
urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
urllib3.disable_warnings = lambda *a, **k: None
sys.modules["urllib3"] = urllib3

from app.settings import get_settings                       # noqa: E402
from orchestrator.game_angles import (                        # noqa: E402
    ANGLES, MIN_UNCONDITIONAL, AngleChooser, _always,
)
from orchestrator.game_state import GameState                # noqa: E402
from orchestrator.priority_queue import SignalQueue           # noqa: E402
from orchestrator import game_theme, tone                     # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def snapshot(game_time=600.0, my_cs=60, my_kills=2, my_deaths=1,
             enemy_cs=50, position="", spell="Flash"):
    """One allgamedata poll, shaped like the Live Client API returns it."""
    me = {
        "championName": "Riven", "summonerName": "exiled",
        "riotId": "exiled#EUW", "team": "ORDER", "level": 9,
        "position": position,
        "summonerSpells": {"summonerSpellOne": {
            "displayName": spell,
            "rawDisplayName":
                f"GeneratedTip_SummonerSpell_Summoner{spell}_DisplayName"}},
        "scores": {"kills": my_kills, "deaths": my_deaths, "assists": 3,
                   "creepScore": my_cs, "wardScore": 7.0},
    }
    others = [
        {"championName": c, "summonerName": f"p{i}", "riotId": f"p{i}#EUW",
         "team": team, "level": 9, "position": "", "summonerSpells": {},
         "scores": {"kills": 1, "deaths": 1, "assists": 1,
                    "creepScore": enemy_cs, "wardScore": 3.0}}
        for i, (c, team) in enumerate([
            ("LeeSin", "ORDER"), ("Orianna", "ORDER"),
            ("Jinx", "ORDER"), ("Thresh", "ORDER"),
            ("Darius", "CHAOS"), ("Elise", "CHAOS"), ("Syndra", "CHAOS"),
            ("Caitlyn", "CHAOS"), ("Nautilus", "CHAOS")])
    ]
    return {"gameData": {"gameTime": game_time},
            "allPlayers": [me] + others,
            "events": {"Events": []}}


MY_NAMES = {"exiled", "exiled#euw", "riven"}


# ============================================================ measured state
def test_state():
    print("\n--- measured state ---")
    s = GameState()
    s.update(snapshot(game_time=1200.0, my_cs=140, my_kills=6, my_deaths=2,
                      enemy_cs=90), "ORDER", MY_NAMES)

    check("champion resolved", s.champion == "Riven", s.champion)
    check("KDA resolved", s.kda_line == "6/2/3", s.kda_line)
    check("CS per minute computed", abs(s.cs_per_min - 7.0) < 0.01,
          f"{s.cs_per_min}")
    check("CS rank is over all ten players", s.cs_rank == 1, str(s.cs_rank))
    check("team kills counted from the scoreboard", s.ours.kills == 10,
          str(s.ours.kills))
    check("enemy champions collected", len(s.enemy_champions) == 5,
          str(s.enemy_champions))
    check("phase from game time", s.phase == "mid", s.phase)

    rendered = s.render()
    check("situation reaches the prompt", "Riven" in rendered and "7.0/min" in rendered)
    check("situation forbids inventing beyond it",
          "Do not state anything about the game beyond them" in rendered)

    # Unknowns are omitted, never guessed. This is the §7 rule in code.
    empty = GameState().render()
    check("an empty state renders nothing at all", empty == "", repr(empty[:40]))

    fresh = GameState()
    fresh.update(snapshot(game_time=60.0), "ORDER", MY_NAMES)
    check("no drake line before any drake is taken",
          "Drakes" not in fresh.render())
    check("no baron line before any baron", "Baron" not in fresh.render())


def test_role_detection():
    print("\n--- role, best effort and never guessed ---")
    s = GameState()
    s.update(snapshot(position="MIDDLE"), "ORDER", MY_NAMES)
    check("position wins when the API fills it in", s.position == "middle",
          s.position)

    s = GameState()
    s.update(snapshot(position="", spell="Smite"), "ORDER", MY_NAMES)
    check("smite identifies jungle when position is empty",
          s.position == "jungle", s.position)

    s = GameState()
    s.update(snapshot(position="", spell="Flash"), "ORDER", MY_NAMES)
    check("no smite and no position leaves role unknown", s.position == "",
          s.position)
    check("unknown role is omitted from the situation",
          "Riven," in s.render() and "Riven unknown" not in s.render())

    # The RU client localises displayName; the raw key still carries the name.
    s = GameState()
    snap = snapshot(position="")
    snap["allPlayers"][0]["summonerSpells"] = {"summonerSpellOne": {
        "displayName": "Кара",
        "rawDisplayName":
            "GeneratedTip_SummonerSpell_SummonerSmite_DisplayName"}}
    s.update(snap, "ORDER", MY_NAMES)
    check("localised spell names still resolve via the raw key",
          s.position == "jungle", s.position)


def test_dragons_and_mood():
    print("\n--- drakes, soul and mood ---")
    s = GameState()
    s.update(snapshot(), "ORDER", MY_NAMES)

    for _ in range(3):
        s.record_dragon("enemy", "Infernal")
    check("soul point detected for them", s.soul_point == "theirs",
          s.soul_point)
    check("soul point appears in the situation",
          "one more and they take soul" in s.render())

    s.record_dragon("enemy", "Infernal")
    check("soul taken detected", s.soul_taken == "theirs", s.soul_taken)
    check("soul point clears once soul is taken", s.soul_point == "")

    even = GameState()
    even.update(snapshot(game_time=300.0, my_kills=1, my_deaths=1),
                "ORDER", MY_NAMES)
    check("an even early game reads as neutral mood",
          abs(even.mood()) < 0.25, f"{even.mood()}")

    losing = GameState()
    losing.update(snapshot(game_time=1500.0, my_kills=2, my_deaths=8),
                  "ORDER", MY_NAMES)
    losing.theirs.dragons = ["a", "b", "c"]
    losing.theirs.turrets = 7
    check("a game going badly reads negative", losing.mood() < -0.4,
          f"{losing.mood()}")

    winning = GameState()
    winning.update(snapshot(game_time=1200.0, my_kills=9, my_deaths=1),
                   "ORDER", MY_NAMES)
    winning.ours.dragons = ["a", "b", "c"]
    winning.ours.turrets = 6
    check("a game going well reads positive", winning.mood() > 0.4,
          f"{winning.mood()}")

    check("mood stays inside [-1, 1]",
          all(-1.0 <= g.mood() <= 1.0 for g in (even, losing, winning)))


# ==================================================================== angles
def test_angle_variety():
    print("\n--- angle variety ---")

    # A game that actually moves: kills swing, drakes stack, minutes pass.
    chooser = AngleChooser()
    picked = []
    for i in range(12):
        state = GameState()
        state.update(snapshot(game_time=300.0 + i * 150,
                              my_kills=i // 2, my_deaths=i // 3),
                     "ORDER", MY_NAMES)
        state.theirs.dragons = ["x"] * min(3, i // 4)
        state.theirs.kills += i
        angle = chooser.choose("AllyDeath", state,
                               {"recent_ally_deaths": i % 3,
                                "victim_deaths": i % 4})
        picked.append(angle.id)

    check("twelve ally deaths in a moving game use many angles",
          len(set(picked)) >= 6, f"{len(set(picked))}: {sorted(set(picked))}")
    check("never the same angle twice in a row",
          all(a != b for a, b in zip(picked, picked[1:])), str(picked))


def test_flat_game_still_varies():
    """
    The floor case, and the one that used to break.

    In a dead-even game almost no situational angle is true, so the list falls
    back to whatever is unconditional. With a single unconditional angle that
    meant the same instruction back to back — exactly the repetition this
    module exists to remove — which is why MIN_UNCONDITIONAL is enforced.
    """
    print("\n--- a flat game still varies ---")

    flat = GameState()
    flat.update(snapshot(game_time=720.0, my_kills=1, my_deaths=1),
                "ORDER", MY_NAMES)

    for event_type in ANGLES:
        chooser = AngleChooser()
        picked = [chooser.choose(event_type, flat, {}).id for _ in range(6)]
        check(f"{event_type}: no back-to-back repeat with nothing going on",
              all(a != b for a, b in zip(picked, picked[1:])), str(picked))

    unconditional = {
        event_type: sum(1 for a in angles if a.when is _always)
        for event_type, angles in ANGLES.items()
    }
    short = {k: v for k, v in unconditional.items() if v < MIN_UNCONDITIONAL}
    check(f"every event type has at least {MIN_UNCONDITIONAL} "
          f"always-eligible angles", not short, str(short))


def test_angles_only_fire_on_true_facts():
    print("\n--- angles never invent facts ---")
    # A brand new game: no drakes, no kills, nothing measured.
    blank = GameState()
    blank.update(snapshot(game_time=60.0, my_kills=0, my_deaths=0),
                 "ORDER", MY_NAMES)

    chooser = AngleChooser()
    for _ in range(6):
        angle = chooser.choose("DragonKill", blank, {"side": "mine"})
        check(f"no soul angle with zero drakes ({angle.id})",
              "soul" not in angle.id, angle.id)

    # Every angle in every list must survive an empty state without raising.
    empty = GameState()
    survived = True
    for event_type in ANGLES:
        c = AngleChooser()
        for _ in range(3):
            try:
                c.choose(event_type, empty, {})
            except Exception as e:
                survived = False
                print(f"      {event_type} raised: {e}")
    check("every angle list is safe against an empty state", survived)

    check("an unknown event type returns no angle",
          AngleChooser().choose("NotAnEvent", blank, {}) is None)


def test_burst_decay():
    print("\n--- burst decay ---")
    from sources.lol_game import LolGameSource

    source = LolGameSource.__new__(LolGameSource)
    source._reaction_log = {}
    source._current_game_time = 600.0

    base = S.REACTION_CHANCE["AllyDeath"]
    chances = []
    for _ in range(4):
        chances.append(source._reaction_chance("AllyDeath", "AllyDeath"))
        source._reaction_log.setdefault("AllyDeath", []).append(600.0)

    check("the first reaction is at the base rate",
          abs(chances[0] - base) < 1e-9, str(chances))
    check("each repeat inside the window is less likely",
          all(a > b for a, b in zip(chances, chances[1:])),
          str([round(c, 3) for c in chances]))
    check("a burst of four collapses hard", chances[3] < base * 0.25,
          f"{chances[3]:.3f} vs base {base}")

    # A different event type is unaffected by the ally-death burst.
    check("decay is per event type",
          abs(source._reaction_chance("DragonKill", "DragonKill")
              - S.REACTION_CHANCE["DragonKill"]) < 1e-9)

    # And it decays: the same event much later is back to full rate.
    source._current_game_time = 600.0 + S.REACTION_WINDOW + 1
    check("the counter decays out of the window",
          abs(source._reaction_chance("AllyDeath", "AllyDeath") - base) < 1e-9)


def test_global_gap():
    """
    A floor under the gap between ANY two game comments.

    Per-type decay stops her repeating a KIND of remark, but five different
    event types landing inside one teamfight still had her narrating without a
    break — she finishes a line, the next queued event goes straight out. The
    live session was terminated over exactly this.
    """
    print("\n--- the global gap between comments ---")
    from sources.lol_game import LolGameSource

    source = LolGameSource.__new__(LolGameSource)
    source._reaction_log = {}
    source._last_game_comment = 0.0
    source._current_game_time = 600.0
    source.state = GameState()
    source.angles = AngleChooser()
    source._read = None
    source._player_summoner = "exiled"
    source._player_champion = "Riven"
    source.theme = game_theme.NO_THEME
    source.tones = tone.ToneLadder()
    pushed = []
    source.queue = types.SimpleNamespace(push=pushed.append)

    import sources.lol_game as lol
    original = lol.random.random
    lol.random.random = lambda: 0.0     # isolate the gap from the dice
    try:
        # Five different event types, all inside one fight.
        for offset, (kind, event) in enumerate([
                ("AllyDeath", "AllyDeath"), ("AllyKill", "AllyKill"),
                ("DragonKill", "DragonKill"), ("TurretKilled", "TurretKilled"),
                ("AllyDeath", "AllyDeath")]):
            source._current_game_time = 600.0 + offset * 4
            source._push_event(kind, f"event {offset}", {}, event)

        check("one teamfight produces one comment, not five",
              len(pushed) == 1, f"{len(pushed)}")

        # Well after the gap, she speaks again.
        source._current_game_time = 600.0 + S.GAME_MIN_GAP + 5
        source._push_event("AllyDeath", "much later", {}, "AllyDeath")
        check("she speaks again once the gap has passed", len(pushed) == 2,
              f"{len(pushed)}")

        # A sub-priority moment cuts through it.
        source._current_game_time += 1
        source._push_event("GameEnd", "game over", {}, "GameEnd")
        check("high-priority events ignore the gap", len(pushed) == 3,
              f"{len(pushed)}")
    finally:
        lol.random.random = original


def test_cheer_and_boo():
    """
    The end-of-game noise.

    Deliberately outside every rationing mechanism in the file: a game ends
    once, so there is nothing for it to be repetitive against, and the moment
    it lands is the moment it matters. It is a quote rather than a prompt so
    the sound arrives while the screen is still grey instead of after an LLM
    round trip and a synthesis.
    """
    print("\n--- the cheer and the boo ---")
    from pathlib import Path
    from sources.lol_game import LolGameSource

    data = Path(__file__).resolve().parent.parent / "data"

    for won, label in ((True, "win"), (False, "loss")):
        queue = SignalQueue()
        source = LolGameSource(queue, data)
        source._player_summoner, source._player_champion = "exiled", "Riven"
        source._current_game_time = 2100.0
        source._last_game_comment = source._current_game_time   # gap wide open
        source._handle_event({"EventName": "GameEnd",
                              "Result": "Win" if won else "Lose"}, {})

        first = queue.pop()
        second = queue.pop()

        check(f"{label}: the noise comes first",
              first is not None and first.priority == S.CHEER_PRIORITY,
              str(first.priority) if first else "nothing queued")
        check(f"{label}: it is the top priority in the system",
              first.priority == 1 and first.priority < S.OWNER_PRIORITY)
        check(f"{label}: it skips the LLM entirely",
              first.skip_llm and first.mode == "quote")
        check(f"{label}: the voice gate cannot hold it",
              first.priority <= S.VOICE_INTERRUPT_PRIORITY)
        check(f"{label}: her face is already doing it",
              (first.context["mood_spike"] > 0) is won,
              str(first.context["mood_spike"]))
        check(f"{label}: it expires rather than arriving late",
              first.ttl == S.CHEER_TTL, str(first.ttl))
        check(f"{label}: the event type says which it was",
              first.context["event_type"] == ("GameCheer" if won else "GameBoo"),
              first.context["event_type"])

        check(f"{label}: her actual line follows behind it",
              second is not None and second.context["event_type"] == "GameEnd")
        check(f"{label}: and that one does go through the LLM",
              not second.skip_llm)
        check(f"{label}: which knows the result",
              second.context.get("won") is won)

    # The noise ignores the throttling that governs everything else.
    queue = SignalQueue()
    source = LolGameSource(queue, data)
    source._player_summoner = "exiled"
    source._current_game_time = 2100.0
    source._last_game_comment = 2100.0        # she spoke this instant
    source._reaction_log = {"GameCheer": [2100.0] * 5}
    source._handle_event({"EventName": "GameEnd", "Result": "Win"}, {})
    check("it fires even immediately after another line",
          queue.pop() is not None)


def main():
    test_state()
    test_role_detection()
    test_dragons_and_mood()
    test_angle_variety()
    test_flat_game_still_varies()
    test_angles_only_fire_on_true_facts()
    test_burst_decay()
    test_global_gap()
    test_cheer_and_boo()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
