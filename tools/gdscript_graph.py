"""
A code graph of the Godot repo (ravyn-godot), in graphify's own format.

    uv tool run --from graphifyy python tools/gdscript_graph.py
    uv tool run --from graphifyy python tools/gdscript_graph.py --godot ../ravyn-godot

graphify has no GDScript extractor. Run on ravyn-godot it skips every `.gd`
and `.tscn` and maps only the C# examples shipped inside the Live2D addon —
228 nodes, none of them Ravyn's. This reads the files it skips:

    scripts/*.gd   one node per script and per function; calls inside a
                   script, signal hookups (`x.connect(_on_x)`), and calls
                   into another script through an `@onready var` that points
                   at a scene node carrying that script
    *.tscn         one node per scene, linked to every script it attaches

and writes ravyn-godot/graphify-out/graph.json, which `graphify query` and
tools/combined_graph.py read like any other repo's graph. `addons/` is
third-party and left out.

It is a line reader, not a parser: enough for functions, calls and scene
wiring, which is what the graph is for.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"addons", ".godot", ".import", "graphify-out", ".git"}

_FUNC = re.compile(r"^(?:static\s+)?func\s+(\w+)\s*\(")
_ONREADY = re.compile(r"^@onready\s+var\s+(\w+)[^=]*=\s*\$\"?([^\"\s]+)\"?")
_CALL = re.compile(r"(?<![\w.])(\w+)\s*\(")
_REMOTE = re.compile(r"\b(\w+)\.(\w+)\s*\(")
_CONNECT = re.compile(r"\.connect\(\s*(\w+)\s*[,)]")
_EXT = re.compile(r'\[ext_resource type="Script".*?path="res://([^"]+)".*?'
                  r'id="([^"]+)"')
_NODE = re.compile(r'^\[node name="([^"]+)"')
_SCRIPT = re.compile(r'^script = ExtResource\("([^"]+)"\)')


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"\W", "_", text.lower())).strip("_")


def _files(root: Path, suffix: str) -> list[Path]:
    return sorted(p for p in root.rglob(f"*{suffix}")
                  if not SKIP_DIRS & set(p.relative_to(root).parts))


def _code(line: str) -> str:
    """The line without its comment or string contents."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    return line.split("#", 1)[0]


def read_script(path: Path) -> dict:
    """{functions: {name: (line, [body lines])}, onready: {var: node name}}."""
    functions, onready, current = {}, {}, None
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = _FUNC.match(raw)
        if m:
            current = m.group(1)
            functions[current] = (i, [])
            continue
        if raw and not raw[0].isspace():
            current = None
            m = _ONREADY.match(raw)
            if m:
                onready[m.group(1)] = m.group(2).rstrip("/").split("/")[-1]
        elif current:
            functions[current][1].append((i, _code(raw)))
    return {"functions": functions, "onready": onready}


