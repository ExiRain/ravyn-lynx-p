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
from orchestrator import session_log
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from orchestrator.sanitize import Sanitizer, Tally


settings = get_settings()

API = "https://api.streamelements.com/kappa/v2"

# Activity types she reacts to, and which lane each goes in. Anything not
# listed is ignored rather than guessed at.
TIP = "tip"
ALERT_TYPES = ("subscriber", "follower", "cheer", "raid", "host")

# What the feed actually calls each type, mapped to the names used here.
# StreamElements sends a follow as "follow" (docs.streamelements.com, channel
# activities). Only "follower" was accepted, so every real follow was parsed,
# found not to be an alert type, and silently dropped — on 2026-11-06 a new
# follower was never greeted. Both spellings are kept for anything older.
TYPE_ALIASES = {
    "follow": "follower",
    "sub": "subscriber",
    "subscription": "subscriber",
    "resub": "subscriber",
    "donation": "tip",
    # The same feed on a YouTube channel.
    "sponsor": "subscriber",
    "superchat": "tip",
}

# Every query parameter StreamElements' own spec marks required for
# GET /activities/{channel} (github.com/StreamElements/api-docs, api.yaml).
# Only after and limit were sent until 2026-11-09, the night a Twitch follow
# went unannounced; if the API enforces the spec, every poll was refused and
# the refusal only ever reached the console. `types` is sent once per value.
ACTIVITY_TYPES = ["follow", "subscriber", "tip", "cheer", "raid", "host",
                  "superchat", "sponsor"]

