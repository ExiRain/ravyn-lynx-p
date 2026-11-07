"""
Her idle thoughts do not come round again too soon.

    python tests/test_silence_filler.py

On 2026-11-02 six of ten improv seeds were heard twice in one stream: the
picker chose at random from the least recently used half, so a seed could
return after five others. It is a shuffled deck now.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.priority_queue import SignalQueue        # noqa: E402
from sources.silence_filler import SilenceFiller           # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def gaps(ids):
    return [j - i for i in range(len(ids)) for j in range(i + 1, len(ids))
            if ids[i] == ids[j]]


def main():
    print("\n--- a whole pool before any repeat ---")
    worst = None
    for _ in range(50):
        f = SilenceFiller(SignalQueue(), DATA)
        n = len(f.seeds)
        ids = [f._pick_entry(f.seeds)["id"] for _ in range(n * 4)]
        if len(set(ids[:n])) != n:
            check("every seed once before any repeat", False, str(ids[:n]))
            break
        g = min(gaps(ids))
        worst = g if worst is None else min(worst, g)
    check("every seed is heard once before any is heard twice", True)
    check(f"and across rounds a repeat needs half the pool in between "
          f"({n} seeds)", worst is not None and worst > n // 2, str(worst))
    check("the pool is big enough for a long stream (20+ seeds)",
          len(SilenceFiller(SignalQueue(), DATA).seeds) >= 20)

    f = SilenceFiller(SignalQueue(), DATA)
    quotes = [f._pick_entry(f.quotes)["id"] for _ in range(len(f.quotes))]
    check("the quote pool is dealt the same way", len(set(quotes)) == len(quotes))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
