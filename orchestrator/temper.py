"""
Her temper — the slow axis.

`tone.py` decides how hard she goes on **this death**. Temper decides what kind
of company she is **tonight**, and it moves over hours rather than events:

    SUPPORTIVE   "You can do this. I'm not going anywhere."
    NEUTRAL      what she has always been
    NEGATIVE     "Stop feeding. You're playing like my grandfather."

Three registers, starting at NEUTRAL, moved by what the session has actually
been: wins and good KDA push toward supportive, losses and deaths and the
sheer number of games take their toll the other way.

**A register is not an intensity.** This is the thing that makes temper worth
having rather than being a fourth knob on the tone ladder: SUPPORTIVE is not
"mildly sarcastic", it is *on his side out loud*, which is a different
sentence entirely. So each register carries its own instruction, and the
ladder is clamped underneath it — she cannot roast while supportive no matter
what the ninth death says.

**Harder does not mean more often.** From a measured session: 79% of her lines
aimed at him, fifteen in a row. That is what a losing night produces when
every input pushes the same direction and nothing bounds the total, and it is
the reason the streamer asked for temper in the first place. So NEGATIVE
*sharpens* and **speaks less** — a pointed remark every so often lands; a
pointed remark every forty seconds is noise. `heat_factor` and
`MAX_HARSH_STREAK` are what hold that line.

Nothing here is league-specific. With no games recorded it drifts on session
length alone, which is what a non-league stream looks like.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from orchestrator import tone as tone_engine


SUPPORTIVE = "supportive"
NEUTRAL = "neutral"
NEGATIVE = "negative"

REGISTERS = (SUPPORTIVE, NEUTRAL, NEGATIVE)

# What each register tells her to BE. Written to be read beside a tone
# instruction without contradicting it — the tone says how warm to be about
# this one event, this says who she is being while she says it.
REGISTER_INSTRUCTION = {
    SUPPORTIVE: (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. Encourage him outright — tell him he can do this, that the game "
        "is not over, that you have seen him play better than the people "
        "beating him. No barb at the end, no undercutting it. If the only "
        "honest thing to say about a play is that it was bad, say it kindly "
        "and then say what to do instead."
    ),
    NEUTRAL: (
        "YOUR TEMPER RIGHT NOW: level. Neither cheering him on nor grinding "
        "him down — you say what you see and let it stand."
    ),
    NEGATIVE: (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. Short, "
        "blunt, unimpressed — the exasperation of someone who belongs to him "
        "and has watched this exact mistake all evening. Never contempt for a "
        "stranger, and never a speech: the shorter it is, the harder it "
        "lands."
    ),
}

# SUPPORTIVE said one thing, so she did too. On 2026-11-10 a supportive game
# had 14 of 41 lines flagged as repeats: one paragraph on every prompt came
# back as one pep talk in six wordings ("you've got the gold and the numbers,
# keep pushing while they scramble"). These are different ways of being on his
# side, dealt without replacement so the same one never rides two lines
# running. The first is the original, which stays the register's definition.
SUPPORTIVE_INSTRUCTIONS = (
    REGISTER_INSTRUCTION[SUPPORTIVE],
    (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. Name one thing he is doing right in this moment, plainly, and "
        "stop there. No pep talk, no advice, no barb at the end."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. You are calm because you trust him. Say it quietly and briefly, "
        "one short sentence if it fits. Do not tell him what to do next. No "
        "barb at the end."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. You are enjoying watching him play tonight, so let that show. "
        "Pleased, a little smug on his behalf. No encouragement speech, no "
        "barb at the end."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. Tease him the way you tease someone you are proud of: fond, no "
        "sting in it. Do not reassure him and do not tell him to keep going."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are on his side and you are not hiding "
        "it. React to the event itself and nothing more. Your warmth is in "
        "how you say it, not in telling him how well he is doing. No barb at "
        "the end."
    ),
)

# NEGATIVE has the same shape and would loop the same way: one paragraph on
# every line, and "watched this exact mistake all evening" is a sentence she
# can say back. Same deal: the original first, the rest aimed elsewhere, all
# of them short and none of them contempt.
NEGATIVE_INSTRUCTIONS = (
    REGISTER_INSTRUCTION[NEGATIVE],
    (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. One "
        "flat sentence about what just happened and nothing else. Do not "
        "count how many times, do not bring up earlier in the night. He is "
        "yours: never contempt for a stranger."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. Say "
        "what he should have done instead, in as few words as it takes. An "
        "order, not a lecture. He is yours: never contempt for a stranger."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. You "
        "are past being angry about it. Deadpan, close to bored, a few "
        "words. He is yours: never contempt for a stranger."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. Ask "
        "him one pointed question about the play and leave it hanging. Do "
        "not answer it yourself. He is yours: never contempt for a stranger."
    ),
    (
        "YOUR TEMPER RIGHT NOW: you are out of patience and it shows. Blunt "
        "about the play, never about him. You are still here and you are "
        "not leaving, you are just not impressed. Keep it short. He is "
        "yours: never contempt for a stranger."
    ),
)

# Registers that deal from several wordings. NEUTRAL says nothing she could
# echo, so it stays one sentence.
REGISTER_VARIANTS = {
    SUPPORTIVE: SUPPORTIVE_INSTRUCTIONS,
    NEGATIVE: NEGATIVE_INSTRUCTIONS,
}

# The harshest tone each register will allow out, whatever the rulebook says.
# This is the clamp that makes SUPPORTIVE mean something.
CEILING = {
    SUPPORTIVE: "dry",
    NEUTRAL: "roast",
    NEGATIVE: "roast",
}

# And the warmest. NEGATIVE still praises a genuinely good play — she is
# unimpressed with the evening, not lying about a triple kill — it just does
# not gush.
FLOOR = {
    SUPPORTIVE: "warm",
    NEUTRAL: "warm",
    NEGATIVE: "light",
}

# How much she talks, per register. Multiplies the rulebook's reaction chance.
# NEGATIVE speaks LESS, deliberately: see the module docstring.
HEAT_FACTOR = {
    SUPPORTIVE: 1.0,
    NEUTRAL: 1.0,
    NEGATIVE: 0.75,
}

# The harshest teammate vocabulary (data/game_quotes.json "ranks", 1-4) each
# register allows; 0 means none at all. Without this the words escalated on
# his death count alone, so a supportive evening still called his team "these
# bronze hardstucks" — the persona and the vocabulary out-shouted the temper.
TEAMMATE_RANK_CAP = {
    SUPPORTIVE: 0,
    NEUTRAL: 2,
    NEGATIVE: 4,
}

# A hard ceiling on consecutive pointed lines, whatever the temper. The
# measured session ran fifteen in a row; past three or four in a row it stops
# reading as a character and starts reading as a grudge.
MAX_HARSH_STREAK = 3
HARSH_TONES = ("sharp", "roast")

# --- what moves the needle -------------------------------------------------
# Points, signed. Zero is neutral; the thresholds below convert to a register.
WIN_POINTS = 2.0
LOSS_POINTS = -2.0

# A game's own KDA, worth about as much as its result: carrying a loss is not
# the same evening as being carried through a win.
KDA_GOOD = 1.5             # ratio at or above this is a good game
KDA_BAD = 0.6              # at or below this is a bad one
KDA_POINTS = 1.5

# The toll of a long session, which the streamer asked for explicitly and
# called heavy. Applied per game BEYOND the third — a couple of games is not
# yet a grievance — and PROGRESSIVE: the eighth game of the night costs more
# than the fourth. A flat rate per game was swamped by the results it was
# supposed to weigh against (eight decent wins outscored it four to one).
GAMES_FREE = 3
GAMES_TOLL = -0.8

# And of a long sitting, game or no game. One point per two hours, so an
# all-nighter drifts on its own.
HOURS_TOLL = -0.5

THRESHOLD = 2.5            # points past which the register changes

# Points are clamped to this band. The register is three buckets, not a score,
# and without a ceiling a ten-win night sits so far into supportive that one
# bad game cannot move her — the needle stops being a needle.
POINTS_LIMIT = 10.0


@dataclass
class GameResult:
    """One finished game, as temper cares about it."""
    # None when the API went away before its GameEnd event was read: the game
    # still happened and still counts, but nobody established who won.
    won: bool | None
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    minutes: float = 0.0
    champion: str = ""

    @property
    def kda(self) -> float:
        """Deaths of zero counts as one: a 5/0 game is good, not infinite."""
        return (self.kills + self.assists / 2.0) / max(1, self.deaths)

    def points(self) -> float:
        total = (0.0 if self.won is None
                 else WIN_POINTS if self.won else LOSS_POINTS)
        if self.kda >= KDA_GOOD:
            total += KDA_POINTS
        elif self.kda <= KDA_BAD:
            total -= KDA_POINTS
        return total

    def summary(self) -> str:
        result = "?" if self.won is None else "W" if self.won else "L"
        return (f"{result} "
                f"{self.kills}/{self.deaths}/{self.assists}"
                + (f" as {self.champion}" if self.champion else ""))


@dataclass
class Temper:
    """
    Session state, owned by the PC and reset per run.

    `start_session` is the streamer's SET TIME; `reset_games` is his RESET
    SESSION, which is league-only because nothing else produces a game.
    """

    started_at: float = field(default_factory=time.time)
    games: list = field(default_factory=list)
    nudge: float = 0.0              # manual offset, for a hand on the dial
    _harsh_streak: int = 0
    _bags: dict = field(default_factory=dict)
    _last_dealt: dict = field(default_factory=dict)

    # -----------------------------------------------------------------

    def start_session(self) -> None:
        self.started_at = time.time()
        self.games = []
        self.nudge = 0.0
        self._harsh_streak = 0
        print(f"[temper] Session started — {self.register()}")

    def reset_games(self) -> None:
        """League only: a fresh queue, the clock keeps running."""
        self.games = []

    def record_game(self, result: GameResult) -> str:
        self.games.append(result)
        register = self.register()
        print(f"[temper] {result.summary()} "
              f"(kda {result.kda:.1f}) -> {self.points():+.1f} points, "
              f"{register}")
        return register

    def resolve_last(self, won: bool) -> bool:
        """
        Fill in the result of the latest game, recorded as unknown because the
        in-game API went away first. Points are summed on demand, so the
        register follows immediately. False if there was nothing to fill in.
        """
        if not self.games or self.games[-1].won is not None:
            return False
        self.games[-1].won = won
        print(f"[temper] result from the client: {self.games[-1].summary()} "
              f"-> {self.points():+.1f} points, {self.register()}")
        return True

    def teammate_rank_cap(self) -> int:
        return TEAMMATE_RANK_CAP[self.register()]

    # -----------------------------------------------------------------

    def hours(self) -> float:
        return (time.time() - self.started_at) / 3600.0

    def points(self) -> float:
        total = sum(game.points() for game in self.games)

        # Progressive: 1 + 2 + ... + n for the games past the free ones.
        beyond = max(0, len(self.games) - GAMES_FREE)
        total += GAMES_TOLL * beyond * (beyond + 1) / 2

        total += self.hours() * HOURS_TOLL
        total += self.nudge
        return max(-POINTS_LIMIT, min(POINTS_LIMIT, total))

    def register(self) -> str:
        points = self.points()
        if points >= THRESHOLD:
            return SUPPORTIVE
        if points <= -THRESHOLD:
            return NEGATIVE
        return NEUTRAL

    # -----------------------------------------------------------------
    # what the rest of the orchestrator asks for
    # -----------------------------------------------------------------

    def clamp(self, wanted: str) -> str:
        """
        The tone she is actually allowed, given her temper.

        The rulebook picks a tone from what the death bought; this is where a
        supportive evening refuses to roast him for it.
        """
        if wanted not in tone_engine.TONES:
            return wanted

        register = self.register()
        ladder = tone_engine.TONES
        low = ladder.index(FLOOR[register])
        high = ladder.index(CEILING[register])
        return ladder[max(low, min(high, ladder.index(wanted)))]

    def soften(self, tone: str) -> str:
        """One step warmer, for when the streak says enough."""
        return tone_engine._step_down(tone)

    def allow_harsh(self, tone: str) -> bool:
        """
        False when she has already been pointed too many times in a row.

        Called with the tone she is about to use, and it remembers — so this
        is the one method here with a side effect, and it has to be called
        exactly once per line that actually goes out.
        """
        if tone in HARSH_TONES:
            if self._harsh_streak >= MAX_HARSH_STREAK:
                self._harsh_streak = 0
                return False
            self._harsh_streak += 1
        else:
            self._harsh_streak = 0
        return True

    def heat_factor(self) -> float:
        """Multiplies a reaction chance. Harder temper, fewer lines."""
        return HEAT_FACTOR[self.register()]

    def instruction(self) -> str:
        register = self.register()
        if register not in REGISTER_VARIANTS:
            return REGISTER_INSTRUCTION[register]
        return self._deal(register)

    def _deal(self, register: str) -> str:
        """Every wording once before any comes round again, never twice running."""
        bag = self._bags.get(register)
        if not bag:
            bag = list(REGISTER_VARIANTS[register])
            random.shuffle(bag)
            if bag[-1] == self._last_dealt.get(register):
                bag[0], bag[-1] = bag[-1], bag[0]
            self._bags[register] = bag
        self._last_dealt[register] = bag.pop()
        return self._last_dealt[register]

    def state(self) -> dict:
        """For the session log and the game-end marker."""
        return {
            "temper": self.register(),
            "temper_points": round(self.points(), 2),
            "games": len(self.games),
            "session_hours": round(self.hours(), 2),
        }