# More follows than this in one poll are read as one line. Alerts no longer
# expire, so a follow-bot wave of two hundred would otherwise be two hundred
# lines, queued ahead of everything else for the rest of the stream.
FOLLOW_BURST = 3

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
        # "full" (every documented parameter) until the API refuses it, then
        # "minimal" (the old after+limit). Whichever works is recorded.
        self._params_mode = "full"
        self._noted: set = set()

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

    def note(self, state: str, once: bool = True, **fields) -> None:
        """
        What the alerts source is doing, in the console AND the session log.

        Its status used to reach the console only, so a session log with no
        alerts in it could not say whether nobody followed, the token was
        missing, or every poll was being refused. Each distinct state is
        recorded once (errors per status code), so a dead feed does not
        write a line every four seconds.
        """
        key = (state, fields.get("status"))
        if once and key in self._noted:
            return
        self._noted.add(key)
        print(f"[se] {state} {fields if fields else ''}".rstrip())
        session_log.get().mark("alerts", state=state, **fields)

    def _params(self) -> dict:
        now = time.time()
        stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
        after = stamp(now - settings.SE_LOOKBACK_MINUTES * 60)
        if self._params_mode == "minimal":
            return {"after": after, "limit": 50}
        return {"after": after, "before": stamp(now + 60), "limit": 100,
                "mincheer": 0, "minhost": 0, "minsub": 0, "mintip": 0,
                "origin": "feed", "types": ACTIVITY_TYPES}

    def _fetch(self) -> list:
        """Recent activities, newest first. [] on any failure."""
        requests = self._requests()
        if requests is None:
            return []

        try:
            response = requests.get(
                f"{API}/activities/{self.channel}",
                headers=self._headers(),
                params=self._params(),
                timeout=10,
            )
            status = response.status_code
            if status in (401, 403):
                self.note("token_rejected", status=status,
                          hint="check RAVYN_SE_JWT")
                return []
            if status in (400, 422) and self._params_mode == "full":
                # The spec's parameter set refused: say what it said, and
                # fall back to the request that was sent before.
                self.note("full_params_refused", status=status,
                          body=(getattr(response, "text", "") or "")[:300])
                self._params_mode = "minimal"
                return self._fetch()
            if status >= 400:
                self.note("api_error", status=status, mode=self._params_mode,
                          body=(getattr(response, "text", "") or "")[:300])
                return []
            data = response.json()
            self.note("feed_ok", mode=self._params_mode)
            return data if isinstance(data, list) else data.get("docs", [])
        except Exception as e:
            # Quiet on the ordinary ones: a dropped connection every few
            # polls would bury the log it shares with the game source.
            if not isinstance(e, (requests.ConnectionError, requests.Timeout)):
                self.note("api_error", error=str(e)[:200])
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
        kind = TYPE_ALIASES.get(kind, kind)

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
            # A gifted sub names the RECIPIENT as username and the buyer as
            # sender. Thanking the recipient for the gifter's money is wrong,
            # and a 20-gift bomb is 20 activities: grouped by sender in
            # _announce, so it is one thank-you.
            "gifted": bool(data.get("gifted")) or bool(
                data.get("sender") and data.get("sender") != data.get("username")),
            "sender": data.get("sender") or "",
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

        if event["type"] == "gift":
            gifter = self.sanitizer.clean(event["user"], "").name
            return self._template("gift").format(
                name=gifter, count=int(event.get("amount") or 1)).strip(), False

        if event["type"] == "follow_burst":
            return self._template("follow_burst").format(
                name=clean.name, count=int(event.get("amount") or 0)).strip(), False

        key = {"subscriber": "subscriber", "follower": "follower",
               "member": "member",
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
        # The PC's face prep keys on these (services/response_listener.py);
        # without them a real follow or sub never got the surprised face that
        # the mock events did.
        face = {"follower": "follow", "follow_burst": "follow",
                "subscriber": "sub", "gift": "sub", "member": "sub"}.get(event["type"])
        if face:
            context["event_type"] = face
        # A YouTube viewer is keyed by channel id in the notebook's memory,
        # so the donor note lands on them and not on a Twitch namesake.
        if event.get("user_key"):
            context["user_key"] = event["user_key"]
            context["platform"] = event.get("platform", "")
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
            # None: a follow, sub or tip is never allowed to age out of the
            # queue. See SE_TTL.
            ttl=settings.SE_TTL,
            lang=settings.LANG_AMBIENT,
            context=context,
        )

    # -----------------------------------------------------------------

    def _handle(self, activity: dict, announce: bool = True) -> Signal | None:
        event = self._take(activity, log=announce)
        if event is None or not announce:
            return None            # first pass: remember, do not replay
        return self._push(event)

    def _push(self, event: dict) -> Signal | None:
        signal = self.to_signal(event)
        if signal is None:
            return None

        self.queue.push(signal)
        print(f"[se] {event['type']}: {event['user'] or '?'} "
              f"{event['currency']}{event['amount']:g} -> {signal.text[:60]}")
        return signal

    def _take(self, activity: dict, log: bool = True) -> dict | None:
        """Parse and dedupe one activity; the event if it is new and handled."""
        event = self._parse_activity(activity)
        if event is None or event["id"] in self._seen_set:
            return None
        self._seen_set.add(event["id"])
        self._seen.append(event["id"])
        if len(self._seen_set) > SEEN_LIMIT * 2:
            self._seen_set = set(self._seen)
        if event["type"] != TIP and event["type"] not in ALERT_TYPES:
            self.note("ignored_type", type=event["type"])
            return None
        if log:
            self.note("received", once=False, type=event["type"],
                      user=event["user"], amount=event["amount"])
        return event

    def push_external(self, event: dict) -> Signal | None:
        """
        An alert from somewhere other than StreamElements — YouTube's Super
        Chats and memberships (sources/youtube_alerts.py). Same dedupe, same
        sanitiser, same quote-only path.
        """
        if not event.get("id") or event["id"] in self._seen_set:
            return None
        self._seen_set.add(event["id"])
        self._seen.append(event["id"])
        self.note("received", once=False, type=event["type"],
                  user=event.get("user", ""), amount=event.get("amount", 0),
                  platform=event.get("platform", ""))
        try:
            return self._push(event)
        except Exception as e:
            print(f"[se] Could not announce an external alert: {e}")
            return None

    def announce(self, activities: list) -> list:
        """
        One poll's activities, oldest first, into signals.

        Gifted subs are grouped by who bought them and a burst of follows is
        one line; everything else is one line each, in order.
        """
        events = []
        for activity in activities:
            try:
                event = self._take(activity)
            except Exception as e:
                print(f"[se] Could not handle an activity: {e}")
                continue
            if event is not None:
                events.append(event)

        gifts: dict = {}
        follows = [e for e in events if e["type"] == "follower"]
        burst = len(follows) > FOLLOW_BURST
        out = []
        for event in events:
            if event["type"] == "subscriber" and event["gifted"] and event["sender"]:
                gifts.setdefault(event["sender"], []).append(event)
                continue
            if burst and event["type"] == "follower":
                continue
            out.append(event)

        for sender, group in gifts.items():
            out.append({**group[0], "type": "gift", "user": sender,
                        "amount": len(group), "message": ""})
        if burst:
            out.append({**follows[-1], "type": "follow_burst",
                        "amount": len(follows), "message": ""})

        signals = []
        for event in out:
            signal = self._push(event)
            if signal is not None:
                signals.append(signal)
        return signals

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not self.token:
            self.note("disabled_no_token",
                      hint="set RAVYN_SE_JWT to switch alerts and donations on")
            return

        self.channel = self._resolve_channel()
        if not self.channel:
            self.note("disabled_no_channel",
                      hint="set RAVYN_SE_CHANNEL, or check the token")
            return

        # Everything already in the window is remembered and NOT spoken: a
        # restart mid-stream must not read the evening's donations again.
        existing = self._fetch()
        for activity in existing:
            self._handle(activity, announce=False)
        self.note("listening", already_seen=len(existing),
                  poll_s=settings.SE_POLL_INTERVAL)

        while self._running:
            time.sleep(settings.SE_POLL_INTERVAL)
            self.announce(list(reversed(self._fetch())))

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
    # A YouTube channel membership. "Subscribed" means something free there.
    "member": [
        "{name} became a member. Welcome in.",
        "Thank you for the membership, {name}.",
        "{name} is a member now. Good choice.",
    ],
    "gift": [
        "{name} gifted {count} subs. Generous.",
        "{count} gifted subs from {name}. I saw that.",
        "{name} just handed out {count} subs.",
    ],
    "follow_burst": [
        "{count} new followers at once. Hello, all of you.",
        "{count} people just followed. I am watching every one of you.",
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
