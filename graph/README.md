# Ravyn, as one graph

The PC (this repo) and the notebook (`ravyn-nb`) mapped into one knowledge
graph by [graphify](https://github.com/Graphify-Labs/graphify), joined where
they actually meet: the three RabbitMQ queues.

| File | What it is |
|---|---|
| `graph.html` | Open in a browser. Click nodes, filter by repo or community, search. |
| `GRAPH_REPORT.md` | The summary: most-connected parts, surprising links, suggested questions. |
| `graph.json` | The data. Ask it things from the repo root: |

    graphify query "how does a donation become speech" --graph graph/graph.json
    graphify path "LolGameSource" "build_messages()" --graph graph/graph.json
    graphify explain "MemoryManager" --graph graph/graph.json

## Rebuilding

Each repo needs its own graph first (`/graphify .` in Claude Code, once per
repo; code-only updates are free and take seconds). Then, from this repo,
with `ravyn-nb` checked out next to it:

    uv tool run --from graphifyy python tools/combined_graph.py --refresh

`--refresh` re-maps the code in both repos before merging. Without it, the
existing per-repo graphs are merged as they are.

## The bridge

The two machines never call each other's code, so a plain merge leaves two
islands. The script adds `ravyn.request`, `ravyn.response` and `ravyn.log`
as nodes, and links each to the line that publishes or consumes it, looked
up in the source on every run. If a queue is renamed or a call moves, the
script says which link it could not find and exits non-zero rather than
drawing a stale one.

Links marked INFERRED are guesses from shape (what one side writes, the
other parses), not code references. Check those before relying on them.

No viewer data is in here: `logs/` is git-ignored and graphify skips it.
