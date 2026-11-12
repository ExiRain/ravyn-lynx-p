"""
What the avatar did in a stream, counted.

    python tools/godot_stats.py                    # newest log in logs/godot/
    python tools/godot_stats.py logs/godot/godot-20261112-203128.jsonl
    python tools/godot_stats.py --json             # the numbers, for a script

Reads the log Godot sends the PC (services/godot_log.py): one record per
action. Nobody can watch her for three hours, so this is how "does she look
alive" becomes numbers — how often she blinks, where she looks and for how
long, which expressions she actually shows, how long the longest stretch
with nothing happening was.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs" / "godot"

# Bookkeeping, not something she did: left out of the quiet-stretch measure.
NOT_ACTIONS = {"avatar_start", "connected", "disconnected", "log_dropped",
               "mood", "tired", "visibility"}


def load(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("t"), (int, float)):
            records.append(record)
    return sorted(records, key=lambda r: r["t"])


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(records: list[dict]) -> dict:
    if not records:
        return {"records": 0}
    start, end = records[0]["t"], records[-1]["t"]
    minutes = max((end - start) / 60.0, 1e-9)
    by_kind = collections.defaultdict(list)
    for r in records:
        by_kind[r["kind"]].append(r)

    def names(kind: str, key: str = "name") -> dict:
        return dict(collections.Counter(
            str(r.get(key)) for r in by_kind[kind]).most_common())

    actions = [r["t"] for r in records if r["kind"] not in NOT_ACTIONS]
    gaps = [b - a for a, b in zip(actions, actions[1:])]
    looks = by_kind["look"]
    look_groups = {}
    for group in sorted({str(r.get("group")) for r in looks}):
        mine = [r for r in looks if str(r.get("group")) == group]
        look_groups[group] = {
            "count": len(mine),
            "mean_s": round(_mean([r.get("duration_s", 0) for r in mine]), 2),
            "presets_used": len({r.get("preset") for r in mine}),
        }
    talks = by_kind["talk_end"]
    blinks = by_kind["blink"]
    return {
        "records": len(records),
        "minutes": round(minutes, 1),
        "per_kind": {k: len(v) for k, v in
                     sorted(by_kind.items(), key=lambda kv: -len(kv[1]))},
        "per_minute": {k: round(len(v) / minutes, 2) for k, v in
                       sorted(by_kind.items(), key=lambda kv: -len(kv[1]))},
        "blinks": {
            "count": len(blinks),
            "per_minute": round(len(blinks) / minutes, 1),
            "double": sum(1 for r in blinks if r.get("double")),
        },
        "looks": look_groups,
        "expressions": names("expression"),
        "micro_expressions": names("micro_expression"),
        "ears": {"perks": len(by_kind["ear_perk"]),
                 "jiggles": names("ear_jiggle", "side")},
        "talking": {
            "lines": len(talks),
            "audio_s": round(sum(r.get("audio_s", 0) for r in talks), 1),
            "share_of_time": round(
                sum(r.get("audio_s", 0) for r in talks) / (minutes * 60), 3),
        },
        "mood": _range(by_kind["mood"]),
        "tired": _range(by_kind["tired"]),
        "quiet": {
            "longest_gap_s": round(max(gaps), 1) if gaps else 0.0,
            "gaps_over_10s": sum(1 for g in gaps if g > 10),
        },
        "disconnects": len(by_kind["disconnected"]),
        "records_dropped": sum(r.get("count", 0) for r in by_kind["log_dropped"]),
    }


def _range(records: list[dict]) -> dict:
    values = [r["value"] for r in records
              if isinstance(r.get("value"), (int, float))]
    if not values:
        return {}
    return {"min": round(min(values), 2), "mean": round(_mean(values), 2),
            "max": round(max(values), 2), "changes": len(values)}


def report(s: dict, name: str) -> str:
    if not s.get("records"):
        return f"{name}: no records"
    out = [f"{name}: {s['records']} records over {s['minutes']} minutes", ""]
    out.append("What she did, per minute:")
    for kind, count in s["per_kind"].items():
        out.append(f"  {kind:<18}{count:>6}   {s['per_minute'][kind]:>6.2f}/min")
    b = s["blinks"]
    out += ["", f"Blinks: {b['per_minute']}/min, {b['double']} of "
                f"{b['count']} double"]
    if s["looks"]:
        out.append("Looks:")
        for group, g in s["looks"].items():
            out.append(f"  {group:<12}{g['count']:>5}   mean {g['mean_s']}s   "
                       f"{g['presets_used']} different targets")
    for title, key in (("Expressions", "expressions"),
                       ("Micro expressions", "micro_expressions")):
        if s[key]:
            out.append(f"{title}: " + ", ".join(
                f"{n} {c}" for n, c in s[key].items()))
    e = s["ears"]
    out.append(f"Ears: {e['perks']} perks, jiggles " + (", ".join(
        f"{side} {c}" for side, c in e["jiggles"].items()) or "none"))
    t = s["talking"]
    out.append(f"Talking: {t['lines']} lines, {t['audio_s']}s of audio "
               f"({t['share_of_time']:.1%} of the time)")
    for key in ("mood", "tired"):
        if s[key]:
            r = s[key]
            out.append(f"{key.capitalize()}: {r['min']} to {r['max']}, "
                       f"mean {r['mean']}, set {r['changes']} times")
    q = s["quiet"]
    out.append(f"Quiet: longest stretch with no action {q['longest_gap_s']}s, "
               f"{q['gaps_over_10s']} stretches over 10s")
    if s["disconnects"] or s["records_dropped"]:
        out.append(f"Connection: {s['disconnects']} disconnects, "
                   f"{s['records_dropped']} records lost while it was down")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("log", nargs="?", help="a godot-*.jsonl file "
                                           "(default: the newest)")
    ap.add_argument("--json", action="store_true", help="print the numbers")
    args = ap.parse_args()

    if args.log:
        path = Path(args.log)
    else:
        logs = sorted(LOG_DIR.glob("godot-*.jsonl"))
        if not logs:
            sys.exit(f"No avatar logs in {LOG_DIR}. They appear once Godot "
                     f"(scripts 1.7 or later) has connected to the PC.")
        path = logs[-1]
    summary = summarise(load(path))
    print(json.dumps(summary, indent=2) if args.json
          else report(summary, path.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
