# Ravyn, as one graph

The PC (this repo), the notebook (`ravyn-nb`) and the Godot avatar
(`ravyn-godot`) mapped into one knowledge graph by
[graphify](https://github.com/Graphify-Labs/graphify), joined where they
actually meet: the three RabbitMQ queues between the PC and the notebook,
and the `/ws/audio` WebSocket between the PC and Godot.

| File | What it is |
|---|---|
| `graph.html` | Open in a browser. Click nodes, filter by repo or community, search. |
| `GRAPH_REPORT.md` | The summary: most-connected parts, surprising links, suggested questions. |
| `graph.json` | The data. Ask it things from the repo root: |

    graphify query "how does a donation become speech" --graph graph/graph.json
    graphify path "LolGameSource" "build_messages()" --graph graph/graph.json
    graphify explain "MemoryManager" --graph graph/graph.json
    graphify path "start_worker()" "perk_up()" --graph graph/graph.json

## Rebuilding

The PC and the notebook each need their own graph first (`/graphify .` in
Claude Code, once per repo; code-only updates are free and take seconds).
Then, from this repo, with `ravyn-nb` and `ravyn-godot` checked out next to
it:

    uv tool run --from graphifyy python tools/combined_graph.py --refresh

`--refresh` re-maps the code in the PC and notebook repos before merging.
Without it, their existing graphs are merged as they are.

Godot needs no step of its own. graphify cannot read GDScript — run there it
maps only the Live2D addon — so `tools/gdscript_graph.py` reads the scripts
and scenes instead, on every run. Without `ravyn-godot` next to this repo
the graph is built from the other two and says so.

Concepts and documents found by the docs pass are carried over from the last
combined graph when a repo's own graph does not have them, so rebuilding on
a machine that only ran the free code pass does not drop them.

## The bridge

The three programs never call each other's code, so a plain merge leaves
islands. The script adds `ravyn.request`, `ravyn.response`, `ravyn.log` and
the `/ws/audio` WebSocket as nodes, and links each to the line that
publishes, serves or consumes it, looked up in the source on every run. If a
queue is renamed or a call moves, the script says which link it could not
find and exits non-zero rather than drawing a stale one.

It also checks every text message the PC sends Godot (`START`, `MOOD:`,
`PHONEME:`, ...) against the handlers in `scripts/main.gd`, and prints any
that one side knows and the other does not.

Links marked INFERRED are guesses from shape (what one side writes, the
other parses), not code references. Check those before relying on them.

No viewer data is in here: `logs/` is git-ignored and graphify skips it.
