"""
The Godot scripts, read into a graph.

    python tests/test_gdscript_graph.py

graphify has no GDScript extractor, so tools/gdscript_graph.py reads the
scripts and scenes itself. This pins what the combined graph leans on: a
node per function, calls inside a script, signal hookups, and a call into
another script through an @onready var and the scene that wires it.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gdscript_graph                                      # noqa: E402

FAILURES: list[str] = []

MAIN = '''extends Node2D

@onready var ears_node = $Sprite2D/Model/Ears
var socket := WebSocketPeer.new()

func _ready():
	socket.connect_to_url("ws://x")   # not a signal hookup
	_helper()

func _process(_delta):
	_handle_websocket()

func _handle_websocket():
	ears_node.perk_up()
	print("perk_up() in a string is not a call")
	# _helper() in a comment is not a call

func _helper():
	pass
'''

EARS = '''extends GDCubismEffectCustom

func _ready():
	cubism_process.connect(_on_process)

func _on_process(model, delta):
	pass

func perk_up():
	pass
'''

SCENE = '''[gd_scene format=3]

[ext_resource type="Script" uid="uid://a" path="res://scripts/main.gd" id="1_a"]
[ext_resource type="Script" uid="uid://b" path="res://scripts/ears.gd" id="2_b"]

[node name="Main Node" type="Node2D"]
script = ExtResource("1_a")

[node name="Ears" type="GDCubismEffectCustom" parent="Sprite2D/Model"]
script = ExtResource("2_b")
'''


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main():
    print("\n--- GDScript into graph nodes and edges ---")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "addons" / "x").mkdir(parents=True)
        (root / "scripts" / "main.gd").write_text(MAIN, encoding="utf-8")
        (root / "scripts" / "ears.gd").write_text(EARS, encoding="utf-8")
        (root / "addons" / "x" / "vendor.gd").write_text(EARS, encoding="utf-8")
        (root / "node_2d.tscn").write_text(SCENE, encoding="utf-8")
        got = gdscript_graph.extract(root)

    ids = {n["id"] for n in got["nodes"]}
    edges = {(e["source"], e["relation"], e["target"]) for e in got["edges"]}

    check("a node per script and per function",
          {"scripts_main", "scripts_main_ready", "scripts_main_process",
           "scripts_main_handle_websocket", "scripts_ears_perk_up"} <= ids,
          str(sorted(ids)))
    check("the addon is left out", not any("addons" in i for i in ids))
    check("calls inside a script",
          ("scripts_main_process", "calls",
           "scripts_main_handle_websocket") in edges)
    check("a call through an @onready var reaches the other script",
          ("scripts_main_handle_websocket", "calls",
           "scripts_ears_perk_up") in edges, str(sorted(edges)))
    check("a signal hookup is an indirect call",
          ("scripts_ears_ready", "indirect_call",
           "scripts_ears_on_process") in edges)
    check("strings and comments are not calls",
          ("scripts_main_handle_websocket", "calls",
           "scripts_main_helper") not in edges)
    check("the scene uses the scripts it attaches",
          {("node_2d_scene", "uses", "scripts_main"),
           ("node_2d_scene", "uses", "scripts_ears")} <= edges)
    check("every edge joins two real nodes",
          all(s in ids and t in ids for s, _, t in edges))
    locations = {n["id"]: n["source_location"] for n in got["nodes"]}
    check("functions carry their line",
          locations["scripts_main_ready"] == "L6", locations["scripts_main_ready"])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
