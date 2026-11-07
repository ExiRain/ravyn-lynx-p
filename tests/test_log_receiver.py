"""
The notebook's log lands on the PC, in logs/nb/, line for line.

    python tests/test_log_receiver.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.log_receiver import LogReceiver, queue_arguments  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def msg(name, line):
    return json.dumps({"file": name, "line": line}).encode("utf-8")


def main():
    print("\n--- notebook lines are filed under logs/nb/ ---")
    with tempfile.TemporaryDirectory() as tmp:
        nb = Path(tmp) / "logs" / "nb"
        r = LogReceiver(nb)
        name = "worker-20261106-202558.jsonl"
        first = json.dumps({"kind": "worker_start"})
        second = json.dumps({"kind": "line", "req_id": "abc", "said": "привет"},
                            ensure_ascii=False)
        check("a line is written", r.write(msg(name, first)))
        r.write(msg(name, second))
        lines = (nb / name).read_text(encoding="utf-8").splitlines()
        check("in order, one per line, under the notebook's own name",
              lines == [first, second], str(lines))
        check("unicode survives", "привет" in lines[1])

        for bad in ("../../app/settings.py", "/etc/passwd",
                    "worker-x.jsonl", "session-20261106-202558.jsonl"):
            check(f"a file name like {bad!r} is refused",
                  not r.write(msg(bad, first)))
        check("nothing was written outside logs/nb/",
              sorted(p.name for p in Path(tmp).rglob("*") if p.is_file())
              == [name])
        check("garbage is refused, not raised", not r.write(b"not json"))

    args = queue_arguments()
    check("the queue is capped, oldest dropped first",
          args.get("x-overflow") == "drop-head"
          and args.get("x-max-length", 0) > 0)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
