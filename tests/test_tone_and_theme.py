"""
How hard she goes, and the shape of a game.

    python tests/test_tone_and_theme.py

Two reports from live sessions drive this file.

"FULL ROAST only makes her repeat herself on the 2nd message" — a tone is a
narrow instruction, and asking a 9B model for two maximum-heat roasts back to
back gets the same roast twice. The ladder refuses consecutive roasts.

"The theme sentence 'he's not even trying' was like an entry message that never
changed within one game, and such a prefix became annoying quite fast" — a
theme derived from facts that do not change during a game will produce the same
sentence every time if it is allowed to produce a sentence at all. So after its
one opening line the theme emits NO text: it shifts the tone a step and unlocks
extra angles, which the chooser then rotates like any others.

The rulebook itself is the streamer's, near enough verbatim, and
`test_rulebook` walks it case by case.
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

from app.settings import get_settings                          # noqa: E402
from orchestrator import game_theme, tone                      # noqa: E402
from orchestrator.game_angles import (                          # noqa: E402
    THEME_ANGLES, AngleChooser,
)
from orchestrator.game_state import GameState                   # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ===================================================== the streamer's rulebook
def test_rulebook():
    print("\n--- the rulebook, case by case ---")

    # "1st death + i kill as well she will be cheerfull 50% to say nothing"
    first = tone.read_death(death_count=1, kills_traded=1, assists_traded=0)
    check("first death traded for a kill is cheerful", first.tone == "warm",
          first.tone)
    check("and half the time she says nothing at all",
          abs(first.react_chance - 0.5) < 1e-9, str(first.react_chance))

    # "2-5 deaths 70% she will comment"
    for n in (2, 3, 4, 5):
        v = tone.read_death(n, kills_traded=0, assists_traded=1)
        check(f"death {n} with an assist comments ~70%",
              abs(v.react_chance - 0.7) < 1e-9, str(v.react_chance))

    # "also dying for free full roast"
    free = tone.read_death(3, kills_traded=0, assists_traded=0)
    check("dying for free is a roast", free.tone == "roast", free.tone)
    check("and is flagged as free", free.free_death)
    check("and almost always lands", free.react_chance >= 0.9)

    # "if i get 1+ kill praise"
    one = tone.read_death(3, kills_traded=1, assists_traded=0)
    check("a death that traded for a kill is not harsh",
          one.tone in ("warm", "light"), one.tone)

    # "every death after 5 tone be like low death win games"
    sixth = tone.read_death(6, kills_traded=0, assists_traded=0)
    check("death six turns on the lecture", sixth.lecture)
    check("and always gets a reaction", sixth.react_chance == 1.0)
    check("the lecture text warns against repeating itself",
          "last time" in tone.DEATH_LECTURE)

    # "unleass my death gives me 2+ kills (not assists kills)"
    saved = tone.read_death(9, kills_traded=2, assists_traded=0)
    check("two kills excuses a late death", saved.tone == "warm", saved.tone)
    check("and she is surprised by it", saved.surprised)
    check("no lecture on a death that bought two kills", not saved.lecture)

    assists_only = tone.read_death(9, kills_traded=0, assists_traded=4)
    check("assists do NOT earn the exception — kills only",
          assists_only.lecture and not assists_only.surprised,
          f"lecture={assists_only.lecture} surprised={assists_only.surprised}")

    # "if i get 0 kills but we get object where was my participation 50-50"
    took_part = {tone.read_objective_participation(0, True).tone
                 for _ in range(40)}
    check("an objective he joined with no kills is genuinely split",
          len(took_part) >= 2, str(took_part))
    check("an objective he was not in is flat",
          tone.read_objective_participation(0, False).tone == "dry")


# ============================================================== the ladder
def test_ladder_refuses_to_repeat():
    print("\n--- the ladder will not roast twice running ---")
    ladder = tone.ToneLadder()

    first = ladder.resolve("roast")
    second = ladder.resolve("roast")
    check("the first roast lands", first == "roast", first)
    check("the second steps down instead", second != "roast", second)
    check("and steps down rather than up",
          tone.TONES.index(second) < tone.TONES.index("roast"), second)

    third = ladder.resolve("roast")
    check("the heat comes back after the gap", third == "roast", third)

    ladder = tone.ToneLadder()
    harsh = [ladder.resolve("sharp") for _ in range(4)]
    check("no harsh tone repeats back to back",
          all(a != b for a, b in zip(harsh, harsh[1:])), str(harsh))

    # Warm is exempt: two pleased reactions do not grate, and pulling her off
    # warm would read as withdrawing approval for no reason.
    ladder = tone.ToneLadder()
    warm = [ladder.resolve("warm") for _ in range(3)]
    check("warm may repeat", warm == ["warm", "warm", "warm"], str(warm))

    ladder.reset()
    check("reset clears the ladder", ladder.last == "", ladder.last)

    check("an unknown tone falls back rather than raising",
          tone.ToneLadder().resolve("nonsense") in tone.TONES)


def test_tone_instruction():
    print("\n--- the tone block ---")
    for name in tone.TONES:
        text = tone.instruction(name)
        check(f"{name} has an instruction", text.startswith("TONE: ")
              and len(text) > 20, text[:40])

    surprised = tone.instruction("warm", tone.read_death(9, 2, 0))
    check("a surprising death says so", "surprise" in surprised.lower())

    lectured = tone.instruction("roast", tone.read_death(7, 0, 0))
    check("the lecture is attached from death six", "not dying" in lectured)


# ================================================================= the theme
def tags_from(mapping):
    return lambda champ: set(mapping.get(champ, ()))


def test_theme_resolution():
    print("\n--- the theme ---")
    plain = tags_from({})

    check("jungle is his worst role and she is harder on him",
          game_theme.resolve("jungle", "Riven", [], plain).tone_shift == +1)
    check("bot is where he tries and she is softer",
          game_theme.resolve("bottom", "Smolder", [], plain).tone_shift == -1)
    check("an unknown role gets no theme",
          not game_theme.resolve("", "Riven", [], plain))

    # The comp theme needs HIS tags. Untagged champions count for nothing —
    # STATUS.md §7: arithmetic on his data, never her opinion.
    enemies = ["Garen", "Malzahar", "Nautilus", "Caitlyn", "Zilean"]
    check("an untagged enemy team produces no comp theme",
          game_theme.resolve("middle", "Riven", enemies, plain).id
          != "comp_immobile")

    tagged = tags_from({
        "Riven": ("melee",),
        "Garen": ("heavy_cc",), "Malzahar": ("heavy_cc",),
        "Nautilus": ("heavy_cc",),
    })
    themed = game_theme.resolve("middle", "Riven", enemies, tagged)
    check("melee into three tagged CC enemies is the immobile theme",
          themed.id == "comp_immobile", themed.id)
    check("and she is more forgiving, not less", themed.tone_shift == -1)
    check("it beats the role theme",
          themed.id != game_theme.ROLE_THEMES["middle"].id)

    two_only = tags_from({"Riven": ("melee",),
                          "Garen": ("heavy_cc",), "Malzahar": ("heavy_cc",)})
    check("two tagged enemies is not enough",
          game_theme.resolve("middle", "Riven", enemies, two_only).id
          != "comp_immobile")

    check("a ranged champion into the same team is not immobile",
          game_theme.resolve("middle", "Caitlyn", enemies, tagged).id
          != "comp_immobile")


def test_theme_is_not_a_prefix():
    """
    The heart of it. After the opening, the theme must emit no text.

    A theme derived from facts that do not change during a game produces the
    same sentence forty times if it is allowed to produce a sentence.
    """
    print("\n--- a theme is a disposition, not a sentence ---")

    theme = game_theme.ROLE_THEMES["jungle"]
    check("a theme has exactly one opening line", bool(theme.opening))
    check("and its ongoing influence is angle ids, not text",
          all(isinstance(a, str) and a in THEME_ANGLES for a in theme.angles),
          str(theme.angles))

    state = GameState()
    state.game_time = 900.0
    state.champion = "Riven"

    # Across a game the theme's angles must rotate, not repeat.
    chooser = AngleChooser()
    picked = [chooser.choose("AllyDeath", state,
                             {"theme_angles": theme.angles}).id
              for _ in range(10)]
    check("theme angles do not repeat back to back",
          all(a != b for a, b in zip(picked, picked[1:])), str(picked))
    check("the theme widens the pool rather than taking it over",
          any(p not in theme.angles for p in picked), str(picked))
    check("but its angles do get used",
          any(p in theme.angles for p in picked), str(picked))

    # And with no theme, nothing changes.
    bare = AngleChooser()
    unthemed = [bare.choose("AllyDeath", state, {}).id for _ in range(6)]
    check("no theme means no theme angles",
          not any(p in THEME_ANGLES for p in unthemed), str(unthemed))


def test_theme_shifts_tone():
    print("\n--- the theme shifts tone by a step ---")
    from sources.lol_game import _shift_tone

    check("a harsher shift moves one step up",
          _shift_tone("dry", +1) == "sharp")
    check("a softer shift moves one step down",
          _shift_tone("dry", -1) == "light")
    check("no shift is identity", _shift_tone("dry", 0) == "dry")
    check("it clamps at the harsh end", _shift_tone("roast", +1) == "roast")
    check("and at the warm end", _shift_tone("warm", -1) == "warm")
    check("an unknown tone passes through", _shift_tone("weird", +1) == "weird")


def test_teammate_ladder():
    """
    What she calls his teammates hardens as the game goes.

    The streamer's ladder — piggies, apes, creatures, bronze hardstuck, soft to
    harsh — keyed on his death count. It replaces one flat list in the system
    prompt that gave her no way to sound angrier at death nine than at death
    one, which is a large part of "she was mostly dismissive".
    """
    print("\n--- the teammate ladder ---")
    import json
    from pathlib import Path

    for deaths, expected in [(0, 1), (1, 1), (3, 1),
                             (4, 2), (5, 2),
                             (6, 3), (8, 3),
                             (9, 4), (30, 4)]:
        got = tone.teammate_rank(deaths)
        check(f"{deaths} deaths is rank {expected}", got == expected, str(got))

    check("it never exceeds the top rank",
          tone.teammate_rank(999) == tone.TEAMMATE_RANK_MAX)
    check("the ladder only ever rises",
          all(tone.teammate_rank(d) <= tone.teammate_rank(d + 1)
              for d in range(0, 40)))

    # And the words actually exist for every rank it can return.
    data = json.loads((Path(__file__).resolve().parent.parent
                       / "data" / "game_quotes.json").read_text(encoding="utf-8"))
    ranks = data["teammates"]["ranks"]
    for r in range(1, tone.TEAMMATE_RANK_MAX + 1):
        words = ranks.get(str(r), [])
        check(f"rank {r} has words", len(words) >= 2, str(words))
    check("no word appears in two ranks — the ladder would not read as one",
          len({w for ws in ranks.values() for w in ws})
          == sum(len(ws) for ws in ranks.values()))


def test_russian_mixing():
    print("\n--- the Russian coin flip ---")
    import json
    from pathlib import Path

    check("the chance is a probability", 0.0 <= S.LANG_AMBIENT_RU_CHANCE <= 1.0,
          str(S.LANG_AMBIENT_RU_CHANCE))

    # A quote is spoken verbatim, so a Russian game needs Russian ones — there
    # is no model anywhere in that path to translate them.
    data = json.loads((Path(__file__).resolve().parent.parent
                       / "data" / "game_quotes.json").read_text(encoding="utf-8"))
    pools = data["game_state"]
    for pool in ("cheer", "boo"):
        check(f"{pool} has a Russian pool", pools.get(pool + "_ru"),
              str(list(pools)))
        check(f"{pool}_ru is actually Cyrillic",
              any(any("\u0400" <= ch <= "\u04ff" for ch in line)
                  for line in pools[pool + "_ru"]))
        check(f"{pool}_ru is the same size as {pool}",
              len(pools[pool + "_ru"]) == len(pools[pool]))


def main():
    test_rulebook()
    test_ladder_refuses_to_repeat()
    test_tone_instruction()
    test_theme_resolution()
    test_theme_is_not_a_prefix()
    test_theme_shifts_tone()
    test_teammate_ladder()
    test_russian_mixing()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
