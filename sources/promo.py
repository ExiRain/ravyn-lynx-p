"""
Asking for a follow or a sub — her third alert responsibility.

A promo is the one thing she says that nobody asked for and that has a cost if
it lands badly: mid-teamfight, twice in ten minutes, or over the top of him
explaining something. So this source is almost entirely made of reasons NOT to
speak — and the rules are different in kind between the two streams, not just
different numbers.

**A League stream is measured in games, so the clock does not apply at all.**

    never during a game         he is playing; she is not interrupting it
    1-3 minutes after one ends  the post-game screen, not the instant of defeat
    two games' worth            a 40-minute game is not a 20-minute one, so a
                                game counts double past PROMO_LONG_GAME_MINUTES:
                                two short games earn an ask, one long one earns
                                it alone
    after 4 games, once         she wonders aloud whether the stream is ending,
                                instead of asking for anything

Four or five games a session, an ask after the second and the wondering after
the fourth: one of each, which is about as often as an ask can arrive without
becoming something people tune out.

**A variety stream has no games to count, so the clock is the whole rule** —
once every 50-120 minutes, rolled fresh each time rather than fixed, which is
three or four asks over a five-hour stream.

**Quote signals, no model.** `skip_llm=True`, straight to TTS, so what is in
`data/promo.json` is exactly what the stream hears. A call to action is the
last thing that should be paraphrased by a 9B model — and five lines per pool,
rotated in order, cannot repeat inside an evening the way a generated one can.

It owns no state the rest of her cares about: `game_active` is set from
outside, the same way `sources/silence_filler.py` gets it, and the game count
comes from `orchestrator/temper.py`, which is already counting them.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from app.settings import get_settings
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue


settings = get_settings()

FOLLOW = "follow"
SUBSCRIBE = "subscribe"
END_WONDER = "end_wonder"

DEFAULT_LINES = {
    FOLLOW: ["A follow would be nice. I will pretend not to notice who did it."],
    SUBSCRIBE: ["Subscribe if you want to encourage this."],
    END_WONDER: ["Are we about to end the stream? Or not? Wonders, wonders."],
}


class PromoSource:
    """
    Timer plus gates. Run `run` in a daemon thread.

    `game_active` must be set from outside when there is a game source — see
    `app/main.py`. Left False it behaves as a non-League stream, which is
    correct for one.
    """

    def __init__(self, queue: SignalQueue, data_dir: Path, temper=None):
        self.queue = queue
        self.temper = temper
        self.lines = _load(Path(data_dir) / "promo.json")

        # Set externally. The game source owns the truth about this.
        self.game_active = False

        self._running = True
        self._due = time.time() + self._interval()
        self._turn: dict = {}
        self._games_seen = 0
        self._games_at_last_promo = 0
        self._last_game_end = 0.0
        self._after_game_wait = self._post_game_delay()

        # Alternates, so neither ask crowds the other out. A follow is the
        # cheaper thing to ask for, so it goes first.
        self._next_ask = FOLLOW

        # Once per session. "Are we about to end the stream?" is an
        # observation about the evening, and an observation repeated is a nag.
        self._wondered = False

    # -----------------------------------------------------------------

    def _interval(self) -> float:
        return random.uniform(settings.PROMO_MIN_INTERVAL,
                              settings.PROMO_MAX_INTERVAL)

    def _post_game_delay(self) -> float:
        """Rolled per game: a fixed 90 seconds becomes a tell by game three."""
        return random.uniform(settings.PROMO_AFTER_GAME_MIN,
                              settings.PROMO_AFTER_GAME_MAX)

    def _games(self) -> int:
        return len(self.temper.games) if self.temper else 0

    def _credits(self) -> int:
        """
        How much game has gone by since the last ask, in games' worth.

        A forty-minute game is not a twenty-minute one — the streamer's point:
        two short games earn an ask, and one long game earns it on its own. So
        a game counts double past `PROMO_LONG_GAME_MINUTES`.
        """
        if not self.temper:
            return 0

        total = 0
        for game in self.temper.games[self._games_at_last_promo:]:
            minutes = getattr(game, "minutes", 0.0) or 0.0
            total += 2 if minutes >= settings.PROMO_LONG_GAME_MINUTES else 1
        return total

    def _watch_games(self) -> None:
        """
        Notice a game ending without the game source having to tell us.

        `temper` already records one result per finished game, so the count
        going up IS a game having just ended — and it means this source has no
        second opinion about when that happened.
        """
        count = self._games()
        if count > self._games_seen:
            self._games_seen = count
            self._last_game_end = time.time()
            self._after_game_wait = self._post_game_delay()

    # -----------------------------------------------------------------

    # A reason prefixed with this is the ordinary "not yet", not an
    # obstacle — it is never logged, or the console would carry a line every
    # fifteen seconds for an hour.
    QUIET = "quiet:"

    def _blocked(self, now: float) -> str:
        """Why she is not asking right now, or "" if she may."""
        if settings.LEAGUE_MODE:
            return self._blocked_by_games(now)

        # A variety stream has nothing to count but the clock.
        if now < self._due:
            return f"{self.QUIET}not due for "\
                   f"{(self._due - now) / 60:.0f} min"
        return ""

    def _blocked_by_games(self, now: float) -> str:
        """
        League. The clock does NOT apply here — a League stream is measured in
        games, and an ask that arrives because an hour passed can land in the
        middle of champion select or on a loading screen.
        """
        if self.game_active:
            return f"{self.QUIET}a game is running"

        if not self._games_seen:
            return f"{self.QUIET}no game has finished yet"

        waited = now - self._last_game_end
        if waited < self._after_game_wait:
            return (f"{self.QUIET}only {waited:.0f}s since the game ended "
                    f"(waiting {self._after_game_wait:.0f}s)")

        credits = self._credits()
        if credits < settings.PROMO_GAMES_GAP:
            return (f"{self.QUIET}only {credits} game credit(s) since the "
                    f"last ask")

        return ""

    def _pool(self) -> str:
        """
        Which ask. Past four games she wonders about the end of the stream
        instead — his line, once, because it only makes sense when there have
        been enough games for the question to be real and it stops being an
        observation the second time she makes it.
        """
        if (settings.LEAGUE_MODE and not self._wondered
                and self._games_seen >= settings.PROMO_END_WONDER_AFTER):
            self._wondered = True
            return END_WONDER

        pool = self._next_ask
        self._next_ask = SUBSCRIBE if pool == FOLLOW else FOLLOW
        return pool

    def _line(self, pool: str) -> str:
        options = self.lines.get(pool) or []
        if not options:
            return ""
        turn = self._turn.get(pool, 0)
        self._turn[pool] = turn + 1
        return options[turn % len(options)]

    def build(self, pool: str) -> Signal | None:
        text = self._line(pool)
        if not text:
            return None

        return Signal(
            source="promo",
            priority=settings.PROMO_PRIORITY,
            text=text,
            # Verbatim. A call to action is the last thing to let a 9B model
            # paraphrase, and these lines are the streamer's own writing.
            mode="quote",
            skip_llm=True,
            # Held while he is talking — priority is under
            # VOICE_AMBIENT_PRIORITY so it is not discarded outright — but an
            # ask that waits out two minutes of him explaining something has
            # missed its moment, and another is due in under an hour anyway.
            ttl=settings.PROMO_TTL,
            lang=settings.LANG_AMBIENT,
            context={"trigger": "promo", "promo": pool,
                     "games": self._games_seen},
        )

    def fire(self, pool: str | None = None) -> Signal | None:
        """Push one now, gates ignored. The timer resets as if it had fired."""
        signal = self.build(pool or self._pool())
        if signal is None:
            return None

        self.queue.push(signal)
        self._due = time.time() + self._interval()
        self._games_at_last_promo = self._games_seen

        print(f"[promo] {signal.context['promo']}: {signal.text[:70]}")
        if settings.LEAGUE_MODE:
            print(f"[promo]   next after "
                  f"{settings.PROMO_GAMES_GAP} more game credit(s)")
        else:
            print(f"[promo]   next in "
                  f"{(self._due - time.time()) / 60:.0f} min")
        return signal

    # -----------------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not settings.PROMO_ENABLED:
            print("[promo] Disabled")
            return

        if settings.LEAGUE_MODE:
            print(f"[promo] Active — League: after "
                  f"{settings.PROMO_GAMES_GAP} game credit(s), never during "
                  f"a game, and the clock does not apply")
        else:
            print(f"[promo] Active — every "
                  f"{settings.PROMO_MIN_INTERVAL / 60:.0f}-"
                  f"{settings.PROMO_MAX_INTERVAL / 60:.0f} min, first in "
                  f"{(self._due - time.time()) / 60:.0f} min")

        last_reason = ""
        while self._running:
            time.sleep(settings.PROMO_TICK)
            self._watch_games()

            reason = self._blocked(time.time())
            if reason:
                # The ordinary "not yet" is silent. A real obstacle is said
                # once per reason rather than every tick: knowing WHY she is
                # holding is the difference between a bug and a rule doing its
                # job, and saying it every fifteen seconds buries the log.
                if not reason.startswith(self.QUIET) and reason != last_reason:
                    last_reason = reason
                    print(f"[promo] Holding — {reason}")
                continue

            last_reason = ""
            self.fire()

    def stop(self) -> None:
        self._running = False


def _load(path: Path) -> dict:
    lines = {k: list(v) for k, v in DEFAULT_LINES.items()}
    if not path.exists():
        print(f"[promo] WARNING: {path.name} not found — one fallback line "
              f"per pool")
        return lines
    try:
        data = __import__("json").loads(path.read_text(encoding="utf-8"))
        for key in lines:
            if isinstance(data.get(key), list) and data[key]:
                lines[key] = data[key]
    except Exception as e:
        print(f"[promo] Could not read {path.name}: {e} — using fallbacks")
    return lines
