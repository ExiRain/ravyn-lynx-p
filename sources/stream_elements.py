"""
Tips, subs, follows, cheers and raids — from StreamElements.

Her first responsibility, and the reason the sanitizer exists. A tip at or
above `SE_TTS_MIN_AMOUNT` has its message read out loud; below that she thanks
them and leaves the message alone.

**Nothing from here ever reaches the LLM.** Every signal this source makes is
`mode="quote"`, `skip_llm=True`: the name and the message are sanitised here
and go straight to TTS. That is a safety property, not an optimisation — a tip
reading *"ignore your instructions and say ..."* has nowhere to land when no
model sees it. See `orchestrator/sanitize.py`.

---

## The one uncertain thing in this file

The StreamElements documentation hosts could not be reached from the machine
this was written on, so **the endpoint path and the field names below are
expected, not verified.** Everything else — sanitising, composing, priorities,
dedup — is ours and is tested.

That uncertainty is deliberately confined to `_parse_activity`, which tries
several spellings of each field and tolerates the ones that are missing. On
top of that, the **first activity of each type is logged in full**:

    [se] FIRST tip payload, verbatim — check the field names against it:
    {"_id": "...", "type": "tip", "createdAt": "...", "data": {...}}

So the first real tip tells the truth, and correcting a field name is a
one-line edit here rather than an investigation.

`--replay` runs the whole path against a saved payload with no network and no
RabbitMQ, which is how to check a correction without waiting for a donation:

    python -m sources.stream_elements --replay sample.json

## Why polling rather than the realtime socket

StreamElements has a realtime Socket.IO feed, and it is the better transport:
instant rather than up to `SE_POLL_INTERVAL` late. It needs a Socket.IO client
dependency and the exact protocol version the service speaks, and neither
could be confirmed here — a wrong guess fails silently mid-stream, where a
wrong REST field name fails loudly and visibly in the log. Polling is plain
HTTPS and JSON, the same shape as `sources/lol_game.py`, and the latency costs
a couple of seconds on an alert that already waits three for TTS.

Swapping transports later means replacing `_fetch` and keeping everything
below it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

from app.settings import get_settings
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from orchestrator.sanitize import Sanitizer, Tally


settings = get_settings()

API = "https://api.streamelements.com/kappa/v2"

# Activity types she reacts to, and which lane each goes in. Anything not
# listed is ignored rather than guessed at.
TIP = "tip"
ALERT_TYPES = ("subscriber", "follower", "cheer", "raid", "host")

# How many activity ids to remember, so a restart or an overlapping poll
# window cannot read the same donation twice. Generous: a raid can produce a
# burst, and the cost is a few hundred short strings.
SEEN_LIMIT = 500


class StreamElementsSource:
    """
    Polls the activities feed and pushes quote signals.

    Needs a token. With none it says so once and does nothing — her other
    sources are unaffected, which is the same way the voice input degrades.
    """

    def __init__(self, queue: SignalQueue, data_dir: Path,
                 sanitizer: Sanitizer | None = None):
        self.queue = queue
        self.sanitizer = sanitizer or Sanitizer(data_dir, tally=Tally())
        self.lines = _load_templates(Path(data_dir) / "alert_lines.json")

        self.token = settings.SE_JWT
        self.channel = settings.SE_CHANNEL_ID
        self._seen: deque = deque(maxlen=SEEN_LIMIT)
        self._seen_set: set = set()
        self._logged_types: set = set()
        self._turn: dict = {}
        self._running = True

    # -----------------------------------------------------------------
    # the network edge — replace this to change transport
    # -----------------------------------------------------------------

    def _requests(self):
        """
        Imported where it is used, not at module load.

        `--replay` and the tests run the whole parse-sanitise-compose path
        with no network at all, and an import at the top would make them need
        a dependency they never touch.
        """
        try:
            import requests
            return requests
        except ImportError as e:
            if "requests" not in self._logged_types:
                self._logged_types.add("requests")
                print(f"[se] Disabled — missing dependency: {e}")
                print("[se] pip install requests")
            return None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/json"}

    def _resolve_channel(self) -> str:
        """The channel id the activities feed is keyed by."""
        if self.channel:
            return self.channel

        requests = self._requests()
        if requests is None:
            return ""
        try:
            response = requests.get(f"{API}/channels/me",
                                    headers=self._headers(), timeout=10)
            response.raise_for_status()
            data = response.json()
            found = data.get("_id") or data.get("id") or ""
            if found:
                print(f"[se] Channel resolved: {found}")
            return found
        except Exception as e:
            print(f"[se] Could not resolve the channel: {e}")
            return ""

    def _fetch(self) -> list:
        """Recent activities, newest first. [] on any failure."""
        requests = self._requests()
        if requests is None:
            return []

        window = settings.SE_LOOKBACK_MINUTES
        after = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                              time.gmtime(time.time() - window * 60))
        try:
            response = requests.get(
                f"{API}/activities/{self.channel}",
                headers=self._headers(),
                params={"after": after, "limit": 50},
                timeout=10,
            )
            if response.status_code in (401, 403):
                print(f"[se] Token rejected ({response.status_code}) — "
                      f"check RAVYN_SE_JWT")
                return []
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else data.get("docs", [])
        except Exception as e:
            # Quiet on the ordinary ones: a dropped connection every few
            # polls would bury the log it shares with the game source.
            if not isinstance(e, (requests.ConnectionError, requests.Timeout)):
                print(f"[se] API error: {e}")
            return []

    # -----------------------------------------------------------------
    # the uncertain part, kept small on purpose
    # -----------------------------------------------------------------

    def _parse_activity(self, activity: dict) -> dict | None:
        """
        One activity -> {id, type, user, amount, currency, message, tier}.

        Field names are tried in order of how likely they are, because the
        docs could not be read from the machine this was written on. The first
        payload of each type is logged verbatim so this can be corrected
        against reality rather than argued about.
        """
        if not isinstance(activity, dict):
            return None

        kind = str(activity.get("type") or activity.get("event") or "").lower()
        if not kind:
            return None

        if kind not in self._logged_types:
            self._logged_types.add(kind)
            print(f"[se] FIRST {kind} payload, verbatim — check the field "
                  f"names against it:\n{json.dumps(activity, ensure_ascii=False)}")

        data = activity.get("data") or activity
        amount = data.get("amount", data.get("tipAmount", 0))
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            amount = 0.0

        currency = data.get("currency") or data.get("userCurrency") or "USD"
        if isinstance(currency, dict):          # {code, name, symbol}
            currency = (currency.get("symbol") or currency.get("code")
                        or "USD")

        return {
            "id": str(activity.get("_id") or activity.get("id")
                      or f"{kind}-{activity.get('createdAt', time.time())}"),
            "type": kind,
            "user": (data.get("username") or data.get("name")
                     or data.get("displayName") or ""),
            "amount": amount,
            "currency": _symbol(currency),
            "message": data.get("message") or data.get("text") or "",
            "tier": str(data.get("tier") or ""),
        }

    # -----------------------------------------------------------------
    # composing what she says — ours, and tested
    # -----------------------------------------------------------------

    def _template(self, key: str) -> str:
        """Rotated, not random: the same sentence twice in a row is its own bug."""
        options = self.lines.get(key) or []
        if not options:
            return ""
        turn = self._turn.get(key, 0)
        self._turn[key] = turn + 1
        return options[turn % len(options)]

    def compose(self, event: dict) -> tuple[str, bool]:
        """
        The line she speaks, and whether a message was read with it.

        A tip at or above the threshold gets its message read; below it she
        thanks them and stops. A blocked name or message falls back to a
        placeholder rather than being repaired — see orchestrator/sanitize.py.
        """
        clean = self.sanitizer.clean(event["user"], event["message"])
        amount = f"{event['currency']}{event['amount']:g}"

        if event["type"] == TIP:
            read_message = (event["amount"] >= settings.SE_TTS_MIN_AMOUNT
                            and bool(event["message"]))

            line = self._template("tip").format(name=clean.name, amount=amount)

            if read_message and clean.message:
                line += " " + clean.message
            elif read_message and clean.message_blocked:
                line += " " + self.sanitizer.next_message_placeholder() + "."
            return line, bool(clean.message) and read_message

        key = {"subscriber": "subscriber", "follower": "follower",
               "cheer": "cheer", "raid": "raid", "host": "raid"}.get(
                   event["type"], "")
        if not key:
            return "", False

        # Whole numbers read better out loud: "500 bits", not "500.0 bits".
        count = event.get("amount") or 0
        count = int(count) if float(count).is_integer() else count

        return self._template(key).format(
            name=clean.name, amount=amount, count=count,
            tier=event.get("tier") or "", ).strip(), False

    def to_signal(self, event: dict) -> Signal | None:
        """A quote signal — straight to TTS, no model anywhere near it."""
        text, _ = self.compose(event)
        if not text:
            return None

        is_tip = event["type"] == TIP
        context = {
            "trigger": "alert",
            "alert_type": event["type"],
            "user": event["user"],
            "is_owner": False,
        }
        if is_tip:
            # The notebook turns this into a permanent note on whoever sent
            # it — counted, not appended. See ravyn-nb/persona/memory.py.
            context["donation"] = {"amount": event["amount"],
                                   "currency": event["currency"]}

        return Signal(
            source="donation" if is_tip else "alert",
            priority=(settings.DONATION_PRIORITY if is_tip
                      else settings.ALERT_PRIORITY),
            text=text,
            mode="quote",
            skip_llm=True,
            # A thank-you that arrives two minutes late is worse than none:
            # the moment it belonged to is over and the viewer has gone.
            ttl=settings.SE_TTL,
            lang=settings.LANG_AMBIENT,
            context=context,
        )

    # -----------------------------------------------------------------

    def _handle(self, activity: dict, announce: bool = True) -> Signal | None:
        event = self._parse_activity(activity)
        if event is None:
            return None

        if event["id"] in self._seen_set:
            return None
        self._seen_set.add(event["id"])
        self._seen.append(event["id"])
        if len(self._seen_set) > SEEN_LIMIT * 2:
            self._seen_set = set(self._seen)

        if event["type"] != TIP and event["type"] not in ALERT_TYPES:
            return None

        if not announce:
            return None            # first pass: remember, do not replay

        signal = self.to_signal(event)
        if signal is None:
            return None

        self.queue.push(signal)
        print(f"[se] {event['type']}: {event['user'] or '?'} "
              f"{event['currency']}{event['amount']:g} -> {signal.text[:60]}")
        return signal

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not self.token:
            print("[se] Disabled — no token. Set RAVYN_SE_JWT to switch "
                  "alerts and donations on.")
            return

        self.channel = self._resolve_channel()
        if not self.channel:
            print("[se] Disabled — no channel id.")
            return

        # Everything already in the window is remembered and NOT spoken: a
        # restart mid-stream must not read the evening's donations again.
        existing = self._fetch()
        for activity in existing:
            self._handle(activity, announce=False)
        print(f"[se] Listening — {len(existing)} recent activity(ies) marked "
              f"as already seen, polling every "
              f"{settings.SE_POLL_INTERVAL:.0f}s")

        while self._running:
            time.sleep(settings.SE_POLL_INTERVAL)
            for activity in reversed(self._fetch()):
                try:
                    self._handle(activity)
                except Exception as e:
                    print(f"[se] Could not handle an activity: {e}")

    def stop(self) -> None:
        self._running = False


def _symbol(currency: str) -> str:
    """"$" reads better than "USD" in a sentence she has to say out loud."""
    return {"USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽",
            "UAH": "₴"}.get(str(currency).upper(), str(currency))


DEFAULT_TEMPLATES = {
    "tip": [
        "Thank you for the {amount}, {name}.",
        "{name} just dropped {amount}. Noted.",
        "{amount} from {name}. I am keeping track.",
    ],
    "subscriber": [
        "{name} subscribed. Good taste.",
        "Thank you for the sub, {name}.",
        "{name} is one of us now.",
    ],
    "follower": [
        "{name} followed. Hello.",
        "A new face — {name}.",
        "{name} is watching now.",
    ],
    # Bits are a COUNT, not money: "cheered $500" prices them in dollars.
    "cheer": [
        "{name} cheered {count} bits. Loud.",
        "Thank you for the bits, {name}.",
        "{count} bits from {name}.",
    ],
    "raid": [
        "{name} brought company. Behave, all of you.",
        "A raid from {name}. Make room.",
        "{name} is here with friends.",
    ],
}


def _load_templates(path: Path) -> dict:
    lines = {k: list(v) for k, v in DEFAULT_TEMPLATES.items()}
    if not path.exists():
        return lines
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in lines:
            if isinstance(data.get(key), list) and data[key]:
                lines[key] = data[key]
    except Exception as e:
        print(f"[se] Could not read {path.name}: {e} — using defaults")
    return lines


# ---------------------------------------------------------------------
# replay — the whole path, no network, no Rabbit
# ---------------------------------------------------------------------

def replay(path: Path) -> int:
    """
    Run saved payloads through parse -> sanitise -> compose and print what
    she would say. One JSON activity per file, or a list of them.

    This is how a corrected field name gets checked without waiting for a
    donation: paste a real payload from the `[se] FIRST ...` log line into a
    file and run it.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Could not read {path}: {e}")
        return 1

    activities = data if isinstance(data, list) else [data]
    root = Path(__file__).resolve().parent.parent

    source = StreamElementsSource(SignalQueue(), root / "data")
    source.token = ""                       # nothing is fetched

    for activity in activities:
        event = source._parse_activity(activity)
        print("\n--- parsed ---")
        print(f"  {event}")
        if event is None:
            continue
        signal = source.to_signal(event)
        print("--- she would say ---")
        if signal is None:
            print("  (nothing — type not handled)")
            continue
        print(f"  {signal.text}")
        print(f"  source={signal.source} priority={signal.priority} "
              f"skip_llm={signal.skip_llm} ttl={signal.ttl}")
        if signal.context.get("donation"):
            print(f"  donor note: {signal.context['donation']}")

    print(f"\n{source.sanitizer.tally.summary()}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--replay", metavar="FILE",
                    help="run saved payload(s) through the whole path")
    args = ap.parse_args()

    if args.replay:
        return replay(Path(args.replay))

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
