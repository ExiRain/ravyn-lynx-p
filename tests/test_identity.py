"""
Identity resolution, and what depends on it.

    python tests/test_identity.py

From a real log:

    [lol] Game detected!  as ()
    [lol]   riotId='' summonerName=''
    [lol]   Enemies: False | Names: 0
    [lol]   WARNING: could not identify the active player

The endpoint answering is not the same as a game being readable. On the loading
screen it responds with an empty activePlayer and an empty allPlayers, and the
old code accepted that as a game and latched the empty identity for the whole
match. Everything that splits ours from theirs then broke at once, silently and
confidently:

  * `GameState.update` matched nobody as an ally and swept all ten champions
    into enemy_champions, so she opened on the "chaotic mix" of a ten-man team
  * every kill counted to the enemy
  * `_is_me` never fired, so his own KDA and CS stayed zero
  * `_has_real_enemies` went False, which makes `_classify_killer` return
    "mine", so every objective in the game counted as his team's

That is what "she counts total kills and objectives without splitting who did
what" was: with no team there is no split. The rule these tests hold is that
being unable to answer is a reason to WAIT, never a reason to guess — a wrong
team produces confident wrong commentary, which is worse than silence.
"""

import sys
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

from orchestrator.game_state import GameState              # noqa: E402
from orchestrator.priority_queue import SignalQueue        # noqa: E402
from sources.lol_game import LolGameSource                 # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


LOADING_SCREEN = {
    "gameData": {"gameTime": 0.0},
    "activePlayer": {"riotId": "", "summonerName": ""},
    "allPlayers": [],
    "events": {"Events": []},
}


def row(champ, team, k, d, a, cs, me=False):
    """A RU-shaped row: summonerName empty, riotId the only handle."""
    return {
        "championName": champ,
        "summonerName": "" if me else champ.lower(),
        "riotId": ("Серый Экран#RU" if me else f"{champ.lower()}#RU"),
        "team": team, "level": 11, "position": "",
        "summonerSpells": {}, "items": [],
        "scores": {"kills": k, "deaths": d, "assists": a,
                   "creepScore": cs, "wardScore": 4.0},
    }


def real_game(t=1500.0):
    return {
        "gameData": {"gameTime": t},
        "activePlayer": {"riotId": "Серый Экран#RU", "summonerName": ""},
        "allPlayers": [
            row("Riven", "ORDER", 6, 2, 3, 150, me=True),
            row("LeeSin", "ORDER", 3, 4, 8, 90),
            row("Orianna", "ORDER", 2, 5, 4, 160),
            row("Jinx", "ORDER", 1, 9, 2, 110),
            row("Thresh", "ORDER", 0, 7, 11, 20),
            row("Darius", "CHAOS", 11, 2, 4, 180),
            row("Elise", "CHAOS", 5, 3, 9, 70),
            row("Syndra", "CHAOS", 4, 4, 6, 175),
            row("Caitlyn", "CHAOS", 6, 3, 5, 190),
            row("Nautilus", "CHAOS", 1, 5, 14, 25),
        ],
        "events": {"Events": []},
    }


def source():
    return LolGameSource(SignalQueue(), DATA)


def test_loading_screen_is_not_a_game():
    print("\n--- the loading screen is not a game ---")
    src = source()
    src._fetch = lambda: LOADING_SCREEN
    src._check_for_game()

    check("an empty player list does not start a game", not src.is_game_active)
    check("no identity is latched", src._player_team == "", src._player_team)
    check("no names are latched", src._name_to_team == {})

    # Half-built snapshots are equally refused.
    half = dict(LOADING_SCREEN, allPlayers=real_game()["allPlayers"])
    src._fetch = lambda: half
    src._check_for_game()
    check("players without an active player is refused", not src.is_game_active)

    stranger = dict(real_game(),
                    activePlayer={"riotId": "SomeoneElse#EUW",
                                  "summonerName": "SomeoneElse"})
    src._fetch = lambda: stranger
    src._check_for_game()
    check("an active player matching nobody is refused", not src.is_game_active)


def test_identity_resolves_when_ready():
    print("\n--- and starts as soon as it is readable ---")
    src = source()
    src._fetch = lambda: LOADING_SCREEN
    src._check_for_game()
    check("still waiting", not src.is_game_active)

    src._fetch = real_game
    src._check_for_game()
    check("the game starts once the list arrives", src.is_game_active)
    check("team resolved", src._player_team == "ORDER", src._player_team)
    check("champion resolved", src._player_champion == "Riven",
          src._player_champion)
    check("RU riotId works with an empty summonerName",
          src._player_summoner == "Серый Экран", src._player_summoner)
    check("enemies detected", src._has_real_enemies)
    check("he is recognised as himself", src._is_me("Серый Экран#RU"))
    check("and by champion", src._is_me("Riven"))
    check("teammates are not him", not src._is_me("leesin#RU"))
    check("his side classifies as mine",
          src._classify_killer("leesin#RU") == "mine")
    check("the other side classifies as enemy",
          src._classify_killer("darius#RU") == "enemy")


