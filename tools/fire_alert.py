"""
Fire one test alert into a LIVE app.main process — real TTS, real Godot,
no donation needed.

Needs app.main running with --debug-alerts, and TTS on (the endpoint rides
the audio server, which only starts when TTS is enabled):

    python -m app.main --debug-alerts

Then, in another terminal:

    python tools/fire_alert.py follower --user NewViewer
    python tools/fire_alert.py subscriber --user ember_fox --tier 1000
    python tools/fire_alert.py tip --user quietstorm --amount 5 --message "hi"
    python tools/fire_alert.py cheer --user glimmerdash --amount 500
    python tools/fire_alert.py raid --user solarflare --amount 12

Each call gets its own id from the current time, so firing the same type
twice in a row is not silently dropped as "already seen" the way a repeated
real donation id would be.

This hits the same code path --replay does (sources/stream_elements.py
_parse_activity -> to_signal) but pushes onto the actual running queue
instead of printing, so she really speaks it and Godot really reacts.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("type",
                    choices=["follower", "subscriber", "tip", "cheer", "raid"])
    ap.add_argument("--user", default="test_user")
    ap.add_argument("--amount", type=float, default=0)
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--message", default="")
    ap.add_argument("--tier", default="")
    ap.add_argument("--port", type=int, default=9000,
                    help="AUDIO_SERVER_PORT the running app.main uses "
                         "(default 9000)")
    args = ap.parse_args()

    activity = {
        "_id": f"fire_alert-{args.type}-{time.time()}",
        "type": args.type,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "data": {
            "username": args.user,
            "amount": args.amount,
            "currency": args.currency,
            "message": args.message,
            "tier": args.tier,
        },
    }

    url = f"http://localhost:{args.port}/debug/alert"
    body = json.dumps(activity).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"{e.code}: {e.read().decode('utf-8')}")
        return 1
    except urllib.error.URLError as e:
        print(f"Could not reach {url}: {e}")
        print("Is app.main running with --debug-alerts (and TTS enabled)?")
        return 1

    if result.get("fired"):
        print(f"Fired. She'll say: {result['text']!r}")
    else:
        print(f"Not fired: {result.get('reason', result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
