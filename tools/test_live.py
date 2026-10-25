"""
Run the full alert/promo test sequence against a LIVE app.main process —
real TTS, real Godot, no donations and no waiting on gates.

Needs app.main running with --debug-alerts, and TTS on:

    python -m app.main --debug-alerts

Then, in another terminal:

    python tools/test_live.py

Fires, in order, with a pause between each so you can actually hear her
react to one before the next starts:

    follower                        (good)
    subscriber                      (good)
    tip below SE_TTS_MIN_AMOUNT     (good — thanks only, message NOT read)
    tip at/above SE_TTS_MIN_AMOUNT  (good — message read aloud)
    cheer                           (good)
    raid                            (good)
    promo status                    (shows why she would/would not ask right
                                     now, from the REAL gate — not forced)
    promo: force a follow ask       (good — gates ignored, PromoSource.fire)
    promo: force a subscribe ask    (good — gates ignored, PromoSource.fire)

Pass --bad-name and/or --bad-message to also fire one extra tip with content
you expect your blocklist to catch, to confirm the sanitizer replaces it with
a placeholder instead of reading it verbatim. Nothing is hardcoded here —
paste in whatever you actually want to verify is blocked.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def _post(port: int, path: str, payload: dict) -> dict:
    url = f"http://localhost:{port}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port: int, path: str) -> dict:
    url = f"http://localhost:{port}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _activity(kind: str, user: str, amount: float = 0,
             message: str = "", tier: str = "") -> dict:
    return {
        "_id": f"test_live-{kind}-{user}-{time.time()}",
        "type": kind,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "data": {"username": user, "amount": amount, "currency": "USD",
                 "message": message, "tier": tier},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--port", type=int, default=9000,
                    help="AUDIO_SERVER_PORT the running app.main uses "
                         "(default 9000)")
    ap.add_argument("--delay", type=float, default=5.0,
                    help="seconds to wait between fires, so one finishes "
                         "speaking before the next starts (default 5)")
    ap.add_argument("--bad-name", default="",
                    help="a name you expect the blocklist to catch")
    ap.add_argument("--bad-message", default="",
                    help="a message you expect the blocklist to catch")
    ap.add_argument("--skip-promo", action="store_true",
                    help="alerts only — skip the promo checks")
    args = ap.parse_args()

    steps = [
        ("follower", lambda: _post(args.port, "/debug/alert",
         _activity("follower", "test_follower"))),
        ("subscriber", lambda: _post(args.port, "/debug/alert",
         _activity("subscriber", "test_subscriber", tier="1000"))),
        ("tip (below threshold — thanks only)", lambda: _post(
         args.port, "/debug/alert",
         _activity("tip", "test_tipper_small", amount=1,
                   message="this should not be read aloud"))),
        ("tip (above threshold — message read)", lambda: _post(
         args.port, "/debug/alert",
         _activity("tip", "test_tipper_big", amount=5,
                   message="this should be read aloud"))),
        ("cheer", lambda: _post(args.port, "/debug/alert",
         _activity("cheer", "test_cheerer", amount=500))),
        ("raid", lambda: _post(args.port, "/debug/alert",
         _activity("raid", "test_raider", amount=12))),
    ]

    if args.bad_name:
        steps.append((f"tip with blocked name {args.bad_name!r}",
                      lambda: _post(args.port, "/debug/alert",
                      _activity("tip", args.bad_name, amount=5,
                                message="hello"))))
    if args.bad_message:
        steps.append((f"tip with blocked message {args.bad_message!r}",
                      lambda: _post(args.port, "/debug/alert",
                      _activity("tip", "test_tipper_bad_msg", amount=5,
                                message=args.bad_message))))

    if not args.skip_promo:
        steps.append(("promo status (real gate, not forced)",
                      lambda: _get(args.port, "/debug/promo/status")))
        steps.append(("promo: force a follow ask",
                      lambda: _post(args.port, "/debug/promo",
                                    {"pool": "follow"})))
        steps.append(("promo: force a subscribe ask",
                      lambda: _post(args.port, "/debug/promo",
                                    {"pool": "subscribe"})))

    print(f"Running {len(steps)} steps against localhost:{args.port}, "
          f"{args.delay:.0f}s apart...\n")

    failures = 0
    for i, (label, call) in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {label}")
        try:
            result = call()
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}: {e.read().decode('utf-8')}")
            failures += 1
        except urllib.error.URLError as e:
            print(f"    Could not reach app.main: {e}")
            print("    Is it running with --debug-alerts (and TTS enabled)?")
            return 1
        else:
            if "blocked" in result:        # /debug/promo/status
                state = "BLOCKED" if result["blocked"] else "clear to ask"
                print(f"    {state}"
                      + (f" — {result['reason']}" if result["reason"] else ""))
            elif result.get("fired"):
                print(f"    she said: {result['text']!r}")
            else:
                print(f"    not fired: {result.get('reason', result)}")
                failures += 1

        if i < len(steps):
            time.sleep(args.delay)

    print(f"\n{len(steps) - failures}/{len(steps)} steps fired")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
