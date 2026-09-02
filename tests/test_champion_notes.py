"""
His notes about his own account — data/champions.json.

    python tests/test_champion_notes.py

The line this protects is STATUS.md §7's governing principle. She may repeat
what he told her; she may not turn it into a read of her own, and she may not
claim a lane assignment nobody established. So the tests care as much about
what does NOT fire as what does.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.champion_notes import ChampionNotes, key   # noqa: E402
from orchestrator.game_angles import AngleChooser            # noqa: E402
from orchestrator.game_state import GameState                # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


FILE = {
    "roles": {
        "top": {"skill": "best", "read": "this is where I know what I'm doing"},
        "middle": {"skill": "ok", "read": "I'm still learning mid"},
    },
    "champions": {
        "Riven": {
            "main_role": "top",
            "history": "I play her constantly and still lose with her",
            "offrole_read": "I'm still learning Riven anywhere but top",
            "matchups": {"Garen": "I never win this lane, I take it anyway"},
        },
        "Lee Sin": {"main_role": "jungle", "history": "I only pick him to show off"},
    },
}


def load(data=None) -> ChampionNotes:
    path = Path(tempfile.mkdtemp()) / "champions.json"
    path.write_text(json.dumps(data if data is not None else FILE))
    return ChampionNotes(path)


ENEMIES = ["Garen", "Elise", "Syndra", "Caitlyn", "Nautilus"]


def test_lookup():
    print("\n--- lookup ---")
    check("spaces and case are ignored", key("Lee Sin") == key("leesin") == "leesin")
    check("apostrophes are ignored", key("Kai'Sa") == "kaisa")
    check("the API's MonkeyKing is Wukong", key("MonkeyKing") == key("Wukong"))

    notes = load()
    read = notes.read("Riven", "top", ENEMIES)
    check("champion history resolved", "still lose with her" in read.champion_history)
    check("role read resolved", "know what I'm doing" in read.role_read)
    check("role skill resolved", read.role_skill == "best", read.role_skill)


def test_offrole():
    print("\n--- off role ---")
    notes = load()

    on = notes.read("Riven", "top", ENEMIES)
    check("main role is not off role", not on.offrole)

    off = notes.read("Riven", "middle", ENEMIES)
    check("a different role is off role", off.offrole)
    check("the off-role note is his own words",
          "still learning Riven" in off.offrole_read)
    check("off role renders first, as the opening beat",
          off.render().index("still learning Riven") < off.render().index("still lose with her"))

    unknown = notes.read("Riven", "", ENEMIES)
    check("unknown role cannot be off role", not unknown.offrole)


def test_matchup_confidence():
    print("\n--- how confidently the lane is claimed ---")
    notes = load()

    # He filed Garen under Riven, whose main_role is top, and he is playing
    # top. The lane claim is his.
    top = notes.read("Riven", "top", ENEMIES)
    check("his own file scopes the lane when he is on that role",
          top.matchups and top.matchups[0][2] == "lane", str(top.matchups))
    check("and it renders as a lane matchup",
          "laning against Garen" in top.render())

    # Playing Riven mid: the Garen note was written for top, so no lane claim.
    mid = notes.read("Riven", "middle", ENEMIES)
    check("a note written for another role makes no lane claim",
          mid.matchups and mid.matchups[0][2] == "team", str(mid.matchups))
    check("it still fires, phrased as team presence",
          "on the enemy team" in mid.render())

    # Role unknown — today's state before quest-item detection.
    blind = notes.read("Riven", "", ENEMIES)
    check("unknown role makes no lane claim",
          blind.matchups and blind.matchups[0][2] == "team", str(blind.matchups))

    # Measured agreement wins on its own, without main_role.
    measured = notes.read("Riven", "middle", ENEMIES, {"Garen": "middle"})
    check("measured matching roles claim the lane",
          measured.matchups[0][2] == "lane", str(measured.matchups))

    # A champion he wrote nothing about produces nothing.
    absent = notes.read("Riven", "top", ["Elise", "Syndra"])
    check("no note means no matchup line", absent.matchups == [])


def test_labelling():
    print("\n--- his words stay labelled as his ---")
    read = load().read("Riven", "top", ENEMIES)
    rendered = read.render()
    check("the block says these are his words, not the game's",
          "his words about his own account" in rendered)
    check("it forbids extending them into her own opinions",
          "do not extend them into opinions of your own" in rendered)
    check("every note is quoted, so it reads as reported speech",
          rendered.count('"') >= 6, str(rendered.count('"')))


def test_missing_and_broken():
    print("\n--- missing and broken files ---")
    empty = ChampionNotes()
    read = empty.read("Riven", "top", ENEMIES)
    check("no file at all yields nothing", not read)
    check("and renders as nothing", read.render() == "")

    absent = ChampionNotes(Path(tempfile.mkdtemp()) / "nope.json")
    check("a missing file is survivable", not absent.read("Riven", "top", ENEMIES))

    path = Path(tempfile.mkdtemp()) / "champions.json"
    path.write_text("{ this is not json")
    check("a hand-edit typo is survivable",
          not ChampionNotes(path).read("Riven", "top", ENEMIES))

    partial = load({"champions": {"Riven": {"history": "just this"}}})
    read = partial.read("Riven", "top", ENEMIES)
    check("a champion with only a history still works",
          read.champion_history == "just this" and not read.matchups)
    check("a role with no entry is simply absent", read.role_read == "")

    untagged = load().read("Yasuo", "top", ENEMIES)
    check("an untagged champion falls back to the role note",
          untagged.role_read and not untagged.champion_history)


def test_angles_gate_on_real_notes():
    print("\n--- note angles only fire when a note exists ---")
    state = GameState()
    state.game_time = 5.0
    state.champion, state.position = "Riven", "top"
    state.enemy_champions = ENEMIES

    # Nothing written: the note-driven openers must not fire at all.
    bare = {"has_matchup_note": False, "has_champion_history": False,
            "has_role_note": False, "is_offrole": False}
    picked = {AngleChooser().choose("GameStart", state, bare).id for _ in range(4)}
    note_angles = {"start_matchup_note", "start_offrole",
                   "start_champion_history", "start_role_read"}
    check("an empty champions.json fires no note angles",
          not (picked & note_angles), str(picked))

    # Written: the opener leads on it.
    read = load().read("Riven", "top", ENEMIES)
    rich = {"has_matchup_note": bool(read.matchups),
            "has_champion_history": bool(read.champion_history),
            "has_role_note": bool(read.role_read),
            "is_offrole": read.offrole}
    first = AngleChooser().choose("GameStart", state, rich).id
    check("with a matchup written, the opener leads on it",
          first == "start_matchup_note", first)

    # A death to a champion he warned about, versus one he did not.
    told = AngleChooser().choose("MyDeath", state, {"killer_has_note": True,
                                                   "death_count": 2}).id
    check("a death to a champion he warned about can use that",
          told == "my_death_told_you", told)

    for _ in range(6):
        angle = AngleChooser().choose("MyDeath", state, {"killer_has_note": False,
                                                        "death_count": 2})
        check(f"no told-you angle without a note ({angle.id})",
              angle.id != "my_death_told_you", angle.id)


def test_shipped_file_is_valid():
    print("\n--- the shipped data/champions.json ---")
    path = Path(__file__).resolve().parent.parent / "data" / "champions.json"
    check("it exists", path.exists())
    if not path.exists():
        return
    notes = ChampionNotes(path)
    check("it parses and loads roles", len(notes.roles) >= 3, str(len(notes.roles)))
    check("it carries a readme", "_readme" in json.loads(path.read_text()))

    read = notes.read("Riven", "middle", ENEMIES)
    check("the shipped example resolves end to end", bool(read))
    check("placeholders are obvious", "PLACEHOLDER" in read.render(),
          read.render()[:80])


def main():
    test_lookup()
    test_offrole()
    test_matchup_confidence()
    test_labelling()
    test_missing_and_broken()
    test_angles_gate_on_real_notes()
    test_shipped_file_is_valid()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