def test_state_refuses_to_guess_sides():
    print("\n--- state refuses to guess sides ---")
    blind = GameState()
    blind.update(real_game(), "", set())

    check("no team means no enemy champions invented",
          blind.enemy_champions == [], str(blind.enemy_champions))
    check("no team means no kill totals",
          blind.ours.kills == 0 and blind.theirs.kills == 0)
    check("the minute is still read", blind.game_time == 1500.0)
    check("nothing about sides reaches the prompt",
          "Kills:" not in blind.render() and "Enemy team" not in blind.render())

    # And with a team, the same snapshot splits properly.
    good = GameState()
    good.update(real_game(), "ORDER", {"серый экран#ru", "riven"})
    check("with a team, allies and enemies separate",
          len(good.allies) == 4 and len(good.enemies) == 5,
          f"{len(good.allies)}/{len(good.enemies)}")
    check("his own line is read", good.kda_line == "6/2/3", good.kda_line)
    check("team totals split", good.ours.kills == 12 and good.theirs.kills == 27,
          f"{good.ours.kills}/{good.theirs.kills}")


def test_unknown_side_records_nothing():
    print("\n--- an unattributed objective is not filed to either team ---")
    s = GameState()
    s.update(real_game(), "ORDER", {"серый экран#ru"})

    s.record_dragon("unknown", "Infernal")
    s.record_baron("unknown")
    s.record_turret("unknown")
    check("an unknown drake goes nowhere",
          not s.ours.dragons and not s.theirs.dragons)
    check("an unknown baron goes nowhere",
          s.ours.barons == 0 and s.theirs.barons == 0)
    check("an unknown tower goes nowhere",
          s.ours.turrets == 0 and s.theirs.turrets == 0)

    s.record_dragon("mine", "Ocean", "LeeSin")
    s.record_dragon("enemy", "Cloud", "Elise")
    check("known sides still record",
          len(s.ours.dragons) == 1 and len(s.theirs.dragons) == 1)
    check("and who took it is kept",
          s.ours.objective_takers == ["LeeSin"], str(s.ours.objective_takers))


def test_who_did_what():
    print("\n--- who did what, not just which side ---")
    s = GameState()
    s.update(real_game(), "ORDER", {"серый экран#ru"})
    rendered = s.render()

    check("teammates appear by champion and line",
          "Jinx 1/9/2" in rendered, rendered)
    check("enemies appear by champion and line",
          "Darius 11/2/4" in rendered)
    check("his own line is separate from the team total",
          "Exiled: Riven" in rendered and "Kills: your team 12" in rendered)

    check("the worst teammate is identifiable",
          s.worst_ally().champion == "Jinx", str(s.worst_ally()))
    check("the enemy actually winning is identifiable",
          s.biggest_threat().champion == "Darius", str(s.biggest_threat()))
    check("outperforming his own team is detectable", s.carrying())

    # One player taking every drake reads differently from four people.
    for _ in range(3):
        s.record_dragon("mine", "Infernal", "LeeSin")
    check("one player taking all the drakes is called out",
          "all of yours taken by LeeSin" in s.render(), s._dragon_line())

    s.ours.objective_takers.append("Thresh")
    check("but not when several people took them",
          "all of yours taken by" not in s.render(), s._dragon_line())


def test_objective_attribution_in_events():
    print("\n--- event text names the taker ---")
    import random as _random
    import sources.lol_game as lol

    src = source()
    src._fetch = real_game
    src._check_for_game()
    src._current_game_time = 1500.0

    pushed = []
    src.queue.push = lambda sig: pushed.append(sig)

    # REACTION_CHANCE and the burst decay would otherwise drop events at
    # random and make this test flake. Both are exercised in
    # test_game_variety.py; here we care only about the text.
    original = lol.random.random
    lol.random.random = lambda: 0.0
    try:
        _attribution_cases(src, pushed)
    finally:
        lol.random.random = original


def _attribution_cases(src, pushed):

    src._handle_dragon({"DragonType": "Infernal", "KillerName": "leesin#RU",
                        "EventTime": 1500.0})
    check("a teammate's drake names the teammate",
          pushed and "Exiled's teammate LeeSin took" in pushed[-1].text,
          pushed[-1].text if pushed else "nothing pushed")

    pushed.clear()
    src._handle_dragon({"DragonType": "Ocean", "KillerName": "Серый Экран#RU",
                        "EventTime": 1500.0})
    check("his own drake names him",
          pushed and pushed[-1].text.startswith("Exiled took"),
          pushed[-1].text if pushed else "nothing pushed")

    pushed.clear()
    src._handle_dragon({"DragonType": "Cloud", "KillerName": "elise#RU",
                        "EventTime": 1500.0})
    check("an enemy drake names the enemy",
          pushed and "The enemy Elise took" in pushed[-1].text,
          pushed[-1].text if pushed else "nothing pushed")

    # A neutral or unresolvable killer must not become a champion name.
    pushed.clear()
    src._handle_dragon({"DragonType": "Mountain", "KillerName": "SRU_Dragon",
                        "EventTime": 1500.0})
    check("an unresolvable killer is not invented into a champion",
          pushed and "SRU_Dragon" not in pushed[-1].text,
          pushed[-1].text if pushed else "nothing pushed")


def main():
    test_loading_screen_is_not_a_game()
    test_identity_resolves_when_ready()
    test_state_refuses_to_guess_sides()
    test_unknown_side_records_nothing()
    test_who_did_what()
    test_objective_attribution_in_events()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
