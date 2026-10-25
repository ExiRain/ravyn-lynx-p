"""
Both halves of one line, side by side.

    python tools/join_logs.py logs/session-x.jsonl worker-y.jsonl
    python tools/join_logs.py session.jsonl worker.jsonl --seq 14

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

The worker log lives on the notebook, so copy it over first:

    scp ravyn@notebook:~/ravyn-lynx/logs/worker-20260922-201500.jsonl .
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


def print_joined(pc: dict, nb: dict | None, full: bool = False) -> None:
    stamp = pc.get("iso", "")[-8:] or pc.get("ts", "")
    tag = knob(pc, "config_key") or pc.get("source", "")
    knobs = "/".join(x for x in (pc.get("angle_id"), knob(pc, "tone"),
                                 pc.get("temper")) if x)

    print(f"\n  {stamp}  {tag}" + (f"  [{knobs}]" if knobs else ""))
    if pc.get("trigger_text"):
        print(f"    trigger : {pc['trigger_text'][:88]}")

    if nb:
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

    why = diagnose(pc, nb)
    if why:
        print(f"    -> {why}")

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("session", nargs="?", help="PC logs/session-*.jsonl")
    ap.add_argument("worker", nargs="?", help="notebook logs/worker-*.jsonl")
    ap.add_argument("--seq", type=int,
                    help="print one line in full — prompt, raw, said")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--similarity", type=float,
                    default=session_metrics.DEFAULT_SIMILARITY)
    args = ap.parse_args()

    session = Path(args.session) if args.session else analyze_session.newest_log()
    if session is None or not session.exists():
        print("No PC session log. Pass one, or run her once.")
        return 1

    if not args.worker:
        print("Also pass the notebook's worker log. It lives on the notebook:\n"
              "  scp ravyn@notebook:~/ravyn-lynx/logs/worker-*.jsonl .")
        return 1

    worker_path = Path(args.worker)
    if not worker_path.exists():
        print(f"No such file: {worker_path}")
        return 1

    pc_records, _ = analyze_session.load(session)
    if not pc_records:
        print(f"{session}: nothing to join")
        return 1

    worker, meta = load_worker(worker_path)
    if not worker:
        print(f"{worker_path}: no worker records with a req_id. An older "
              f"notebook build does not stamp one.")
        return 1

    if args.seq:
        pc = next((r for r in pc_records if r.get("seq") == args.seq), None)
        if pc is None:
            print(f"No line #{args.seq} in {session.name}")
            return 1
        print_joined(pc, worker.get(pc.get("req_id", "")), full=True)
        return 0

    report(pc_records, worker, meta, args.similarity, args.top)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)
