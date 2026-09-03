"""
The shape of this particular game — as a disposition, never as a sentence.

From the meta notes: *"if I am playing Riven MID and they have [Garen,
Malzahar, Elise, Caitlyn, Zilean] then the theme of the game is me being sad,
how can I play, how can I move ... and her comments would carry hits, making
her comments be affected by this factor."*

And from the session after it: *"the theme sentence 'he's not even trying' was
like an entry message that never changed within one game, and such a prefix
became annoying quite fast."*

Both things are true at once, and the second is why this module hands back **no
text** after the opening line. A theme that produces a sentence produces the
same sentence forty times, because it is derived from facts that do not change
during a game. So the theme does exactly three things:

  1. Supplies ONE opening instruction, used only at GameStart and never again.
  2. Nudges the tone ladder a step warmer or harsher for the rest of the game.
  3. Unlocks a handful of extra angles, which the chooser then rotates like any
     other — so the theme's influence arrives as *different* remarks about the
     same underlying situation, rather than one remark repeated.

That third point is the whole trick. "He is immobile into a team that can chain
him" is not a line she says; it is a reason certain observations become
available, and the anti-repetition machinery still governs which of them she
reaches for.

Champion tags come from data/champions.json and are the streamer's own, per
STATUS.md §7 — "tag heavy_cc / hard_engage yourself so 'five of them can stop
you moving' is arithmetic on YOUR data, never her opinion". No champion is
tagged here from memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How many tagged enemies it takes before the comp is worth a theme. Three is
# the point at which "some of them have CC" becomes "you are not going to be
# allowed to move".
HEAVY_CC_THRESHOLD = 3


@dataclass(frozen=True)
class Theme:
    """A disposition for one game. Immutable once the game starts."""

    id: str = ""
    opening: str = ""           # GameStart only
    tone_shift: int = 0         # -1 warmer, +1 harsher, per comment
    angles: tuple = field(default_factory=tuple)   # extra angle ids unlocked

    def __bool__(self) -> bool:
        return bool(self.id)


NO_THEME = Theme()


# Role dispositions, from the meta notes. These are HIS assessments of his own
# play, which is what makes them sayable at all — §7's governing principle.
# They are only used when data/champions.json has a real note for that role,
# so an unwritten file leaves her with nothing to assert.
ROLE_THEMES = {
    "jungle": Theme(
        id="role_jungle",
        opening="He has queued jungle, which by his own account is his worst "
                "role. Open on that — he told you this himself, so it is his "
                "admission and not your diagnosis. Whine about it.",
        tone_shift=+1,
        angles=("theme_jungle_not_trying", "theme_jungle_camps"),
    ),
    "middle": Theme(
        id="role_middle",
        opening="Mid is comfortable for him. Open expecting a good game and "
                "one that ends with him having ignored his team entirely.",
        tone_shift=0,
        angles=("theme_mid_tunnel", "theme_mid_swing"),
    ),
    "bottom": Theme(
        id="role_bottom",
        opening="Bot is where he actually tries to win. Open on that — mildly "
                "approving, and suspicious that it will last.",
        tone_shift=-1,
        angles=("theme_adc_actually_trying", "theme_adc_needs_a_team"),
    ),
    "utility": Theme(
        id="role_support",
        opening="Support, by his own account, is him passing the time with "
                "zero effort. Open on that, unimpressed but not cruel.",
        tone_shift=0,
        angles=("theme_support_passing_time",),
    ),
    "top": Theme(
        id="role_top",
        opening="Top is his best role and he knows it. Open expecting a "
                "splitpush and an ignored team fight.",
        # Neutral, not soft. This is where he is good, so there is less to
        # forgive and also less to excuse — theme_top_comfort holds him to the
        # higher standard, and a warm shift would have contradicted it.
        tone_shift=0,
        angles=("theme_top_splitpush", "theme_top_comfort"),
    ),
}


# The comp theme. Beats a role theme when it fires, because being unable to
# move is a bigger fact about a game than which lane he queued.
IMMOBILE_THEME = Theme(
    id="comp_immobile",
    opening="He is on a melee champion that has to walk at people, and by his "
            "own tagging their team is full of ways to stop him doing it. "
            "Open on that: not a prediction about the matchup, just the "
            "arithmetic of how many of them can hold him still.",
    tone_shift=-1,      # she is more forgiving; this one is not his fault
    angles=("theme_cannot_move", "theme_cc_chain", "theme_walked_at_them"),
)


def resolve(role: str, champion: str, enemy_champions: list[str],
            champion_tags) -> Theme:
    """
    Pick the theme for this game. Called once, at game start.

    champion_tags is a callable name -> set of tags, backed by
    data/champions.json. Untagged champions contribute nothing, so an empty
    file simply means no comp theme — never a guessed one.
    """
    my_tags = champion_tags(champion)

    if "melee" in my_tags or "immobile" in my_tags:
        heavy = sum(1 for e in enemy_champions
                    if "heavy_cc" in champion_tags(e))
        if heavy >= HEAVY_CC_THRESHOLD:
            return IMMOBILE_THEME

    return ROLE_THEMES.get((role or "").lower(), NO_THEME)