def read_scene(path: Path) -> dict:
    """{scripts: [res path], nodes: {node name: res path of its script}}."""
    ext, nodes, node = {}, {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _EXT.search(raw)
        if m:
            ext[m.group(2)] = m.group(1)
            continue
        m = _NODE.match(raw)
        if m:
            node = m.group(1)
            continue
        m = _SCRIPT.match(raw)
        if m and node and m.group(1) in ext:
            nodes[node] = ext[m.group(1)]
    return {"scripts": sorted(set(ext.values())), "nodes": nodes}


def extract(root: Path) -> dict:
    """graphify's extraction shape: {nodes, edges}."""
    nodes, edges = [], []

    def node(nid, label, rel, line, callable_=False):
        n = {"id": nid, "label": label, "file_type": "code",
             "source_file": rel, "source_location": f"L{line}",
             "_origin": "ast"}
        if callable_:
            n["_callable"] = True
        nodes.append(n)

    def edge(src, tgt, relation, rel, line, conf="EXTRACTED", score=1.0):
        edges.append({"source": src, "target": tgt, "relation": relation,
                      "confidence": conf, "confidence_score": score,
                      "source_file": rel, "source_location": f"L{line}",
                      "weight": 1.0, "_origin": "ast"})

    scripts = {p.relative_to(root).as_posix(): read_script(p)
               for p in _files(root, ".gd")}
    scenes = {p.relative_to(root).as_posix(): read_scene(p)
              for p in _files(root, ".tscn")}

    # Scene node name -> the script on it, across every scene.
    node_script = {}
    for scene in scenes.values():
        for name, script in scene["nodes"].items():
            node_script.setdefault(name, script)

    def fid(rel: str) -> str:
        return slug(rel.rsplit(".", 1)[0])

    for rel, script in scripts.items():
        node(fid(rel), Path(rel).name, rel, 1)
        for name, (line, _) in script["functions"].items():
            node(f"{fid(rel)}_{slug(name)}", f"{name}()", rel, line, True)
            edge(fid(rel), f"{fid(rel)}_{slug(name)}", "contains", rel, line)

    for rel, script in scripts.items():
        local = set(script["functions"])
        for name, (_, body) in script["functions"].items():
            me, seen = f"{fid(rel)}_{slug(name)}", set()
            for line, code in body:
                for m in _CONNECT.finditer(code):
                    if m.group(1) in local:
                        seen.add((f"{fid(rel)}_{slug(m.group(1))}",
                                  "indirect_call", line))
                for m in _REMOTE.finditer(code):
                    target = node_script.get(script["onready"].get(m.group(1)))
                    if target in scripts and \
                            m.group(2) in scripts[target]["functions"]:
                        seen.add((f"{fid(target)}_{slug(m.group(2))}",
                                  "calls", line))
                for m in _CALL.finditer(code):
                    if m.group(1) in local and m.group(1) != name:
                        seen.add((f"{fid(rel)}_{slug(m.group(1))}",
                                  "calls", line))
            done = set()
            for target, relation, line in sorted(seen, key=lambda s: s[2]):
                if (target, relation) not in done:
                    done.add((target, relation))
                    edge(me, target, relation, rel, line)

    for rel, scene in scenes.items():
        node(fid(rel) + "_scene", Path(rel).name, rel, 1)
        for script in scene["scripts"]:
            if script in scripts:
                edge(fid(rel) + "_scene", fid(script), "uses", rel, 1)

    return {"nodes": nodes, "edges": edges, "hyperedges": [],
            "input_tokens": 0, "output_tokens": 0}


def write(root: Path) -> tuple[int, int]:
    """Build ravyn-godot/graphify-out/graph.json. (nodes, edges)."""
    from graphify.build import build_from_json
    from graphify.cluster import cluster
    from graphify.export import to_json

    extraction = extract(root)
    if not extraction["nodes"]:
        sys.exit(f"No .gd or .tscn files under {root}")
    G = build_from_json(extraction, root=str(root), directed=False)
    communities = cluster(G)
    # A community is a script, near enough: name it after the file most of
    # its nodes are in.
    labels = {}
    for cid, members in communities.items():
        files = [Path(G.nodes[m].get("source_file") or "").name
                 for m in members]
        labels[cid] = max(set(files), key=files.count) or f"Community {cid}"
    out = root / "graphify-out"
    out.mkdir(exist_ok=True)
    if not to_json(G, communities, str(out / "graph.json"),
                   community_labels=labels, force=True):
        sys.exit("graphify refused to write the Godot graph")
    return G.number_of_nodes(), G.number_of_edges()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--godot", default=str(ROOT.parent / "ravyn-godot"),
                    help="the Godot repo (default: ../ravyn-godot)")
    args = ap.parse_args()
    root = Path(args.godot).resolve()
    try:
        n, e = write(root)
    except ImportError:
        sys.exit("graphify is not installed for this Python. Run with:\n"
                 "  uv tool run --from graphifyy python tools/gdscript_graph.py")
    print(f"Godot graph: {n} nodes, {e} edges -> {root / 'graphify-out'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
