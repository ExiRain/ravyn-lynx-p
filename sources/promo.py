"""
Asking for a follow or a sub — her third alert responsibility.

A promo is the one thing she says that nobody asked for and that has a cost if
it lands badly: mid-teamfight, twice in ten minutes, or over the top of him
explaining something. So this source is almost entirely made of reasons NOT to
speak, and the streamer's rules are the gates:

    once every 40-80 minutes          rolled fresh each time, never a fixed cadence
    never during a game               he is playing; she is not interrupting it
    1-3 minutes after one ends        the post-game screen, not the instant of defeat
    after every 2nd game              games are short, promos should not track them
    after 4 games, she may wonder     aloud whether the stream is ending

**Quote signals, no model.** `skip_llm=True`, straight to TTS, so what is in
`data/promo.json` is exactly what the stream hears. A call to action is the
last thing that should be paraphrased by a 9B model — and five lines per pool,
rotated in order, cannot repeat inside an evening the way a generated one can.

Outside League none of the game gates apply and only the clock does, which is
what a non-League stream looks like.

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

    def _blocked(self, now: float) -> str:
        """Why she is not asking right now, or "" if she may."""
        if now < self._due:
            return ""           # not an obstacle, just not yet

        if not settings.LEAGUE_MODE:
            return ""           # no games to wait for

        if self.game_active:
            return "a game is running"

        if self._last_game_end:
            waited = now - self._last_game_end
            if waited < self._after_game_wait:
                return (f"only {waited:.0f}s since the game ended "
                        f"(waiting {self._after_game_wait:.0f}s)")

        since = self._games_seen - self._games_at_last_promo
        if self._games_seen and since < settings.PROMO_GAMES_GAP:
            return f"only {since} game(s) since the last one"

        return ""

    def _pool(self) -> str:
        """
        Which ask. After enough games she may wonder about the end of the
        stream instead — his line, and it only makes sense once there have
        been enough games for the question to be real.
        """
        if (settings.LEAGUE_MODE
                and self._games_seen >= settings.PROMO_END_WONDER_AFTER
                and random.random() < settings.PROMO_END_WONDER_CHANCE):
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
        print(f"[promo]   next in {(self._due - time.time()) / 60:.0f} min")
        return signal

    # -----------------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not settings.PROMO_ENABLED:
            print("[promo] Disabled")
            return

        print(f"[promo] Active — every "
              f"{settings.PROMO_MIN_INTERVAL / 60:.0f}-"
              f"{settings.PROMO_MAX_INTERVAL / 60:.0f} min, first in "
              f"{(self._due - time.time()) / 60:.0f} min")

        last_reason = ""
        while self._running:
            time.sleep(settings.PROMO_TICK)
            now = time.time()
            self._watch_games()

            if now < self._due:
                continue

            reason = self._blocked(now)
            if reason:
                # Said once per reason rather than every tick: she is due, and
                # knowing WHY she is holding is the difference between a bug
                # and a rule doing its job.
                if reason != last_reason:
                    last_reason = reason
                    print(f"[promo] Due, holding — {reason}")
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
