"""
What the PC sends the notebook — the fields the other machine depends on.

    python tests/test_contract.py

Neither machine fails a test when the other renames something: the notebook
reads a missing key as its default and carries on. On 2026-11-07 the audit
of every context key the notebook reads found `game_active` was never sent,
so every prompt said "No game is running. Just chatting." during games. This
checks the payload as it actually goes over the wire.
"""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The dispatcher imports pika at module level; no broker is touched here.
sys.modules.setdefault("pika", types.ModuleType("pika"))

from orchestrator.dispatcher import Dispatcher            # noqa: E402
from orchestrator.models import Signal                    # noqa: E402
from orchestrator.priority_queue import SignalQueue       # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class Channel:
    def __init__(self):
        self.sent = []

    def basic_publish(self, exchange, routing_key, body):
        self.sent.append(json.loads(body))


def sent(dispatcher, signal):
    channel = Channel()
    dispatcher._dispatch(signal, channel)
    return channel.sent[-1]


def main():
    print("\n--- every request says whether a game is on ---")
    d = Dispatcher(SignalQueue())
    body = sent(d, Signal(source="chat", priority=5, text="hi",
                          context={"user": "bob"}))
    check("between games: game_active is False, and present",
          body["context"].get("game_active") is False, str(body["context"]))

    d.game_active = True
    body = sent(d, Signal(source="game", priority=3, text="You died."))
    check("in a game: game_active is True",
          body["context"].get("game_active") is True)

    body = sent(d, Signal(source="game", priority=3, text="x",
                          context={"game_active": False}))
    check("a source that knows better keeps its own value",
          body["context"]["game_active"] is False)

    print("\n--- the fields the notebook's worker reads ---")
    body = sent(d, Signal(source="chat", priority=5, text="hello"))
    check("text, source, mode, skip_llm and context are all there",
          {"text", "source", "mode", "skip_llm", "context"} <= set(body),
          str(sorted(body)))
    check("with the req_id that joins the two logs",
          len(body["context"].get("req_id", "")) == 12)
    check("and league_mode and lang stamped",
          "league_mode" in body["context"] and body["context"].get("lang"))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
