"""
What she actually said, and how much of it she had already said.

    python tools/analyze_session.py                     # newest logs/*.jsonl
    python tools/analyze_session.py logs/session-x.jsonl
    python tools/analyze_session.py scrollback.txt      # a pasted terminal log
    python tools/analyze_session.py --lines             # the full transcript
    python tools/analyze_session.py --json              # for diffing runs
    python tools/analyze_session.py new.jsonl --compare old.jsonl
    python tools/analyze_session.py --history          # every session so far

"She felt repetitive" is not something you can act on, and neither is a
scrollback that shows the first fifty characters of every line. This turns a
session into numbers that move when a prompt, an angle pool or a tone ladder
changes:

    repeat rate     share of her lines that echo an earlier line this session
    phrase reuse    the exact wordings she keeps coming back to, with counts
    knobs           which angle_id / tone / config_key produced the repeats
    heat            how much of the session was aimed at him, and how hard

The repeat rate is the headline. Everything else exists to answer the next
question — *which knob do I turn* — because a repetition number with no
attribution just tells you again that she felt repetitive.

Similarity is deliberately loose (0.50 by default). She is supposed to rephrase
rather than repeat, and the failure this measures is a model that varies four
words and says the same thing; a strict threshold would call that two lines.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import console_import                                    # noqa: E402
from orchestrator import session_metrics                            # noqa: E402

# The measurement lives in orchestrator/session_metrics.py so the running app
# can print the same numbers at game end without importing a CLI. This module
# is the reading-it-in-detail half: loading, the long report, comparison.
from orchestrator.session_metrics import (                          # noqa: E402,F401
    DEFAULT_SIMILARITY, HEAT_WORDS, STOPWORDS,
    analyse, cluster, knob, normalise, phrases, said, similarity, words,
)


ROOT = Path(__file__).resolve().parent.parent



# ===================================================================== loading

def load(path: Path) -> tuple[list[dict], str]:
    """Returns (records, kind). Accepts JSONL or terminal scrollback."""
    if path.suffix == ".jsonl":
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "line":
                records.append(rec)
        return records, "session log"

    return console_import.parse_file(path), "console scrollback"


def newest_log() -> Path | None:
    logs = sorted((ROOT / "logs").glob("session-*.jsonl"))
    return logs[-1] if logs else None




# ====================================================================== report

def bar(share: float, width: int = 24) -> str:
    filled = int(round(share * width))
    return "#" * filled + "." * (width - filled)


def print_report(report: dict, source_name: str, kind: str, top: int,
                 threshold: float) -> None:
    heard = report["heard"]

    print()
    print("=" * 72)
    print(f"  {source_name}  ({kind})")
    print("=" * 72)

    print(f"\n  lines dispatched : {report['records']}")
    print(f"  lines with text  : {report['with_text']}")
    outcomes = ", ".join(f"{k} {v}" for k, v in report["outcomes"].most_common())
    print(f"  outcomes         : {outcomes or '-'}")
    sources = ", ".join(f"{k} {v}" for k, v in report["sources"].most_common())
    print(f"  sources          : {sources or '-'}")
    if report["truncated"]:
        print("\n  NOTE: reconstructed from console output — her lines are cut")
        print("        at 50 characters, so every comparison below is a")
        print("        comparison of prefixes. Run with the JSONL log for the")
        print("        real thing.")

    # ---------------------------------------------------------- repetition
    print("\n" + "-" * 72)
    print(f"  REPETITION   (similarity >= {threshold:.2f})")
    print("-" * 72)
    rate = report["repeat_rate"]
    print(f"\n  repeat rate      : {rate:6.1%}  {bar(rate)}")
    print(f"  repeated groups  : {len(report['clusters'])}")

    if report["clusters"]:
        print("\n  what she said more than once:\n")
        for c in report["clusters"][:top]:
            tag = "/".join(sorted(set(k for k in c["keys"] if k != "-"))) or "-"
            print(f"  [{c['size']}x] {tag}")
            for text, when, angle, tone in zip(c["texts"], c["when"],
                                               c["angles"], c["tones"]):
                stamp = when or "--:--:--"
                print(f"        {stamp}  ({angle}/{tone})  {text[:88]}")
            print()

    if report["phrases"]:
        print("  wordings she keeps returning to:\n")
        for text, count, _ in report["phrases"][:top]:
            print(f"    {count}x  \"{text}\"")
        print()

    repeated_openers = [(o, n) for o, n in report["openers"].most_common()
                        if n > 1]
    if repeated_openers:
        print("  repeated openings (first four words):\n")
        for opener, count in repeated_openers[:top]:
            print(f"    {count}x  {opener}...")
        print()

    # ---------------------------------------------------------------- knobs
    print("-" * 72)
    print("  KNOBS   (echo = a line that repeated something said earlier)")
    print("-" * 72)
    for knob in ("config_key", "angle_id", "tone", "source"):
        totals = report["knob_total"][knob]
        if not totals:
            continue
        echoes = report["by_knob"][knob]
        rows = sorted(totals.items(), key=lambda kv: (-echoes[kv[0]], -kv[1]))
        print(f"\n  by {knob}:")
        for value, used in rows[:top]:
            e = echoes[value]
            flag = "  <-- stale" if e and e >= used / 2 else ""
            print(f"    {value:28} used {used:3}   echoes {e:3}{flag}")

    if report["angles"]:
        print(f"\n  distinct angles used: {len(report['angles'])}"
              f" over {sum(report['angles'].values())} game lines")
        _print_unused(report["angles"], report["keys"])

    # ----------------------------------------------------------------- heat
    print("\n" + "-" * 72)
    print("  HEAT   (how much of it was aimed at him, and how hard)")
    print("-" * 72)
    share = report["hot_share"]
    print(f"\n  lines at him     : {report['at_him']} of {len(heard)}")
    print(f"  lines with heat  : {report['hot_lines']:3}  {share:6.1%}  {bar(share)}")
    print(f"  longest streak   : {report['hot_streak']} consecutive")
    if report["tones"]:
        print(f"  harsh tones      : {report['harsh_tone_share']:.1%} "
              f"(sharp + roast of {sum(report['tones'].values())} game lines)")
        tones = ", ".join(f"{k} {v}" for k, v in report["tones"].most_common())
        print(f"  tone spread      : {tones}")
    if report["heat_words"]:
        hits = ", ".join(f"{w} {n}" for w, n in report["heat_words"].most_common(12))
        print(f"  vocabulary       : {hits}")
    if report["grievances"]:
        print("\n  standing grievances she came back to:")
        for phrase, count in report["grievances"].most_common(top):
            print(f"    {count}x  \"{phrase}\"")

    print("\n" + "=" * 72)
    _verdict(report)
    print("=" * 72 + "\n")


def _print_unused(used: Counter, per_event: Counter) -> None:
    """
    How much of each angle pool the session actually reached.

    A pool of twelve that hands out the same three is the repetition finding
    the cluster list cannot make on its own — the lines differ, the direction
    behind them does not. Silent if the pools cannot be imported (an older
    checkout, or the file run from somewhere else).
    """
    try:
        from orchestrator.game_angles import ANGLES, THEME_ANGLES
    except Exception:
        return

    rows = []
    for event_type, pool in sorted(ANGLES.items()):
        ids = {a.id for a in pool}
        seen = ids & set(used)
        if seen:
            rows.append((event_type, len(seen), len(ids),
                         per_event.get(event_type, 0)))

    if not rows:
        return

    print("\n  angle pools reached:")
    for event_type, seen, total, fired in rows:
        # Narrow means she had room to vary and did not: the pool was drawn
        # from repeatedly and kept landing on the same few. A pool used once
        # because the event happened once is not a finding.
        flag = "  <-- narrow" if fired >= 4 and seen <= fired / 2 else ""
        print(f"    {event_type:20} {seen:2}/{total:<3} angles over "
              f"{fired:2} lines{flag}")

    theme_used = set(used) & set(THEME_ANGLES)
    if theme_used:
        print(f"    {'(theme angles)':20} {len(theme_used):2}/"
              f"{len(THEME_ANGLES):<3} used")


def _verdict(report: dict) -> None:
    """The two or three sentences worth reading if nothing else is."""
    rate = report["repeat_rate"]
    if rate >= 0.25:
        print(f"  {rate:.0%} of her lines echoed an earlier one. That is the "
              f"thing to fix.")
    elif rate >= 0.12:
        print(f"  {rate:.0%} echo rate — noticeable on a long session.")
    else:
        print(f"  {rate:.0%} echo rate — she is not repeating herself much.")

    stale = [(v, n) for v, n in report["by_knob"]["config_key"].most_common(3) if n]
    if stale:
        names = ", ".join(f"{v} ({n})" for v, n in stale)
        print(f"  Most of it came through: {names}.")

    if report["hot_share"] >= 0.6:
        print(f"  {report['hot_share']:.0%} of her lines were aimed at him with "
              f"heat, {report['hot_streak']} of them in a row at the worst.")


# ======================================================================== main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("path", nargs="?", help="session .jsonl, or a console log")
    ap.add_argument("--top", type=int, default=12, help="rows per section")
    ap.add_argument("--similarity", type=float, default=DEFAULT_SIMILARITY,
                    help=f"repeat threshold 0-1 (default {DEFAULT_SIMILARITY})")
    ap.add_argument("--lines", action="store_true",
                    help="print the whole transcript and stop")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--history", action="store_true",
                    help="the running table of every game, from logs/history.csv")
    ap.add_argument("--compare", metavar="OLDER",
                    help="print this session's headline numbers against an "
                         "earlier one — did the change help?")
    args = ap.parse_args()

    if args.history:
        print_history(ROOT / "logs" / "history.csv")
        return 0

    path = Path(args.path) if args.path else newest_log()
    if path is None:
        print("No session logs yet. Run her once — logs/session-*.jsonl is "
              "written from startup — or pass a saved console log.")
        return 1
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    records, kind = load(path)
    if not records:
        print(f"{path}: nothing to analyse")
        return 1

    if args.lines:
        _print_transcript(records)
        return 0

    report = analyse(records, args.similarity)

    if args.json:
        print(json.dumps(_jsonable(report), ensure_ascii=False, indent=2))
        return 0

    if args.compare:
        other = Path(args.compare)
        if not other.exists():
            print(f"No such file: {other}")
            return 1
        older, _ = load(other)
        print_comparison(analyse(older, args.similarity), str(other),
                         report, str(path))
        return 0

    print_report(report, str(path), kind, args.top, args.similarity)
    return 0


def print_history(path: Path) -> None:
    """
    The table he asked for: one row per game, oldest first.

    A single session says what happened that night. A column of repeat
    percentages down three weeks says whether a change held — and an outlier
    row names the log file to open and hand over.
    """
    rows = session_metrics.read_history(path)
    if not rows:
        print(f"No history yet ({path}). It fills in one row per game.")
        return

    print()
    print(f"  {'when':16} {'scope':8} {'lines':>5} {'repeat':>7} {'hot':>5} "
          f"{'streak':>6} {'angles':>7}  {'most reused':38} log")
    print("  " + "-" * 118)
    for row in rows:
        print(f"  {row.get('when',''):16} {row.get('scope',''):8} "
              f"{row.get('lines',''):>5} {row.get('repeat_pct','')+'%':>7} "
              f"{row.get('hot_pct','')+'%':>5} {row.get('streak',''):>6} "
              f"{row.get('angles',''):>7}  "
              f"{(row.get('top_repeat','') or '-')[:38]:38} {row.get('log','')}")
    print()

    games = [r for r in rows if r.get("scope") == "game"
             and (r.get("repeat_pct") or "").isdigit()]
    if len(games) >= 2:
        first, last = int(games[0]["repeat_pct"]), int(games[-1]["repeat_pct"])
        every = [int(r["repeat_pct"]) for r in games]
        print(f"  {len(games)} games: repeat rate {first}% -> {last}%, "
              f"average {sum(every) // len(every)}%")
        print()


def print_comparison(before: dict, before_name: str,
                     after: dict, after_name: str) -> None:
    """
    Two sessions, the same four numbers. This is the loop: change one thing,
    stream, compare. Sessions differ in length and in how the game went, so
    everything here is a share rather than a count.
    """
    rows = [
        ("lines with text", before["with_text"], after["with_text"], "{:.0f}"),
        ("repeat rate", before["repeat_rate"], after["repeat_rate"], "{:.1%}"),
        ("repeated groups", len(before["clusters"]), len(after["clusters"]),
         "{:.0f}"),
        ("lines with heat", before["hot_share"], after["hot_share"], "{:.1%}"),
        ("longest heat streak", before["hot_streak"], after["hot_streak"],
         "{:.0f}"),
        ("harsh tone share", before["harsh_tone_share"],
         after["harsh_tone_share"], "{:.1%}"),
    ]

    print()
    print("=" * 72)
    print(f"  before : {before_name}")
    print(f"  after  : {after_name}")
    print("=" * 72 + "\n")

    for label, old_v, new_v, fmt in rows:
        arrow = "  " if new_v == old_v else ("down" if new_v < old_v else "up")
        print(f"  {label:22} {fmt.format(old_v):>8}  ->  "
              f"{fmt.format(new_v):>8}   {arrow}")

    gone = set(before["grievances"]) - set(after["grievances"])
    new_ones = set(after["grievances"]) - set(before["grievances"])
    if gone:
        print(f"\n  dropped a catchphrase : {', '.join(sorted(gone))}")
    if new_ones:
        print(f"  picked one up         : {', '.join(sorted(new_ones))}")
    print()


def _print_transcript(records: list[dict]) -> None:
    for rec in records:
        text = said(rec)
        if not text:
            continue
        stamp = rec.get("ts") or rec.get("iso", "")[-8:] or "--:--:--"
        tag = knob(rec, "config_key") or rec.get("source", "")
        knobs = "/".join(x for x in (rec.get("angle_id"), knob(rec, "tone"))
                         if x)
        outcome = rec.get("outcome", "")
        head = f"{stamp}  {tag}" + (f"  [{knobs}]" if knobs else "")
        if outcome and outcome != "spoken":
            head += f"  ({outcome})"
        print(f"\n{head}")
        if rec.get("trigger_text"):
            print(f"  <- {rec['trigger_text']}")

        # One chunk per line: a console-reconstructed record is a list of
        # fifty-character prefixes, and running them together reads as one
        # broken sentence rather than as what she actually said.
        chunks = [c["text"] for c in (rec.get("sentences") or [])]
        if chunks and rec.get("truncated"):
            for chunk in chunks:
                print(f"     {chunk}")
        else:
            print(f"  {text}")


def _jsonable(report: dict) -> dict:
    out = {}
    for key, value in report.items():
        if key in ("heard",):
            continue
        if isinstance(value, Counter):
            out[key] = dict(value.most_common())
        elif isinstance(value, dict) and all(isinstance(v, Counter)
                                             for v in value.values()):
            out[key] = {k: dict(v.most_common()) for k, v in value.items()}
        else:
            out[key] = value
    return out


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # piped into head/more — not an error
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)
