"""
The measurement itself — what counts as a repeat, and how hot a session ran.

Split out of `tools/analyze_session.py` so the running app can use it too.
The CLI is for reading a session in detail after the fact; the orchestrator
needs the same numbers at game end, in three lines, without anyone typing a
command. Both must agree, which means one implementation.

Pure standard library and pure functions: no I/O, no settings, nothing that
can fail in a way that matters to a live stream.
"""

from __future__ import annotations

import csv
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


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



# ====================================================== the three-line version

# Below this many lines the numbers are noise: one repeat in four lines is
# 25%, and means nothing. A game this short gets its row in the history file
# (it still happened) but no verdict in the console.
MIN_LINES_FOR_VERDICT = 6

HISTORY_COLUMNS = [
    "when", "scope", "lines", "echoes", "repeat_pct", "hot_pct",
    "streak", "harsh_pct", "top_repeat", "worst_key", "angles", "log",
]


def summarise(records: list[dict], threshold: float = DEFAULT_SIMILARITY,
              scope: str = "game", log_name: str = "") -> dict:
    """
    The compact form: what goes in the console at game end and in one row of
    the history file. Same measurement as the full report, fewer words.
    """
    report = analyse(records, threshold)
    heard = report["heard"]

    top_repeat, top_count = "", 0
    if report["phrases"]:
        top_repeat, top_count, _ = report["phrases"][0]

    worst_key, worst_echoes = "", 0
    keys = report["by_knob"]["config_key"]
    if keys:
        worst_key, worst_echoes = keys.most_common(1)[0]

    # How much of the busiest pool was reached — the "she had options and did
    # not take them" number.
    busiest = report["keys"].most_common(1)[0][0] if report["keys"] else ""
    angles_used = angles_total = 0
    if busiest:
        try:
            from orchestrator.game_angles import ANGLES
            pool = ANGLES.get(busiest)
            if pool:
                ids = {a.id for a in pool}
                angles_total = len(ids)
                angles_used = len(ids & set(report["angles"]))
        except Exception:
            pass

    return {
        "when": time.strftime("%Y-%m-%d %H:%M"),
        "scope": scope,
        "lines": len(heard),
        "echoes": sum(c["size"] - 1 for c in report["clusters"]),
        "repeat_pct": round(report["repeat_rate"] * 100),
        "hot_pct": round(report["hot_share"] * 100),
        "streak": report["hot_streak"],
        "harsh_pct": round(report["harsh_tone_share"] * 100),
        "top_repeat": top_repeat,
        "top_repeat_count": top_count,
        "worst_key": worst_key,
        "worst_key_echoes": worst_echoes,
        "busiest_key": busiest,
        "angles": f"{angles_used}/{angles_total}" if angles_total else "",
        "angles_used": angles_used,
        "angles_total": angles_total,
        "log": log_name,
    }


def console_lines(summary: dict) -> list[str]:
    """
    What she prints at game end. Three lines at most, and the third only when
    there is something to point at — a clean game should not look like a
    report with empty fields.
    """
    if not summary["lines"]:
        return ["[session] Nothing said this game."]

    scope = "Game over" if summary["scope"] == "game" else "Session over"
    out = [
        f"[session] {scope}: {summary['lines']} lines, "
        f"{summary['echoes']} echoes ({summary['repeat_pct']}%), "
        f"{summary['hot_pct']}% hot, longest streak {summary['streak']}"
    ]

    if summary["lines"] < MIN_LINES_FOR_VERDICT:
        out.append("[session]   too few lines to read anything into.")
        return out

    # The busiest pool and the one that repeated most are usually the same
    # pool, and naming it twice in one line reads like a bug.
    detail = []
    if summary["angles_total"]:
        detail.append(f"{summary['busiest_key']}: {summary['angles']} angles used")
    if summary["worst_key_echoes"]:
        if detail and summary["worst_key"] == summary["busiest_key"]:
            detail[-1] += f", {summary['worst_key_echoes']} repeats"
        else:
            detail.append(f"{summary['worst_key']} repeated "
                          f"{summary['worst_key_echoes']}x")
    if detail:
        out.append("[session]   " + ", ".join(detail))

    if summary["top_repeat_count"] >= 2:
        out.append(f"[session]   most reused: "
                   f"\"{summary['top_repeat']}\" "
                   f"x{summary['top_repeat_count']}")
    return out


def append_history(summary: dict, path: Path) -> None:
    """
    One row per game, appended to a CSV that outlives every session.

    This is the thing you read when you have not been counting: a column of
    repeat percentages down the weeks says whether a change held, where a
    single session says only what happened that night. The `log` column names
    the file to open when a row looks wrong.

    Never raises — a history write failing must not take a game down with it.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerow(summary)
    except Exception as e:
        print(f"[session] history write failed: {e}")


def read_history(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[session] history read failed: {e}")
        return []
