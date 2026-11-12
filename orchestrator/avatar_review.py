"""
Did her avatar act right while she spoke? Checked at every game end.

Godot logs its state twice a second while her voice plays (focus on him,
look group, eyes, head, expression, the mood it holds), stamped with the
line's req_id; services/godot_log.py files it in logs/godot/. When a game
ends, every line she spoke in it is set against what the PC sent for it,
and anything that disagrees is written to

    logs/godot/review-<date>-<time>.txt

with one line in the console saying how many lines were off. Nothing to
run. tools/join_logs.py uses the same checks for a whole session.

    focus      she should look at him for the whole line
    expression the one her mood implies (eyes.gd set_mood: >0.7 SURPRISED,
               <-0.7 ANGRY, <-0.4 SAD, tired >0.7 SLEEPY, else NEUTRAL)
               against the ones she actually showed
    mood       what Godot holds against what was sent
    gaze       how far eyes and head were from straight at him (0 = on him)
    visible    lowest alpha while talking (ghost mode should have her shown)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

FOCUS_MIN = 0.9         # share of talking samples with attention on him
GAZE_MAX = 0.35         # mean eye offset from straight at him, model units
HEAD_MAX = 8.0          # mean head angle offset, degrees
MOOD_SLACK = 0.05


def load_godot(path: Path) -> dict:
    """Records by req_id, in time order."""
    by_id: dict[str, list] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("req_id"):
            by_id.setdefault(record["req_id"], []).append(record)
    for records in by_id.values():
        records.sort(key=lambda r: r.get("t", 0))
    return by_id


def expected_expression(mood: float, tired: float) -> str:
    """What eyes.gd shows for the mood and tired the PC sent."""
    expression = "NEUTRAL"
    if mood > 0.7:
        expression = "SURPRISED"
    elif mood < -0.7:
        expression = "ANGRY"
    elif mood < -0.4:
        expression = "SAD"
    if tired > 0.7:
        expression = "SLEEPY"
    return expression


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def avatar(pc: dict, records: list | None) -> dict | None:
    """Her avatar during this line, and what in it disagrees with the line."""
    if not records:
        return None
    talking = [r for r in records if r.get("kind") == "state" and r.get("voice")]
    starts = [r["t"] for r in records if r.get("kind") == "voice_start"]
    ends = [r["t"] for r in records if r.get("kind") == "voice_end"]
    mood = float(pc.get("mood") or 0.0)
    tired = float(pc.get("tired") or 0.0)
    want = expected_expression(mood, tired)
    shown = []
    for r in talking:
        if r.get("expression") and (not shown or shown[-1] != r["expression"]):
            shown.append(r["expression"])
    out = {
        "samples": len(talking),
        "voice_s": round(ends[-1] - starts[0], 1) if starts and ends else None,
        "focus": round(_mean([1.0 if r.get("focus") else 0.0
                              for r in talking]), 2) if talking else None,
        "wandering": sum(1 for r in talking if r.get("wandering")),
        "groups": sorted({r.get("group") for r in talking if r.get("group")}),
        "expected": want,
        "shown": shown,
        "held_mood": talking[0].get("mood") if talking else None,
        "gaze": round(_mean([sum(abs(v) for v in r.get("eye", [0, 0])) / 2
                             for r in talking]), 2) if talking else None,
        "head": round(_mean([sum(abs(v) for v in r.get("head", [0, 0, 0])) / 3
                             for r in talking]), 1) if talking else None,
        "alpha": min((r.get("alpha", 1.0) for r in talking), default=None),
        "micro": sum(1 for r in talking if r.get("micro")),
    }
    problems = []
    if not talking:
        problems.append("no state while her voice played")
    else:
        if out["focus"] < FOCUS_MIN:
            problems.append(f"looked at him {out['focus']:.0%} of the line")
        if out["wandering"]:
            problems.append(f"idle wandering in {out['wandering']} sample(s) "
                            f"while talking")
        if want not in shown:
            problems.append(f"mood {mood:+.2f} wants {want}, showed "
                            f"{'/'.join(shown) or 'nothing'}")
        if out["held_mood"] is not None and \
                abs(out["held_mood"] - max(-1.0, min(1.0, mood))) > MOOD_SLACK:
            problems.append(f"Godot held mood {out['held_mood']:+.2f}, "
                            f"sent {mood:+.2f}")
        if out["gaze"] > GAZE_MAX:
            problems.append(f"eyes off him by {out['gaze']} on average")
        if out["head"] > HEAD_MAX:
            problems.append(f"head turned {out['head']} deg on average")
        if out["alpha"] is not None and out["alpha"] < 0.95:
            problems.append(f"faded to {out['alpha']:.0%} while talking")
        if out["micro"]:
            problems.append(f"micro expression running in {out['micro']} "
                            f"sample(s) while talking")
    out["problems"] = problems
    return out



def review_text(lines: list[dict], godot: dict) -> tuple[str, int, int]:
    """(the review, lines checked, lines with something off)."""
    spoken = [r for r in lines if r.get("outcome") == "spoken"]
    checked = off = 0
    out = []
    for pc in spoken:
        a = avatar(pc, godot.get(pc.get("req_id", "")))
        if a is None:
            continue
        checked += 1
        if not a["problems"]:
            continue
        off += 1
        stamp = (pc.get("iso") or "")[-8:]
        what = pc.get("config_key") or pc.get("event_type") or pc.get("source", "")
        said = (pc.get("spoken_text") or pc.get("said") or "")[:90]
        out.append(f"{stamp}  {what}  mood {float(pc.get('mood') or 0):+.2f}"
                   f"  tired {float(pc.get('tired') or 0):.2f}")
        out.append(f"  said   : {said}")
        out.append(f"  avatar : focus {a['focus']:.0%}, group "
                   f"{'/'.join(a['groups']) or '-'}, expr "
                   f"{'/'.join(a['shown']) or '-'} (wants {a['expected']}), "
                   f"eyes {a['gaze']} head {a['head']}"
                   if a["samples"] else "  avatar : no state while her voice played")
        out.extend(f"  !  {p}" for p in a["problems"])
        out.append("")
    head = [f"{checked} of {len(spoken)} spoken lines had avatar data; "
            f"{off} with something off.", ""]
    if checked < len(spoken):
        head.insert(1, "(Lines without data: Godot not connected, or older "
                       "than scripts 1.8.)")
    return "\n".join(head + out), checked, off


def write_game_review(lines: list[dict], godot_path: Path | None,
                      out_dir: Path) -> Path | None:
    """The game-end review. Never raises: it is a report, not the stream."""
    try:
        if not godot_path or not Path(godot_path).exists():
            return None
        text, checked, off = review_text(lines, load_godot(Path(godot_path)))
        if not checked:
            print("[avatar] No avatar data for this game's lines")
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / time.strftime("review-%Y%m%d-%H%M%S.txt")
        path.write_text(text, encoding="utf-8")
        print(f"[avatar] {off} of {checked} lines with something off -> {path}")
        return path
    except Exception as e:
        print(f"[avatar] Game review failed: {e}")
        return None
