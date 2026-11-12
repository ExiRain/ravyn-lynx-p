"""
One knowledge graph of all of Ravyn: this PC repo, the notebook and the
Godot avatar, joined.

    uv tool run --from graphifyy python tools/combined_graph.py
    uv tool run --from graphifyy python tools/combined_graph.py --refresh
    uv tool run --from graphifyy python tools/combined_graph.py --nb ../ravyn-nb --godot ../ravyn-godot

Writes, into graph/ (tracked):

    graph.html        open in a browser: click, filter by repo or community
    GRAPH_REPORT.md   the summary: hubs, surprises, questions
    graph.json        query it:  graphify query "..." --graph graph/graph.json

The PC and the notebook are mapped on their own first, with /graphify in
Claude Code (or `graphify update .` for code only, free). That leaves
graphify-out/graph.json in each. --refresh re-runs the free code pass in
both first, so a code change shows up without re-reading the docs.

Godot is mapped here, on every run, by tools/gdscript_graph.py: graphify
cannot read GDScript, so /graphify there sees only the Live2D addon. If
ravyn-godot is not checked out next to this repo, the graph is built
without it and says so.

What the docs pass found (concepts, documents) is carried over from the
last combined graph when a repo's own graph lacks it, so a machine with only
the free code pass does not strip it out.

## Why the bridges

The three programs never call each other's code. The PC and the notebook
talk only over RabbitMQ; the PC and Godot only over one WebSocket
(`/ws/audio`: speech audio, lip sync, mood, visibility). Merged as-is the
graph was islands touching only through shared libraries like json and
pika. So the three queues and the WebSocket are added as nodes, and each
edge to them is found by searching the real source line on every run. A
renamed queue or a moved call is reported, never silently drawn from a
stale line.

Every text message the PC sends Godot ("START", "MOOD:", ...) is checked
against the handlers in scripts/main.gd too: one that is sent and never
handled is printed.

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

PC, NB, GD = "ravyn-lynx-p::", "ravyn-nb::", "ravyn-godot::"

QUEUES = {
    "rabbitmq::ravyn_request": ("ravyn.request queue",
                                "PC -> notebook: one request per signal"),
    "rabbitmq::ravyn_response": ("ravyn.response queue",
                                 "notebook -> PC: exactly one reply per request"),
    "rabbitmq::ravyn_log": ("ravyn.log queue",
                            "notebook -> PC: worker log lines, capped, drop-head"),
}

SOCKET = "websocket::ws_audio"
SOCKETS = {
    SOCKET: ("/ws/audio WebSocket",
             "PC -> Godot: speech audio, lip sync, mood and visibility"),
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

# The same, for the PC <-> Godot WebSocket. Only drawn when Godot is there.
SOCKET_EDGES = [
    ("pc", "services/audio_server.py", r"@app\.websocket\(\"/ws/audio\"\)",
     PC + "services_audio_server_websocket_endpoint", "serves", SOCKET),
    ("pc", "services/audio_server.py", r"await ws\.send_text\(msg\)",
     PC + "services_audio_server_send_text_to_godot", "publishes_to", SOCKET),
    ("pc", "services/audio_server.py", r"await ws\.send_bytes\(",
     PC + "services_audio_server_send_bytes_to_godot", "publishes_to", SOCKET),
    ("godot", "scripts/main.gd", r"connect_to_url\(ws_url\)",
     GD + "scripts_main_ready", "connects_to", SOCKET),
    ("godot", "scripts/main.gd", r"socket\.get_packet\(\)",
     GD + "scripts_main_handle_websocket", "consumes", SOCKET),
]

# Each text message, and the PC function that sends it. Godot handles them
# all in one function, so the links are per sender; INFERRED, like payloads.
GODOT_HANDLER = GD + "scripts_main_handle_websocket"
MESSAGES = [
    ("LINE:", PC + "services_audio_server_begin_utterance"),
    ("SHOW:", PC + "services_audio_server_set_visibility"),
    ("MOOD:", PC + "services_audio_server_begin_utterance"),
    ("TIRED:", PC + "services_audio_server_begin_utterance"),
    ("START", PC + "services_audio_server_begin_utterance"),
    ("RATE:", PC + "services_audio_server_push_sentence"),
    ("MOUTH:", PC + "services_audio_server_push_sentence"),
    ("PHONEME:", PC + "services_audio_server_push_sentence"),
    ("END", PC + "services_audio_server_end_utterance"),
    ("FACE:", PC + "services_audio_server_send_face"),
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


def bridges(ids: set, roots: dict) -> tuple[list, list]:
    out, problems = [], []
    wanted = QUEUE_EDGES + (SOCKET_EDGES if "godot" in roots else [])
    for side, rel_file, pattern, node, relation, queue in wanted:
        root = roots[side]
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


def message_links(ids: set, roots: dict) -> tuple[list, list]:
    """
    PC sender -> Godot handler, one link per sender, for the messages both
    sides know. A message only one side knows is returned as a note: it is a
    fact about the code, not a fault in the graph.
    """
    out, notes, linked = [], [], set()
    pc = (roots["pc"] / "services/audio_server.py").read_text(encoding="utf-8")
    gd = (roots["godot"] / "scripts/main.gd").read_text(encoding="utf-8")
    for message, sender in MESSAGES:
        sent = re.search(rf'send_text_to_godot\(f?"{re.escape(message)}', pc)
        handled = re.search(rf'msg(?: == |\.begins_with\()"{re.escape(message)}',
                            gd)
        if sent and not handled:
            notes.append(f'the PC sends "{message}" and scripts/main.gd has '
                         f"no handler for it")
        elif handled and not sent:
            notes.append(f'scripts/main.gd handles "{message}" and the PC '
                         f"never sends it")
        elif sent and sender in ids and GODOT_HANDLER in ids \
                and sender not in linked:
            linked.add(sender)
            out.append(edge(sender, GODOT_HANDLER, "shares_data_with",
                            "services/audio_server.py", None, "INFERRED", 0.95))
    return out, notes


def carried_over(g: dict, previous: Path) -> tuple[list, list]:
    """
    Docs-pass nodes and links that the last combined graph had and this
    merge lacks — see the module docstring.
    """
    try:
        old = json.loads(previous.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    ids = {n["id"] for n in g["nodes"]}
    nodes = [n for n in old["nodes"]
             if n.get("_origin") == "semantic" and n["id"] not in ids]
    ids |= {n["id"] for n in nodes}
    have = {(l["source"], l["target"], l["relation"]) for l in g["links"]}
    links = [l for l in old["links"]
             if l.get("_origin") == "semantic"
             and l["source"] in ids and l["target"] in ids
             and (l["source"], l["target"], l["relation"]) not in have]
    return nodes, links


def run(cmd: list, cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed in {cwd}:\n{result.stderr[-800:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--nb", default=str(ROOT.parent / "ravyn-nb"),
                    help="the notebook repo (default: ../ravyn-nb)")
    ap.add_argument("--godot", default=str(ROOT.parent / "ravyn-godot"),
                    help="the Godot repo (default: ../ravyn-godot)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-run the free code pass in the PC and notebook "
                         "repos first")
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

    roots = {"pc": ROOT, "nb": nb_root}
    graphs = [ROOT / "graphify-out" / "graph.json",
              nb_root / "graphify-out" / "graph.json"]
    godot_root = Path(args.godot).resolve()
    if (godot_root / "project.godot").exists():
        import gdscript_graph
        n, e = gdscript_graph.write(godot_root)
        print(f"Mapped the Godot scripts: {n} nodes, {e} edges")
        roots["godot"] = godot_root
        graphs.append(godot_root / "graphify-out" / "graph.json")
    else:
        print(f"No Godot repo at {godot_root} — building without it")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "graphify-out").mkdir()
        run(["graphify", "merge-graphs", *map(str, graphs),
             "--out", "graphify-out/graph.json"], work)

        g = json.loads((work / "graphify-out" / "graph.json").read_text())
        kept_nodes, kept_links = carried_over(g, OUT / "graph.json")
        if kept_nodes:
            print(f"Carried over {len(kept_nodes)} docs-pass nodes from the "
                  f"last combined graph")
        g["nodes"] += kept_nodes
        g["links"] += kept_links

        ids = {n["id"] for n in g["nodes"]}
        links, problems = bridges(ids, roots)
        for p in problems:
            print(f"  ! bridge skipped: {p}")
        sockets = {}
        if "godot" in roots:
            sockets = SOCKETS
            more, notes = message_links(ids, roots)
            links += more
            for note in notes:
                print(f"  note: {note}")

        queue_nodes = [{"id": q, "label": label, "file_type": "concept",
                        "repo": "rabbitmq", "source_file": None,
                        "source_location": None, "rationale": why,
                        "_origin": "bridge"}
                       for q, (label, why) in QUEUES.items()]
        queue_nodes += [{"id": q, "label": label, "file_type": "concept",
                         "repo": "websocket", "source_file": None,
                         "source_location": None, "rationale": why,
                         "_origin": "bridge"}
                        for q, (label, why) in sockets.items()]
        contracts = []
        if sockets:
            contracts.append({
                "id": "pc_godot_avatar_contract",
                "label": "PC <-> Godot avatar contract",
                "nodes": [SOCKET,
                          PC + "services_audio_server_websocket_endpoint",
                          PC + "services_audio_server_send_text_to_godot",
                          PC + "services_audio_server_send_bytes_to_godot",
                          GODOT_HANDLER],
                "relation": "participate_in", "confidence": "EXTRACTED",
                "confidence_score": 1.0, "source_file": None})
        repos["Godot"] = godot_root
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
                "confidence_score": 1.0, "source_file": None}] + contracts,
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
                elif d.get("repo") == "websocket":
                    names["PC <-> Godot WebSocket"] += 3
                elif d.get("community_name"):
                    side = {"ravyn-lynx-p": "PC", "ravyn-nb": "NB",
                            "ravyn-godot": "Godot"}.get(
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
