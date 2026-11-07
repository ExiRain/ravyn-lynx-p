"""
The one queue everything she says passes through.

    python tests/test_signal_queue.py

Chat, alerts, game events, promos and the silence filler all wait in
SignalQueue, and since alerts stopped expiring (2026-11-06) it can hold
things for a long time. Its three promises, checked against a plain
reference over hundreds of random pushes, pops and clock jumps:

  * the most important waiting signal comes out first (lowest number)
  * ties come out in the order they arrived
  * nothing past its TTL is ever handed out; nothing without one ever expires
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orchestrator.models as models                       # noqa: E402
import orchestrator.priority_queue as pq                   # noqa: E402
from orchestrator.models import Signal                     # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main():
    print("\n--- order and expiry, against a reference ---")
    clock = [1000.0]
    real_time, real_print = models.time.time, getattr(pq, "print", print)
    models.time.time = lambda: clock[0]
    pq.print = lambda *a, **k: None          # expiry notices, not under test
    rng = random.Random(7)
    mismatches, never_expiring_lost = 0, 0
    try:
        for _ in range(300):
            q, waiting, n = pq.SignalQueue(), [], 0
            for _ in range(60):
                if rng.random() < 0.6:
                    s = Signal(source="x", priority=rng.choice([1, 2, 2, 3, 5, 7, 10]),
                               text=str(n), ttl=rng.choice([None, 5, 15, 120]))
                    s.created_at = clock[0]
                    q.push(s)
                    waiting.append((s.priority, n, s))
                    n += 1
                else:
                    got = q.pop()
                    live = [w for w in waiting if not w[2].is_expired()]
                    want = min(live, key=lambda w: (w[0], w[1]))[2] if live else None
                    mismatches += got is not want
                    waiting = [w for w in waiting if w[2] is not got]
                clock[0] += rng.choice([0, 1, 3, 8])
            never_expiring_lost += sum(
                1 for w in waiting if w[2].ttl is None
                and w[2] not in [h[2] for h in q._heap])
    finally:
        models.time.time, pq.print = real_time, real_print

    check("every pop matched the reference (priority, then arrival)",
          mismatches == 0, f"{mismatches} mismatches")
    check("a signal with no TTL is never dropped", never_expiring_lost == 0,
          str(never_expiring_lost))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
