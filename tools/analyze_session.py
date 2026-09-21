"""
What she actually said, and how much of it she had already said.

    python tools/analyze_session.py                     # newest logs/*.jsonl
    python tools/analyze_session.py logs/session-x.jsonl
    python tools/analyze_session.py scrollback.txt      # a pasted terminal log
    python tools/analyze_session.py --lines             # the full transcript
    python tools/analyze_session.py --json              # for diffing runs
    python tools/analyze_session.py new.jsonl --compare old.jsonl

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


ROOT = Path(__file__).resolve().parent.parent

# Loose on purpose — see the module docstring. Measured against a live
# session: her four "limit testing" deaths score 0.73-1.00 against each other,
# two answers that open identically and diverge halfway land at 0.52, and the
# closest genuinely different pair in that session sits at 0.48. The line goes
# between the last two.
DEFAULT_SIMILARITY = 0.50

# Content words at the head of a line. Opening the same way twice is what a
# listener notices first, whatever the rest of the sentence does afterwards.
OPENING_WORDS = 5
OPENING_SCORE = 0.75

# A shared run of this many words is a quoted phrase, not a coincidence.
MIN_PHRASE_WORDS = 4
MAX_PHRASE_WORDS = 9

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "is", "are", "was", "were", "be", "been", "it", "its",
    "that", "this", "these", "those", "as", "so", "not", "no", "just",
}

# Words that only appear when she is going at him or his team. Not a morality
# check — a count. The ladder in orchestrator/tone.py hands her the teammate
# vocabulary deliberately; this is how you find out how often it came back.
HEAT_WORDS = {
    "ape", "apes", "piggies", "piggy", "creature", "creatures", "hardstuck",
    "hardstucks", "bronze", "clown", "clowns", "monkey", "monkeys",
    "pathetic", "useless", "garbage", "trash", "braindead", "idiot", "idiots",
    "embarrassing", "shameful", "disgrace", "worthless", "feeding", "feeder",
    "griefing", "inting", "int", "throw", "throwing", "thrown",
}

# Second person aimed squarely at him. Counted separately from the heat words:
# "the apes fed again" is her being rude about strangers, "you walked straight
# into it again" is her being rude to the person listening, and those two wear
# out at very different rates.
AT_HIM = [
    re.compile(p) for p in (
        r'\byou keep\b', r'\byou walked\b', r'\byou died\b', r'\byou think\b',
        r'\byou are (?:not|still|just)\b', r"\byou're (?:not|still|just)\b",
        r'\byou thought\b', r'\byou forgot\b', r'\bdid you\b',
        r'\byou (?:always|never)\b', r'\bstop (?:walking|running|dying|going)\b',
        r'\byou have no\b', r'\byou owe\b',
    )
]

# Standing grievances: lines she is allowed to hold as a position, which is
# exactly why they turn into a catchphrase if nothing is watching them.
GRIEVANCES = [
    re.compile(p) for p in (
        r'games are won', r'low deaths', r'limit test', r'stop walking',
        r'walking straight into', r'grey screen', r'staying alive',
    )
]

_WORD = re.compile(r"[^\w']+", re.UNICODE)


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


def knob(rec: dict, name: str):
    """
    One of the things that produced this line.

    A console-reconstructed record has no chosen tone — the ladder's decision
    is never printed — but the verdict that fed it is, so that stands in.
    Same for the pool key, which the game source prints and the JSONL records
    directly.
    """
    if name == "tone":
        return rec.get("tone") or rec.get("verdict_tone")
    if name == "config_key":
        return rec.get("config_key") or rec.get("event_type")
    return rec.get(name)


def said(rec: dict) -> str:
    """What she said, preferring her full reply over the spoken chunks."""
    return (rec.get("said") or rec.get("spoken_text") or "").strip()


def normalise(text: str) -> str:
    return _WORD.sub(" ", text.lower()).strip()


def words(text: str) -> list[str]:
    return [w for w in normalise(text).split() if w]


# ================================================================== similarity

def similarity(a: list[str], b: list[str]) -> float:
    """
    Order-aware overlap, floored by bag-of-content-words overlap.

    SequenceMatcher alone misses the case that matters most here — the same
    observation with the clauses swapped — and Jaccard alone calls any two
    league reactions similar because they share "you", "the" and "them". Taking
    the larger of the two catches the reorderings without the false positives,
    since the stopwords are stripped before the set is built.
    """
    if not a or not b:
        return 0.0

    seq = SequenceMatcher(None, a, b).ratio()

    content_a = [w for w in a if w not in STOPWORDS]
    content_b = [w for w in b if w not in STOPWORDS]

    ca, cb = set(content_a), set(content_b)
    jaccard = len(ca & cb) / len(ca | cb) if ca and cb else 0.0

    # Same opening, different tail still counts. Live example: "Briar finally
    # got lucky enough to tag one of theirs, I guess" and the same nine words
    # followed by a different second half score 0.52 on the measures above —
    # under any sane threshold — and are heard as her saying it twice.
    opening = 0.0
    if (len(content_a) >= OPENING_WORDS and len(content_b) >= OPENING_WORDS
            and content_a[:OPENING_WORDS] == content_b[:OPENING_WORDS]):
        opening = OPENING_SCORE

    return max(seq, jaccard, opening)


def cluster(lines: list[dict], threshold: float) -> list[list[int]]:
    """
    Group lines that say the same thing. Greedy single-link: a line joins the
    first cluster it matches, which is what "she already said this" means.
    """
    clusters: list[list[int]] = []
    reps: list[list[list[str]]] = []

    for i, rec in enumerate(lines):
        toks = rec["_words"]
        placed = False
        for ci, members in enumerate(reps):
            if any(similarity(toks, other) >= threshold for other in members):
                clusters[ci].append(i)
                members.append(toks)
                placed = True
                break
        if not placed:
            clusters.append([i])
            reps.append([toks])

    return clusters


def phrases(lines: list[dict]) -> list[tuple[str, int, list[int]]]:
    """
    Word runs she used in more than one line, longest and most reused first.

    Counted per line rather than per occurrence: saying "games are won by
    staying alive" twice inside one answer is a rambling line, saying it in six
    answers is a catchphrase, and only the second is what this is looking for.
    """
    seen: dict[tuple, set[int]] = defaultdict(set)

    for i, rec in enumerate(lines):
        toks = rec["_words"]
        for n in range(MIN_PHRASE_WORDS, MAX_PHRASE_WORDS + 1):
            for start in range(len(toks) - n + 1):
                gram = tuple(toks[start:start + n])
                if all(w in STOPWORDS for w in gram):
                    continue
                seen[gram].add(i)

    kept = {g: ls for g, ls in seen.items() if len(ls) >= 2}

    # Keep only maximal phrases: "walking straight into their range" and its
    # own four-word prefix are one finding, not two.
    out = []
    for gram, ls in kept.items():
        longer = any(len(other) > len(gram)
                     and _contains(other, gram)
                     and kept[other] >= ls
                     for other in kept)
        if not longer:
            out.append((" ".join(gram), len(ls), sorted(ls)))

    out.sort(key=lambda x: (-x[1], -len(x[0].split())))
    return out


def _contains(haystack: tuple, needle: tuple) -> bool:
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


# ===================================================================== metrics

def analyse(records: list[dict], threshold: float) -> dict:
    lines = [r for r in records if said(r)]
    for rec in lines:
        rec["_words"] = words(said(rec))

    spoken = [r for r in lines if r.get("outcome") in ("spoken", "unknown", None)]
    heard = spoken or lines

    clusters = cluster(heard, threshold)
    repeated = [c for c in clusters if len(c) > 1]
    echoes = sum(len(c) - 1 for c in repeated)

    report: dict = {
        "records": len(records),
        "with_text": len(lines),
        "outcomes": Counter(r.get("outcome", "unknown") for r in records),
        "sources": Counter(r.get("source", "?") for r in records),
        "truncated": any(r.get("truncated") for r in lines),
        "repeat_rate": (echoes / len(heard)) if heard else 0.0,
        "clusters": [],
        "phrases": phrases(heard)[:40],
        "openers": Counter(" ".join(r["_words"][:4]) for r in heard if r["_words"]),
        "tones": Counter(knob(r, "tone") for r in heard if knob(r, "tone")),
        "angles": Counter(r["angle_id"] for r in heard if r.get("angle_id")),
        "keys": Counter(knob(r, "config_key") for r in heard
                        if knob(r, "config_key")),
        "heard": heard,
    }

    for members in sorted(repeated, key=lambda c: -len(c)):
        recs = [heard[i] for i in members]
        report["clusters"].append({
            "size": len(members),
            "texts": [said(r) for r in recs],
            "when": [r.get("ts") or r.get("iso", "")[-8:] for r in recs],
            "angles": [r.get("angle_id", "-") for r in recs],
            "tones": [knob(r, "tone") or "-" for r in recs],
            "keys": [knob(r, "config_key") or "-" for r in recs],
        })

    # --- attribution: a repeat belongs to whatever produced it -------------
    by_knob: dict[str, Counter] = {"angle_id": Counter(), "tone": Counter(),
                                   "config_key": Counter(), "source": Counter()}
    knob_total: dict[str, Counter] = {k: Counter() for k in by_knob}

    for members in clusters:
        for pos, idx in enumerate(members):
            rec = heard[idx]
            for name in by_knob:
                value = knob(rec, name)
                if value is None:
                    continue
                knob_total[name][value] += 1
                if pos > 0:                 # everything after the first is an echo
                    by_knob[name][value] += 1

    report["by_knob"] = by_knob
    report["knob_total"] = knob_total

    # --- heat --------------------------------------------------------------
    heat_hits = Counter()
    at_him = 0
    grievance = Counter()
    hot_lines = 0

    for rec in heard:
        text = said(rec).lower()
        hits = [w for w in rec["_words"] if w in HEAT_WORDS]
        heat_hits.update(hits)
        aimed = any(p.search(text) for p in AT_HIM)
        if aimed:
            at_him += 1
        for p in GRIEVANCES:
            m = p.search(text)
            if m:
                grievance[m.group(0)] += 1
        rec["_heat"] = len(hits) + (1 if aimed else 0)
        if rec["_heat"]:
            hot_lines += 1

    report["heat_words"] = heat_hits
    report["at_him"] = at_him
    report["grievances"] = grievance
    report["hot_lines"] = hot_lines
    report["hot_share"] = (hot_lines / len(heard)) if heard else 0.0
    report["hot_streak"] = _longest_streak(heard)

    harsh = sum(n for tone, n in report["tones"].items()
                if tone in ("sharp", "roast"))
    report["harsh_tone_share"] = (harsh / sum(report["tones"].values())
                                  if report["tones"] else 0.0)

    return report


def _longest_streak(lines: list[dict]) -> int:
    best = run = 0
    for rec in lines:
        run = run + 1 if rec.get("_heat") else 0
        best = max(best, run)
    return best


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
    ap.add_argument("--compare", metavar="OLDER",
                    help="print this session's headline numbers against an "
                         "earlier one — did the change help?")
    args = ap.parse_args()

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
