"""
All three sides of one line, side by side: what she said, what the model was
asked, and what her avatar did while she said it.

    python tools/join_logs.py                     # newest session + its nb and godot logs
    python tools/join_logs.py logs/pc/session-x.jsonl
    python tools/join_logs.py session.jsonl worker.jsonl --seq 14
    python tools/join_logs.py --godot logs/godot/godot-x.jsonl

THE AVATAR. Godot logs its state twice a second while her voice plays —
focus on the viewer, look group, eyes, head, expression, the mood it holds —
stamped with the line's req_id (logs/godot/, sent over the audio WebSocket).
Each line is checked against what the PC sent for it:

    focus      she should look at him for the whole line: share of samples
               with attention on, and any idle wandering while talking
    expression the one her mood implies (eyes.gd set_mood: >0.7 SURPRISED,
               <-0.7 ANGRY, <-0.4 SAD, tired >0.7 SLEEPY, else NEUTRAL)
               against the ones she actually showed
    mood       what Godot holds against what was sent
    gaze       how far eyes and head were from straight at him (0 = on him)
    visible    lowest alpha while talking (ghost mode should have her shown)

The PC records what she SAID and the knobs that produced it. The notebook
records what the model was ASKED — the framed prompt, the seed, the raw output
before the filters, and whether each block actually arrived. Both carry the
same `req_id`, so they line up exactly.

Separately, each file answers half a question. Together they answer the one
that matters, and they answer it mechanically:

    different angles, different seeds, same sentence   the model ignored the
                                                       direction
    the angle never reached the prompt                 plumbing, not the model
    one seed, two identical answers                    the server ignored the
                                                       seed
    her line differs from the raw output               a filter took the part
                                                       that differed

That is the whole tool. It does not re-measure repetition — `analyze_session.py`
does that, and this reads its clusters back to explain them.

The notebook sends its worker log to the PC as it is written, into logs/nb/
(services/log_receiver.py), so the matching one is found on its own — the
worker file sharing the most req_ids with the session. Pass one explicitly
to override.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import session_metrics                           # noqa: E402
from orchestrator.session_metrics import analyse, knob, said       # noqa: E402
from tools import analyze_session                                  # noqa: E402
from orchestrator.avatar_review import (                           # noqa: E402
    FOCUS_MIN, _mean, avatar, expected_expression, load_godot)

ROOT = analyze_session.ROOT


def load_worker(path: Path) -> tuple[dict, dict]:
    """Returns (records by req_id, meta)."""
    by_id: dict[str, dict] = {}
    meta: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "line":
            if record.get("req_id"):
                by_id[record["req_id"]] = record
        elif record.get("kind") == "system_prompt":
            meta["system_prompt"] = record
    return by_id, meta


def diagnose(pc: dict, nb: dict | None) -> str:
    """One line on why this line came out the way it did."""
    if nb is None:
        return "no worker record — restarted mid-session?"

    missing = [name for name, flag in (("angle", "angle_in_prompt"),
                                       ("tone", "tone_in_prompt"),
                                       ("situation", "situation_in_prompt"))
               if flag in nb and not nb[flag]]
    if missing:
        return (f"{', '.join(missing)} chosen but NOT in the prompt — "
                f"plumbing, not the model")

    if nb.get("removed"):
        return f"filters took {', '.join(nb['removed'])} out of this one"

    return ""


def print_joined(pc: dict, nb: dict | None, full: bool = False,
                 avatar_info: dict | None = None, show_model: bool = True,
                 godot_records: list | None = None) -> None:
    stamp = pc.get("iso", "")[-8:] or pc.get("ts", "")
    tag = knob(pc, "config_key") or pc.get("source", "")
    knobs = "/".join(x for x in (pc.get("angle_id"), knob(pc, "tone"),
                                 pc.get("temper")) if x)

    print(f"\n  {stamp}  {tag}" + (f"  [{knobs}]" if knobs else ""))
    if pc.get("trigger_text"):
        print(f"    trigger : {pc['trigger_text'][:88]}")

    if pc.get("mood") is not None or pc.get("tired") is not None:
        print(f"    sent    : mood {float(pc.get('mood') or 0):+.2f}, "
              f"tired {float(pc.get('tired') or 0):.2f}"
              + (f", {pc.get('outcome')}" if pc.get("outcome") else ""))

    if nb and show_model:
        bits = []
        if nb.get("seed") is not None:
            bits.append(f"seed {nb['seed']}")
        if nb.get("llm_s"):
            bits.append(f"{nb['llm_s']}s")
        if nb.get("prompt_chars"):
            bits.append(f"{nb['prompt_chars']} chars")
        for name, flag in (("angle", "angle_in_prompt"),
                           ("tone", "tone_in_prompt")):
            if flag in nb:
                bits.append(f"{name} {'in' if nb[flag] else 'MISSING from'} prompt")
        print(f"    model   : {', '.join(bits)}")

        if nb.get("raw") and nb["raw"].strip() != (pc.get("said") or "").strip():
            print(f"    raw     : {nb['raw'][:88]}")

    print(f"    said    : {said(pc)[:88]}")

    if show_model:
        why = diagnose(pc, nb)
        if why:
            print(f"    -> {why}")

    if avatar_info is not None or godot_records is not None:
        print_avatar(avatar_info, full=full, records=godot_records)

    if full and nb:
        for label, key in (("--- framed prompt", "framed"),
                           ("--- raw output", "raw"),
                           ("--- before filters", "before_filters")):
            if nb.get(key):
                print(f"\n{label}\n")
                print("    " + str(nb[key]).replace("\n", "\n    "))


def report(pc_records: list[dict], worker: dict, meta: dict,
           threshold: float, top: int) -> None:
    matched = [r for r in pc_records if worker.get(r.get("req_id", ""))]
    unmatched = [r for r in pc_records if not worker.get(r.get("req_id", ""))]

    print()
    print("=" * 72)
    print(f"  BOTH SIDES   ({len(matched)} of {len(pc_records)} lines matched "
          f"on req_id)")
    print("=" * 72 + "\n")

    if unmatched:
        print(f"  {len(unmatched)} line(s) with no worker record — a restart "
              f"on one side,\n  or two files from different evenings.\n")

    nbs = [worker[r["req_id"]] for r in matched]

    for name, flag in (("angle", "angle_in_prompt"),
                       ("tone", "tone_in_prompt"),
                       ("situation", "situation_in_prompt")):
        sent = [n for n in nbs if flag in n]
        if sent:
            landed = sum(1 for n in sent if n[flag])
            mark = "" if landed == len(sent) else "   <-- chosen and dropped"
            print(f"  {name:10} reached the prompt : {landed}/{len(sent)}{mark}")

    seeds = [n.get("seed") for n in nbs if n.get("seed") is not None]
    if seeds:
        print(f"  distinct seeds              : {len(set(seeds))}/{len(seeds)}")

    cut = [n for n in nbs if n.get("removed")]
    print(f"  lines a filter changed      : {len(cut)}/{len(nbs)}")
    if "system_prompt" in meta:
        print(f"  system prompt               : "
              f"{meta['system_prompt']['chars']} chars")

    # ---------------------------------------------------------- the repeats
    report_pc = analyse(pc_records, threshold)
    clusters = report_pc["clusters"]
    if not clusters:
        print("\n  No repeats to explain — nothing echoed an earlier line.\n")
        return

    print("\n" + "-" * 72)
    print("  WHAT SHE REPEATED, AND WHAT THE MODEL WAS ASKED FOR")
    print("-" * 72)

    heard = report_pc["heard"]

    for cluster in clusters[:top]:
        print(f"\n  [{cluster['size']}x] "
              + "/".join(sorted(set(k for k in cluster["keys"] if k != "-"))))

        angles, seeds_here, landed_all = set(), set(), True
        for index in cluster["members"]:
            pc = heard[index]
            nb = worker.get(pc.get("req_id", ""))
            angles.add(pc.get("angle_id", "-"))
            if nb:
                seeds_here.add(nb.get("seed"))
                if nb.get("angle_in_prompt") is False:
                    landed_all = False
            stamp = pc.get("iso", "")[-8:]
            seed = nb.get("seed") if nb else "?"
            print(f"      {stamp}  {pc.get('angle_id', '-'):26} "
                  f"seed {str(seed):11} {said(pc)[:44]}")

        print("      -> " + _verdict(angles, seeds_here, landed_all))

    print()


def _verdict(angles: set, seeds: set, landed_all: bool) -> str:
    """The mechanical reading. This is the whole reason to join the files."""
    if not landed_all:
        return ("the angle was chosen and never reached the prompt — "
                "plumbing, not the model")
    if len(seeds) == 1 and seeds != {None}:
        return ("one seed for two answers — the server is ignoring the seed, "
                "not the prompt")
    if len(angles) > 1 and len(seeds) > 1:
        return ("different angles, different seeds, same sentence — the model "
                "ignored the direction")
    if len(angles) == 1:
        return ("the same angle came up twice — the chooser repeated itself, "
                "not the model")
    return "no single explanation; read the prompts with --seq"


# ------------------------------------------------------------------ avatar
# The checks live in orchestrator/avatar_review.py, which also runs them on
# its own at every game end.

def print_avatar(a: dict | None, full: bool = False,
                 records: list | None = None) -> None:
    if a is None:
        print("    avatar  : no Godot record for this line")
        return
    bits = [f"{a['samples']} samples"]
    if a["voice_s"] is not None:
        bits.append(f"voice {a['voice_s']}s")
    if a["focus"] is not None:
        bits.append(f"focus {a['focus']:.0%}")
    if a["groups"]:
        bits.append("group " + "/".join(a["groups"]))
    bits.append(f"expr {'/'.join(a['shown']) or '-'} (wants {a['expected']})")
    if a["gaze"] is not None:
        bits.append(f"eyes {a['gaze']} head {a['head']}")
    print(f"    avatar  : {', '.join(bits)}")
    for p in a["problems"]:
        print(f"    !  {p}")
    if full and records:
        print("\n--- avatar timeline\n")
        t0 = records[0].get("t", 0)
        for r in records:
            extra = {k: v for k, v in r.items()
                     if k not in ("t", "kind", "req_id", "iso", "pc_t")}
            print(f"    +{r.get('t', 0) - t0:6.2f}s  {r.get('kind'):<16} "
                  f"{json.dumps(extra, ensure_ascii=False)[:110]}")


def report_avatar(pc_records: list[dict], godot: dict) -> None:
    spoken = [r for r in pc_records if r.get("outcome") == "spoken"]
    if not spoken:
        return
    joined = [(pc, avatar(pc, godot.get(pc.get("req_id", ""))))
              for pc in spoken]
    seen = [(pc, a) for pc, a in joined if a is not None]

    print("\n" + "-" * 72)
    print("  WHAT HER AVATAR DID WHILE SHE SPOKE")
    print("-" * 72)
    print(f"  spoken lines with a Godot record : {len(seen)}/{len(spoken)}")
    if not seen:
        print("  (Godot scripts 1.8+ log per line; an older build logs nothing"
              " joinable.)\n")
        return

    def count(test) -> int:
        return sum(1 for _, a in seen if test(a))

    focus = [a["focus"] for _, a in seen if a["focus"] is not None]
    print(f"  focus on him, mean               : {_mean(focus):.0%}")
    print(f"  lines below {FOCUS_MIN:.0%} focus            : "
          f"{count(lambda a: a['focus'] is not None and a['focus'] < FOCUS_MIN)}")
    print(f"  lines with idle wandering         : "
          f"{count(lambda a: a['wandering'])}")
    print(f"  lines with the wrong expression   : "
          f"{count(lambda a: a['samples'] and a['expected'] not in a['shown'])}")
    print(f"  lines where Godot's mood differed : "
          f"{count(lambda a: any(p.startswith('Godot held') for p in a['problems']))}")
    print(f"  lines with eyes or head off him   : "
          f"{count(lambda a: any(p.startswith(('eyes', 'head')) for p in a['problems']))}")

    flagged = [(pc, a) for pc, a in seen if a["problems"]]
    if flagged:
        print(f"\n  {len(flagged)} line(s) with something off:")
        for pc, a in flagged:
            print_joined(pc, None, avatar_info=a, show_model=False)
    print()


def matching_godot(pc_records: list) -> Path | None:
    """The logs/godot/ file sharing the most req_ids with this session."""
    wanted = {r.get("req_id") for r in pc_records if r.get("req_id")}
    best, best_hits = None, 0
    for path in sorted((ROOT / "logs" / "godot").glob("godot-*.jsonl")):
        try:
            hits = len(wanted & set(load_godot(path)))
        except OSError:
            continue
        if hits > best_hits:
            best, best_hits = path, hits
    return best


def matching_worker(pc_records: list) -> Path | None:
    """The logs/nb/ file sharing the most req_ids with this session."""
    wanted = {r.get("req_id") for r in pc_records if r.get("req_id")}
    best, best_hits = None, 0
    for path in sorted((ROOT / "logs" / "nb").glob("worker-*.jsonl")):
        hits = 0
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if '"req_id"' in line:
                    try:
                        if json.loads(line).get("req_id") in wanted:
                            hits += 1
                    except ValueError:
                        continue
        except OSError:
            continue
        if hits > best_hits:
            best, best_hits = path, hits
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("session", nargs="?", help="PC logs/session-*.jsonl")
    ap.add_argument("worker", nargs="?", help="notebook logs/worker-*.jsonl")
    ap.add_argument("--seq", type=int,
                    help="print one line in full — prompt, raw, said")
    ap.add_argument("--godot", help="avatar logs/godot/godot-*.jsonl "
                                    "(default: the one sharing the most lines)")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--similarity", type=float,
                    default=session_metrics.DEFAULT_SIMILARITY)
    args = ap.parse_args()

    session = Path(args.session) if args.session else analyze_session.newest_log()
    if session is None or not session.exists():
        print("No PC session log. Pass one, or run her once.")
        return 1

    pc_records, _ = analyze_session.load(session)
    if not pc_records:
        print(f"{session}: nothing to join")
        return 1

    # The avatar log stands on its own: no notebook log is needed for it.
    godot_path = Path(args.godot) if args.godot else matching_godot(pc_records)
    godot = load_godot(godot_path) if godot_path and godot_path.exists() else {}
    if godot_path and godot:
        print(f"Avatar log: {godot_path}")

    worker, meta = {}, {}
    worker_path = Path(args.worker) if args.worker \
        else matching_worker(pc_records)
    if worker_path is None:
        print("No notebook log in logs/nb/ shares a request with this "
              "session. Is the notebook sending it (RAVYN_WORKER_LOG_SHIP)?"
              " Or pass one explicitly.")
    elif not worker_path.exists():
        print(f"No such file: {worker_path}")
        return 1
    else:
        if not args.worker:
            print(f"Notebook log: {worker_path}")
        worker, meta = load_worker(worker_path)
        if not worker:
            print(f"{worker_path}: no worker records with a req_id. An older "
                  f"notebook build does not stamp one.")
    if not worker and not godot:
        return 1

    if args.seq:
        pc = next((r for r in pc_records if r.get("seq") == args.seq), None)
        if pc is None:
            print(f"No line #{args.seq} in {session.name}")
            return 1
        records = godot.get(pc.get("req_id", ""))
        print_joined(pc, worker.get(pc.get("req_id", "")), full=True,
                     avatar_info=avatar(pc, records) if godot else None,
                     godot_records=records if godot else None)
        return 0

    if worker:
        report(pc_records, worker, meta, args.similarity, args.top)
    if godot:
        report_avatar(pc_records, godot)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)
