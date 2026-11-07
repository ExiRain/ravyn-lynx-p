"""
One knowledge graph of all of Ravyn: this PC repo and the notebook, joined.

    uv tool run --from graphifyy python tools/combined_graph.py
    uv tool run --from graphifyy python tools/combined_graph.py --refresh
    uv tool run --from graphifyy python tools/combined_graph.py --nb ../ravyn-nb

Writes, into graph/ (tracked):

    graph.html        open in a browser: click, filter by repo or community
    GRAPH_REPORT.md   the summary: hubs, surprises, questions
    graph.json        query it:  graphify query "..." --graph graph/graph.json

Each repo is mapped on its own first, with /graphify in Claude Code (or
`graphify update .` for code only, free). That leaves graphify-out/graph.json
in each. This merges the two. --refresh re-runs the free code pass in both
repos first, so a code change shows up without re-reading the docs.

## Why the bridge

The two halves never call each other's code: they talk only over RabbitMQ.
Merged as-is, the graph had ZERO direct PC <-> notebook links — two islands
touching only through shared libraries like json and pika. So the three
queues are added as nodes, and each publish/consume edge is found by
searching the real source line for its routing key on every run. A renamed
queue or a moved call is reported, never silently drawn from a stale line.

The payload links (what one side writes, the other parses) are marked
INFERRED: nothing in the code names the other side, the shape does.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "graph"

PC, NB = "ravyn-lynx-p::", "ravyn-nb::"

QUEUES = {
    "rabbitmq::ravyn_request": ("ravyn.request queue",
                                "PC -> notebook: one request per signal"),
    "rabbitmq::ravyn_response": ("ravyn.response queue",
                                 "notebook -> PC: exactly one reply per request"),
    "rabbitmq::ravyn_log": ("ravyn.log queue",
                            "notebook -> PC: worker log lines, capped, drop-head"),
}

# (side, file, regex on the line, node id, relation, queue). The line number
# is looked up every run, so the edge cites where the code is today.
QUEUE_EDGES = [
    ("pc", "orchestrator/dispatcher.py", r"routing_key=.*QUEUE_REQUEST",
     PC + "orchestrator_dispatcher_dispatcher_dispatch", "publishes_to",
     "rabbitmq::ravyn_request"),
    ("nb", "adapters/mq/rabbitmq.py", r"basic_consume\(queue=.*QUEUE_REQUEST",
     NB + "adapters_mq_rabbitmq_start_worker", "consumes",
     "rabbitmq::ravyn_request"),
    ("nb", "adapters/mq/rabbitmq.py", r"routing_key=.*QUEUE_RESPONSE",
     NB + "adapters_mq_rabbitmq_start_worker_callback", "publishes_to",
     "rabbitmq::ravyn_response"),
    ("pc", "services/response_listener.py", r"queue=.*QUEUE_RESPONSE,",
     PC + "services_response_listener_start_response_listener", "consumes",
     "rabbitmq::ravyn_response"),
    ("nb", "adapters/mq/rabbitmq.py", r"routing_key=.*QUEUE_LOG",
     NB + "adapters_mq_rabbitmq_start_worker_ship", "publishes_to",
     "rabbitmq::ravyn_log"),
    ("pc", "services/log_receiver.py", r"basic_consume\(queue=.*QUEUE_LOG",
     PC + "services_log_receiver_logreceiver_run", "consumes",
     "rabbitmq::ravyn_log"),
]

# What one side writes is what the other parses. Inferred from shape.
PAYLOAD_EDGES = [
    (PC + "orchestrator_models_signal_to_request",
     NB + "adapters_mq_rabbitmq_start_worker_callback", "orchestrator/models.py"),
    (NB + "adapters_mq_rabbitmq_start_worker_callback",
     PC + "services_response_listener_start_response_listener_handle",
     "adapters/mq/rabbitmq.py"),
    (NB + "app_worker_log_workerlog_record",
     PC + "tools_join_logs_load_worker", "app/worker_log.py"),
]


def edge(src, tgt, rel, source_file, loc, conf="EXTRACTED", score=1.0):
    return {"source": src, "target": tgt, "relation": rel,
            "confidence": conf, "confidence_score": score,
            "source_file": source_file, "source_location": loc,
            "weight": 1.0, "_origin": "bridge"}


def find_line(path: Path, pattern: str) -> str | None:
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(pattern, line) and not line.lstrip().startswith("#"):
                return f"L{i}"
    except OSError:
        pass
    return None


def bridges(ids: set, pc_root: Path, nb_root: Path) -> tuple[list, list]:
    out, problems = [], []
    for side, rel_file, pattern, node, relation, queue in QUEUE_EDGES:
        root = pc_root if side == "pc" else nb_root
        loc = find_line(root / rel_file, pattern)
        if node not in ids:
            problems.append(f"node {node} is gone — was it renamed?")
        elif loc is None:
            problems.append(f"{side}:{rel_file}: no line matches {pattern!r}")
        else:
            out.append(edge(node, queue, relation, rel_file, loc))
    for src, tgt, rel_file in PAYLOAD_EDGES:
        if src in ids and tgt in ids:
            out.append(edge(src, tgt, "shares_data_with", rel_file, None,
                            "INFERRED", 0.95))
        else:
            problems.append(f"payload link {src} -> {tgt}: node missing")
    return out, problems


def run(cmd: list, cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed in {cwd}:\n{result.stderr[-800:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--nb", default=str(ROOT.parent / "ravyn-nb"),
                    help="the notebook repo (default: ../ravyn-nb)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-run the free code pass in both repos first")
    args = ap.parse_args()

    try:
        from graphify.analyze import (god_nodes, suggest_questions,
                                      surprising_connections)
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.export import to_json
        from graphify.report import generate
    except ImportError:
        sys.exit("graphify is not installed for this Python. Run with:\n"
                 "  uv tool run --from graphifyy python tools/combined_graph.py")

    nb_root = Path(args.nb).resolve()
    repos = {"PC": ROOT, "notebook": nb_root}
    for name, repo in repos.items():
        if args.refresh:
            print(f"Refreshing the {name} code graph...")
            run(["graphify", "update", "."], repo)
        if not (repo / "graphify-out" / "graph.json").exists():
            sys.exit(f"No graph for the {name} repo at {repo}. Build it first:\n"
                     f"  /graphify .   (in Claude Code, in {repo})")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "graphify-out").mkdir()
        run(["graphify", "merge-graphs",
             str(ROOT / "graphify-out" / "graph.json"),
             str(nb_root / "graphify-out" / "graph.json"),
             "--out", "graphify-out/graph.json"], work)

        g = json.loads((work / "graphify-out" / "graph.json").read_text())
        ids = {n["id"] for n in g["nodes"]}
        links, problems = bridges(ids, ROOT, nb_root)
        for p in problems:
            print(f"  ! bridge skipped: {p}")

        queue_nodes = [{"id": q, "label": label, "file_type": "concept",
                        "repo": "rabbitmq", "source_file": None,
                        "source_location": None, "rationale": why,
                        "_origin": "bridge"}
                       for q, (label, why) in QUEUES.items()]
        tokens = sum(json.loads((r / "graphify-out" / "cost.json").read_text())
                     .get("total_input_tokens", 0)
                     for r in repos.values()
                     if (r / "graphify-out" / "cost.json").exists())
        extraction = {
            "nodes": g["nodes"] + queue_nodes,
            "edges": g["links"] + links,
            "hyperedges": g.get("hyperedges", []) + [{
                "id": "pc_notebook_message_contract",
                "label": "PC <-> notebook message contract",
                "nodes": list(QUEUES) + [
                    PC + "orchestrator_dispatcher_dispatcher_dispatch",
                    NB + "adapters_mq_rabbitmq_start_worker_callback",
                    PC + "services_response_listener_start_response_listener_handle"],
                "relation": "participate_in", "confidence": "EXTRACTED",
                "confidence_score": 1.0, "source_file": None}],
            "input_tokens": tokens, "output_tokens": 0,
        }

        G = build_from_json(extraction, root=".", directed=False)
        communities = cluster(G)
        cohesion = score_all(G, communities)

        # Each combined community is named after the per-repo community most
        # of its nodes came from, tagged with the side it lives on.
        labels = {}
        for cid, members in communities.items():
            names = collections.Counter()
            for m in members:
                d = G.nodes[m]
                if d.get("repo") == "rabbitmq":
                    names["PC <-> Notebook Queues"] += 3
                elif d.get("community_name"):
                    side = {"ravyn-lynx-p": "PC", "ravyn-nb": "NB"}.get(
                        d.get("repo"), "lib")
                    names[f"{d['community_name']} ({side})"] += 1
            labels[cid] = (names.most_common(1)[0][0] if names
                           else f"Community {cid}")
        taken = collections.Counter(labels.values())
        for cid in labels:
            if taken[labels[cid]] > 1:
                labels[cid] += f" #{cid}"

        questions = suggest_questions(G, communities, labels)
        if not to_json(G, communities, str(work / "graphify-out" / "graph.json"),
                       community_labels=labels, force=True):
            sys.exit("graphify refused to write the combined graph")

        detection = {"total_files": 0, "total_words": 0, "files": {},
                     "skipped_sensitive": []}
        report = generate(G, communities, cohesion, labels, god_nodes(G),
                          surprising_connections(G, communities), detection,
                          {"input": tokens, "output": 0}, ".",
                          suggested_questions=questions)
        (work / "graphify-out" / "GRAPH_REPORT.md").write_text(report,
                                                               encoding="utf-8")
        run(["graphify", "export", "html"], work)

        OUT.mkdir(exist_ok=True)
        for name in ("graph.json", "graph.html", "GRAPH_REPORT.md"):
            shutil.copy(work / "graphify-out" / name, OUT / name)

    print(f"Combined graph: {G.number_of_nodes()} nodes, "
          f"{G.number_of_edges()} edges, {len(communities)} communities, "
          f"{len(links)} bridge edges -> {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
