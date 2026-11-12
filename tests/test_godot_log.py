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
from orchestrator import avatar_review                # noqa: E402

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

    print("\n--- at game end, the review writes itself ---")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "godot"
        log = GodotLog(out)

        def sample(t, req, **kw):
            r = {"t": t, "kind": "state", "voice": True, "focus": True,
                 "group": "USER_FOCUS", "wandering": False,
                 "expression": "NEUTRAL", "micro": False, "mood": 0.1,
                 "tired": 0.0, "eye": [0, 0], "head": [0, 0, 0],
                 "alpha": 1.0, "req_id": req}
            r.update(kw)
            return r

        log.write(json.dumps([sample(1, "a"), sample(1.5, "a"),
                              sample(5, "b", focus=False, wandering=True)]))
        lines = [{"req_id": "a", "outcome": "spoken", "mood": 0.1,
                  "said": "Clean.", "config_key": "MyKill"},
                 {"req_id": "b", "outcome": "spoken", "mood": 0.1,
                  "said": "Baron.", "config_key": "BaronKill"},
                 {"req_id": "c", "outcome": "dropped_gate", "mood": 0.1}]
        path = avatar_review.write_game_review(lines, log.path, out)
        text = path.read_text(encoding="utf-8") if path else ""
        check("a review file is written next to the avatar log",
              path is not None and path.parent == out
              and path.name.startswith("review-"), str(path))
        check("it counts the spoken lines and the ones that were off",
              text.startswith("2 of 2 spoken lines had avatar data; 1 with "
                              "something off."), text[:80])
        check("and lists only the line that was off, with why",
              "Baron." in text and "Clean." not in text
              and "looked at him 0%" in text, text)
        check("no avatar log: nothing written, nothing raised",
              avatar_review.write_game_review(lines, None, out) is None)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
