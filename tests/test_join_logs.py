"""
Both halves of one line, and the reading they give together.

    python tests/test_join_logs.py

The PC knows what she said and which angle produced it. The notebook knows
what the model was asked and with which seed. Separately each answers half the
question; joined on `req_id` they answer it mechanically, and the four readings
below are the whole reason the tool exists:

    different angles, different seeds, same sentence   the model ignored it
    the angle never reached the prompt                 plumbing, not the model
    one seed, two identical answers                    the server ignored the seed
    her line differs from the raw output               a filter took the difference

The bug this file exists to prevent: the first version looked members up by
their own text, so two lines that repeated each other VERBATIM collapsed into
one record and it reported "one seed for two answers" about two different
seeds. Confidently wrong is worse than silent, so every reading here is
asserted against a fixture built to produce it.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.session_metrics import DEFAULT_SIMILARITY, analyse  # noqa: E402
from tools import join_logs                                        # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


SAME = ("You're outpacing these little piggies, Caitlyn, and everyone else "
        "is still at zero.")
OTHER = "Briar is down again, which surprises nobody at this point."


def pc_line(seq: int, req_id: str, angle: str, text: str,
            key: str = "MyKill") -> dict:
    return {"kind": "line", "seq": seq, "req_id": req_id, "source": "game",
            "iso": f"2026-09-22T20:{20 + seq}:00", "config_key": key,
            "angle_id": angle, "tone": "warm", "temper": "neutral",
            "trigger_text": "Deleted.", "said": text, "outcome": "spoken"}


def nb_line(req_id: str, seed: int, raw: str, angle_in: bool = True,
            removed=None) -> dict:
    return {"kind": "line", "req_id": req_id, "seed": seed, "llm_s": 3.0,
            "prompt_chars": 6800, "angle_in_prompt": angle_in,
            "tone_in_prompt": True, "situation_in_prompt": True,
            "framed": "SITUATION ... YOUR ANGLE THIS TIME: ...",
            "raw": raw, "removed": list(removed or [])}


def write(directory: Path, pc: list, nb: list) -> tuple[Path, Path]:
    pc_path = directory / "session-test.jsonl"
    nb_path = directory / "worker-test.jsonl"
    pc_path.write_text("\n".join(json.dumps(r) for r in pc) + "\n",
                       encoding="utf-8")
    nb_path.write_text("\n".join(json.dumps(r) for r in nb) + "\n",
                       encoding="utf-8")
    return pc_path, nb_path


# ==================================================================== loading
def test_loading_and_matching():
    print("\n--- the two files line up on req_id ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        pc = [pc_line(1, "a1", "my_kill_clean", SAME),
              pc_line(2, "a2", "my_kill_expected", OTHER)]
        nb = [{"kind": "worker_start"},
              {"kind": "system_prompt", "chars": 6200, "text": "You are Ravyn."},
              nb_line("a1", 11, SAME)]
        _, nb_path = write(tmp, pc, nb)

        worker, meta = join_logs.load_worker(nb_path)
        check("worker lines are keyed by req_id", set(worker) == {"a1"},
              str(set(worker)))
        check("the system prompt comes back as meta",
              meta["system_prompt"]["chars"] == 6200)
        check("a line with no worker record is simply unmatched",
              worker.get("a2") is None)
        check("and says so rather than guessing",
              "no worker record" in join_logs.diagnose(pc[1], None))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =================================================================== readings
def verdict_for(pc: list, nb: list) -> str:
    """The reading the tool gives for the first repeated group."""
    report = analyse(pc, DEFAULT_SIMILARITY)
    cluster = report["clusters"][0]
    heard = report["heard"]
    worker = {r["req_id"]: r for r in nb if r.get("kind") == "line"}

    angles, seeds, landed = set(), set(), True
    for index in cluster["members"]:
        record = heard[index]
        angles.add(record.get("angle_id", "-"))
        other = worker.get(record.get("req_id", ""))
        if other:
            seeds.add(other.get("seed"))
            if other.get("angle_in_prompt") is False:
                landed = False
    return join_logs._verdict(angles, seeds, landed)


def test_the_model_ignored_the_direction():
    print("\n--- two angles, two seeds, one sentence ---")
    pc = [pc_line(1, "a1", "my_kill_outclassing_team", SAME),
          pc_line(2, "a2", "my_kill_clean", SAME)]
    nb = [nb_line("a1", 1551, SAME), nb_line("a2", 9921, SAME)]

    report = analyse(pc, DEFAULT_SIMILARITY)
    check("the two identical lines are one group of two",
          [c["size"] for c in report["clusters"]] == [2])
    check("and the group holds TWO members, not one deduplicated by text",
          len(report["clusters"][0]["members"]) == 2,
          str(report["clusters"][0]["members"]))

    check("the reading blames the model",
          "ignored the direction" in verdict_for(pc, nb),
          verdict_for(pc, nb))


def test_the_angle_never_arrived():
    print("\n--- the angle was chosen and dropped ---")
    pc = [pc_line(1, "a1", "ally_death_bleeding", OTHER, key="AllyDeath"),
          pc_line(2, "a2", "ally_death_while_behind", OTHER, key="AllyDeath")]
    nb = [nb_line("a1", 7, OTHER, angle_in=False),
          nb_line("a2", 8, OTHER, angle_in=False)]
    check("the reading blames the plumbing, not the model",
          "plumbing" in verdict_for(pc, nb), verdict_for(pc, nb))


def test_the_server_ignored_the_seed():
    print("\n--- one seed, two answers ---")
    pc = [pc_line(1, "a1", "my_kill_clean", SAME),
          pc_line(2, "a2", "my_kill_expected", SAME)]
    nb = [nb_line("a1", 4242, SAME), nb_line("a2", 4242, SAME)]
    check("the reading blames the sampler",
          "ignoring the seed" in verdict_for(pc, nb), verdict_for(pc, nb))


def test_the_chooser_repeated_itself():
    print("\n--- the same angle came up twice ---")
    pc = [pc_line(1, "a1", "my_kill_clean", SAME),
          pc_line(2, "a2", "my_kill_clean", SAME)]
    nb = [nb_line("a1", 11, SAME), nb_line("a2", 22, SAME)]
    check("the reading blames the chooser",
          "chooser repeated itself" in verdict_for(pc, nb),
          verdict_for(pc, nb))


def test_a_filter_took_the_difference():
    print("\n--- her line is not what the model wrote ---")
    pc_record = pc_line(1, "a1", "my_death_traded", "That one didn't count.")
    nb_record = nb_line("a1", 11, "*She leans back* That one didn't count.",
                        removed=["stage_directions"])
    why = join_logs.diagnose(pc_record, nb_record)
    check("the filter is named", "stage_directions" in why, why)

    clean = join_logs.diagnose(pc_record, nb_line("a1", 11, "x"))
    check("and a line nothing touched gets no verdict", clean == "", clean)


# ====================================================================== shape
def test_it_runs_end_to_end():
    print("\n--- the whole tool, on a file ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        pc = [pc_line(1, "a1", "my_kill_outclassing_team", SAME),
              pc_line(2, "a2", "my_kill_clean", SAME),
              pc_line(3, "a3", "my_death_traded", "That one didn't count.",
                      key="MyDeath")]
        nb = [{"kind": "system_prompt", "chars": 6200, "text": "x"},
              nb_line("a1", 1551, SAME),
              nb_line("a2", 9921, SAME),
              nb_line("a3", 4242, "*She leans back* That one didn't count.",
                      removed=["stage_directions"])]
        pc_path, nb_path = write(tmp, pc, nb)

        records, _ = __import__("tools.analyze_session", fromlist=["x"]).load(pc_path)
        worker, meta = join_logs.load_worker(nb_path)
        join_logs.report(records, worker, meta, DEFAULT_SIMILARITY, 12)
        join_logs.print_joined(records[2], worker["a3"], full=True)
        check("the report and the full view both run", True)

        missing = join_logs.load_worker(nb_path)[0]
        missing.pop("a2")
        join_logs.report(records, missing, meta, DEFAULT_SIMILARITY, 12)
        check("and a half-matched pair of files does not crash it", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_loading_and_matching()
    test_the_model_ignored_the_direction()
    test_the_angle_never_arrived()
    test_the_server_ignored_the_seed()
    test_the_chooser_repeated_itself()
    test_a_filter_took_the_difference()
    test_it_runs_end_to_end()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
