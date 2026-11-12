"""
The avatar's actions land on the PC, in logs/godot/.

    python tests/test_godot_log.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import godot_log                       # noqa: E402
from services.godot_log import GodotLog              # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main():
    print("\n--- Godot's LOG: messages are filed under logs/godot/ ---")
    with tempfile.TemporaryDirectory() as tmp:
        log = GodotLog(Path(tmp) / "logs" / "godot")
        batch = [{"t": 1000.0, "kind": "blink", "double": False},
                 {"t": 1001.5, "kind": "look", "group": "WANDERING",
                  "preset": 3, "duration_s": 1.2}]
        check("a batch is written, one line per record",
              log.write(json.dumps(batch)) == 2)
        lines = [json.loads(x) for x in
                 log.path.read_text(encoding="utf-8").splitlines()]
        check("in order, with Godot's own fields kept",
              [r["kind"] for r in lines] == ["blink", "look"]
              and lines[1]["preset"] == 3, str(lines))
        check("Godot's clock is kept and the PC's is added",
              lines[0]["t"] == 1000.0 and lines[0]["pc_t"] > 1000.0
              and lines[0]["iso"].startswith("1970-01-01"), str(lines[0]))
        check("the file is named like the other logs",
              log.path.name.startswith("godot-")
              and log.path.suffix == ".jsonl")
        check("a single record is fine too",
              log.write(json.dumps({"t": 1002.0, "kind": "ear_perk"})) == 1)
        check("a record with no kind is skipped, the rest kept",
              log.write(json.dumps([{"t": 1.0}, "junk",
                                    {"kind": "blink"}])) == 1)
        check("garbage is refused, not raised",
              log.write("not json") == 0 and log.write("42") == 0)
        check("an oversized message is refused",
              log.write("[" + " " * godot_log.MAX_MESSAGE_CHARS + "]") == 0)
        check("nothing was written anywhere else",
              [p.name for p in Path(tmp).rglob("*") if p.is_file()]
              == [log.path.name])

        off = GodotLog(Path(tmp) / "off", enabled=False)
        check("switched off, it writes nothing",
              off.write(json.dumps(batch)) == 0 and not off.path.exists())

    saved, godot_log._LOG = godot_log._LOG, None
    check("write() before init() is safe", godot_log.write("[]") == 0)
    godot_log._LOG = saved

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
