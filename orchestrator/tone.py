"""
How hard she goes — and why it must not be a constant.

The rulebook is the streamer's, near enough verbatim:

    1st death, and he traded for a kill    -> cheerful; half the time, nothing
    deaths 2-5                             -> ~70% she comments
    dying for free                         -> full roast
    1+ kills of his own                    -> praise
    0 kills but he was in an objective     -> half praise, half mock
    death 6 onward                          -> "low deaths win games" mode,
                                              rising heat — UNLESS the death
                                              traded for 2+ KILLS (not assists),
                                              in which case be surprised

The part that is not in the rulebook, and matters as much: **the top of the
ladder cannot repeat.** From the live session — "FULL ROAST only makes her
repeat herself on the 2nd message". A tone is a narrow instruction, and asking
a 9B model for two maximum-heat roasts in a row gets the same roast twice. So
`ToneLadder` refuses to hand out the same tone consecutively and steps down
after a roast: the heat comes back on the death after next, which also makes it
land harder.

Tone is deliberately separate from the angle. The angle says *what to talk
about* (the drake count, the teammate who is one and nine); the tone says *how
warm to be about it*. Multiplying them is where the variety comes from — five
tones over sixty-odd angles, rather than one fixed "be dismissive" per event.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Warmest to harshest. The order is the ladder: `step_down` moves left.
TONES = ["warm", "light", "dry", "sharp", "roast"]

TONE_INSTRUCTION = {
    "warm": "Be genuinely pleased. No barb at the end, no undercutting "
            "yourself — you are allowed to just be glad about this one.",
    "light": "Amused and light. You are teasing, not scoring points; he can "
             "hear that you are on his side.",
    "dry": "Flat and dry. State it, do not decorate it. The lack of reaction "
           "is the reaction.",
    "sharp": "Pointed. Name the specific thing that went wrong and do not "
             "soften the landing.",
    "roast": "Full roast. Exasperated, merciless, still his — the mockery of "
             "someone who belongs to him, never contempt for a stranger.",
}

# What "low deaths win games" mode adds, from death six onward. Kept separate
# from the tone so it does not turn into a fixed prefix: it is a standing
# grievance she may reach for, not a sentence she must open with.
DEATH_LECTURE = (
    "He is well past the point where deaths are individually interesting. You "
    "have a standing position on this — games are won by not dying — and you "
    "may lean on it. Do not phrase it the way you phrased it last time."
)


# What she calls his teammates, and how that hardens as the game goes.
#
# The streamer's ladder: piggies, apes, creatures, bronze hardstuck — soft to
# harsh — stepping up on his death count. Deaths are the proxy for how the game
# is going, and by the time he has died nine times "the piggies" has stopped
# being funny.
#
# Keyed on HIS deaths rather than the team's on purpose: it is the number he
# feels, and it is the one already driving every other escalation in this file,
# so her vocabulary hardens in step with her tone instead of on its own clock.
TEAMMATE_RANKS = ((3, 1), (5, 2), (8, 3))       # deaths <= n -> rank
TEAMMATE_RANK_MAX = 4


def teammate_rank(death_count: int) -> int:
    """1-4, soft to harsh."""
    for limit, rank in TEAMMATE_RANKS:
        if death_count <= limit:
            return rank
    return TEAMMATE_RANK_MAX


@dataclass(frozen=True)
class Verdict:
    """What the numbers say about how he is doing, before any tone is chosen."""

    tone: str
    react_chance: float
    lecture: bool = False       # death 6+, "low deaths win games" territory
    surprised: bool = False     # a death that bought two or more kills
    free_death: bool = False    # nothing at all to show for it


def read_death(death_count: int, kills_traded: int, assists_traded: int) -> Verdict:
    """
    The rulebook above, applied to one death.

    kills_traded and assists_traded are what he got since his LAST death — the
    fight this death ended, not the game so far. "Dying for free" is both at
    zero, and it is the only thing that earns a roast before death six.
    """
    free = kills_traded == 0 and assists_traded == 0

    # Death six onward. A death that bought two or more KILLS is the exception
    # the streamer asked for: assists do not count, because trading yourself
    # for two kills is a decision and being nearby for two is not.
    if death_count >= 6:
        if kills_traded >= 2:
            return Verdict(tone="warm", react_chance=1.0,
                           lecture=False, surprised=True)
        return Verdict(tone="roast" if free else "sharp",
                       react_chance=1.0, lecture=True, free_death=free)

    # First death, traded for something: cheerful, and half the time she lets
    # it go entirely. Saying nothing IS the reaction.
    if death_count == 1 and not free:
        return Verdict(tone="warm", react_chance=0.5)

    if free:
        return Verdict(tone="roast", react_chance=0.9, free_death=True)

    if kills_traded >= 2:
        return Verdict(tone="warm", react_chance=0.8, surprised=True)

    if kills_traded >= 1:
        return Verdict(tone="light", react_chance=0.7)

    # Assists only — he was there, he did not close it.
    return Verdict(tone="dry", react_chance=0.7)


def read_kill(total_kills: int, deaths: int) -> Verdict:
    """His own kills. One is worth noticing; a lot while dying is not."""
    if deaths and total_kills < deaths:
        return Verdict(tone="dry", react_chance=0.7)
    if total_kills >= 5:
        return Verdict(tone="warm", react_chance=0.85)
    return Verdict(tone="light", react_chance=0.8)


def read_objective_participation(my_kills: int, took_part: bool) -> Verdict:
    """
    An objective he was in on.

    The streamer's "0 kills but we get an object where was my participation,
    50-50 praise mock" — she genuinely cannot decide whether showing up counts,
    so let the ladder decide and let it differ each time.
    """
    if not took_part:
        return Verdict(tone="dry", react_chance=0.5)
    if my_kills == 0:
        return Verdict(tone=random.choice(["light", "dry"]), react_chance=0.75)
    return Verdict(tone="warm", react_chance=0.8)


class ToneLadder:
    """
    Hands out tones, and refuses to repeat the harsh end of the ladder.

    One instance per source, reset between games.
    """

    def __init__(self):
        self._last = ""
        self._roasts = 0

    def reset(self) -> None:
        self._last = ""
        self._roasts = 0

    def resolve(self, wanted: str) -> str:
        """
        The tone she actually gets.

        A roast immediately after a roast is the failure mode the streamer
        reported, so the second one steps down. Warm tones may repeat: two
        pleased reactions in a row do not grate the way two roasts do, and
        pulling her off warm would read as her withdrawing approval for no
        reason.
        """
        tone = wanted if wanted in TONES else "dry"

        if tone == "roast":
            if self._roasts >= 1:
                tone = "sharp"          # step down; the heat returns later
                self._roasts = 0
            else:
                self._roasts += 1
        else:
            self._roasts = 0

        # Never the same harsh tone twice running. Warm and light are exempt.
        if tone == self._last and tone in ("dry", "sharp", "roast"):
            tone = _step_down(tone)

        self._last = tone
        return tone

    @property
    def last(self) -> str:
        return self._last


def _step_down(tone: str) -> str:
    i = TONES.index(tone)
    return TONES[max(0, i - 1)]


def instruction(tone: str, verdict: Verdict | None = None) -> str:
    """The TONE block for the prompt."""
    parts = [TONE_INSTRUCTION.get(tone, TONE_INSTRUCTION["dry"])]

    if verdict is not None:
        if verdict.surprised:
            parts.append("This one actually went well for him and you did not "
                         "expect it. Let the surprise show.")
        if verdict.lecture:
            parts.append(DEATH_LECTURE)

    return "TONE: " + " ".join(parts)
