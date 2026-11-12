"""
The avatar's actions land on the PC, in logs/godot/, and can be counted.

    python tests/test_godot_log.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from services import godot_log                       # noqa: E402
from services.godot_log import GodotLog              # noqa: E402
import godot_stats                                    # noqa: E402

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

    print("\n--- and counted ---")
    records = [{"t": 0.0, "kind": "avatar_start"}]
    records += [{"t": 5.0 * i, "kind": "blink", "double": i % 5 == 0}
                for i in range(1, 25)]                  # two minutes
    records += [
        {"t": 10.0, "kind": "look", "group": "USER_FOCUS", "preset": 1,
         "duration_s": 0.3},
        {"t": 20.0, "kind": "look", "group": "WANDERING", "preset": 2,
         "duration_s": 2.0},
        {"t": 30.0, "kind": "look", "group": "WANDERING", "preset": 4,
         "duration_s": 1.0},
        {"t": 40.0, "kind": "expression", "name": "SURPRISED"},
        {"t": 42.0, "kind": "expression", "name": "NEUTRAL"},
        {"t": 50.0, "kind": "talk_start"},
        {"t": 56.0, "kind": "talk_end", "audio_s": 6.0},
        {"t": 60.0, "kind": "mood", "value": 0.8},
        {"t": 61.0, "kind": "mood", "value": -0.2},
        {"t": 70.0, "kind": "ear_jiggle", "side": "left"},
    ]
    s = godot_stats.summarise(sorted(records, key=lambda r: r["t"]))
    check("blinks per minute", s["blinks"]["per_minute"] == 12.0
          and s["blinks"]["double"] == 4, str(s["blinks"]))
    check("looks by group, with mean length",
          s["looks"]["WANDERING"] == {"count": 2, "mean_s": 1.5,
                                      "presets_used": 2}, str(s["looks"]))
    check("expressions by name",
          s["expressions"] == {"SURPRISED": 1, "NEUTRAL": 1})
    check("how much of the time she was talking",
          s["talking"]["lines"] == 1 and s["talking"]["audio_s"] == 6.0
          and s["talking"]["share_of_time"] == 0.05, str(s["talking"]))
    check("mood range", s["mood"]["min"] == -0.2 and s["mood"]["max"] == 0.8)
    check("the longest stretch with nothing happening",
          s["quiet"]["longest_gap_s"] == 5.0
          and s["quiet"]["gaps_over_10s"] == 0, str(s["quiet"]))
    check("an empty log is not an error",
          godot_stats.summarise([]) == {"records": 0})
    check("and the report prints",
          "Blinks: 12.0/min" in godot_stats.report(s, "godot-x.jsonl"))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
