"""
She knows when it is him.

    python tests/test_owner.py

Two things were wrong, and the first is the one that mattered.

**His messages were being thrown away.** Chat scoring is a contest with one
winner per batch and the losers are discarded, not delayed. A viewer's "hey
ravyn, what do you think?" scores 20; his "gg" scores 7 even with the owner
bonus. So he could type at her and get nothing back, with no log line saying
why.

**His name lived in three places** — data/identity.json for League, a tuple in
twitch_chat scoring, another tuple in the notebook's context_builder. Three
copies of one fact, one of them on the other machine and not editable without a
deploy.

Now: one file, one loader, and his messages skip the contest entirely.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for name, attrs in {
    "requests": {"ConnectionError": type("C", (Exception,), {}),
                 "Timeout": type("T", (Exception,), {}), "get": lambda *a, **k: None},
    "urllib3": {"exceptions": types.SimpleNamespace(InsecureRequestWarning=Warning),
                "disable_warnings": lambda *a, **k: None},
}.items():
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod

from app.settings import get_settings                        # noqa: E402
from orchestrator.identity import Identity, normalise        # noqa: E402
from orchestrator.priority_queue import SignalQueue          # noqa: E402
from sources.twitch_chat import TwitchChatSource, score_message   # noqa: E402

S = get_settings()
DATA = Path(__file__).resolve().parent.parent / "data"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_normalise_keeps_every_script():
    print("\n--- name matching ---")
    check("case is ignored", normalise("ExiledRa1n") == normalise("exiledra1n"))
    check("spaces are ignored", normalise("Exiled Rain") == normalise("exiledrain"))

    # An ASCII-only [a-z0-9] class collapsed this to "", so his RU account was
    # silently absent from the set — the log said "4 names" for a five-name file.
    check("Cyrillic survives normalisation",
          normalise("Серый Экран") == "серыйэкран",
          normalise("Серый Экран"))
    check("and is therefore matchable at all",
          normalise("Серый Экран") != "")


def test_shipped_identity_file():
    print("\n--- data/identity.json ---")
    identity = Identity(DATA / "identity.json")

    check("his Twitch login is recognised", identity.is_owner_chat("exiledra1n"))
    check("regardless of case", identity.is_owner_chat("ExiledRa1n"))
    check("and in caps", identity.is_owner_chat("EXILEDRA1N"))
    check("a viewer is not", not identity.is_owner_chat("someviewer"))
    check("an empty name is not", not identity.is_owner_chat(""))

    # A Twitch login is a claim anyone can register. Near-misses must NOT
    # inherit owner standing: her loyal framing, priority over every game
    # event, and a bypass of the voice gate. He logs in as one name.
    #
    # The underscore cases are the ones that caught me out: Twitch logins may
    # contain underscores, so the punctuation-stripping normaliser that is
    # right for League names resolved `exiled_ra1n` to him. Chat matching is
    # exact, and only the game list stays loose.
    for impostor in ("exiled", "exiledr", "exiledra1n_", "xexiledra1nx",
                     "exiled_ra1n", "exiledrain", "exiled ra1n", "exiledra1"):
        check(f"{impostor!r} is not him", not identity.is_owner_chat(impostor))

    check("surrounding whitespace is still forgiven",
          identity.is_owner_chat("  exiledra1n  "))

    # The game list stays loose on purpose: it is matched against League event
    # text on his own machine, where nobody else picks the strings.
    check("his RU League account is recognised",
          identity.is_owner_game("Серый Экран"))
    check("game matching ignores spacing",
          identity.is_owner_game("amsterdamghost"))
    check("with a #TAG suffix too",
          identity.is_owner_game("Серый Экран#RU1"))
    check("and his Latin ones", identity.is_owner_game("Amsterdam Ghost"))
    check("a teammate is not", not identity.is_owner_game("SomeTeammate"))

    # The two lists are separate identities on purpose.
    check("a chat name is not a game name",
          not identity.is_owner_game("exiledra1n"))

    check("a missing file degrades quietly",
          not Identity(DATA / "nope.json").is_owner_chat("exiledra1n"))
    check("so does no file at all", not Identity().is_owner_chat("exiledra1n"))


def test_his_message_is_never_dropped():
    print("\n--- his message never loses the contest ---")
    identity = Identity(DATA / "identity.json")
    queue = SignalQueue()
    chat = TwitchChatSource(queue, identity=identity)

    # This is the exact case that used to lose: a strong viewer message in the
    # same batch as a weak one from him.
    viewer_score = score_message("someviewer", "hey ravyn, what do you think?",
                                 set())
    owner_score = score_message("exiledra1n", "gg", set())
    check("a good viewer message really does outscore his short one",
          viewer_score > owner_score, f"{viewer_score} vs {owner_score}")

    chat._on_message("someviewer", "hey ravyn, what do you think?")
    chat._on_message("exiledra1n", "gg")

    signal = queue.pop()
    check("his message reached the queue immediately", signal is not None)
    check("and it is his", signal and signal.context.get("user") == "exiledra1n",
          signal.context.get("user") if signal else "none")
    check("marked as the owner", signal and signal.context.get("is_owner") is True)
    check("at owner priority",
          signal and signal.priority == S.OWNER_PRIORITY,
          str(signal.priority) if signal else "none")
    check("it did not wait for the batch window",
          queue.pop() is None, "something else was queued too")

    # The viewer's message is still in the buffer for the normal batch.
    check("the viewer's message is still pending",
          len(chat._buffer) == 1, str(len(chat._buffer)))


def test_owner_beats_game_events():
    print("\n--- and outranks the rest of the queue ---")
    from sources.lol_game import EVENT_CONFIG

    game_priorities = {k: c["priority"] for k, c in EVENT_CONFIG.items()}
    worst = max(game_priorities.values())
    check("owner priority beats every game event",
          all(S.OWNER_PRIORITY <= p for p in game_priorities.values()),
          f"owner={S.OWNER_PRIORITY}, game={sorted(set(game_priorities.values()))}")
    check("and ordinary chat", S.OWNER_PRIORITY < TwitchChatSource.PRIORITY,
          f"{S.OWNER_PRIORITY} vs {TwitchChatSource.PRIORITY}")
    check("and the silence filler", S.OWNER_PRIORITY < 10)
    check("game events do go as low as expected", worst >= 5, str(worst))

    # Documented side effect: at 2 he also clears the voice gate.
    check("at this priority he cuts through the voice hold",
          S.OWNER_PRIORITY <= S.VOICE_INTERRUPT_PRIORITY,
          f"owner={S.OWNER_PRIORITY} gate={S.VOICE_INTERRUPT_PRIORITY}")


def test_chat_without_identity_is_unchanged():
    print("\n--- no identity file, old behaviour ---")
    queue = SignalQueue()
    chat = TwitchChatSource(queue, identity=None)

    chat._on_message("exiledra1n", "gg")
    check("nothing is pushed straight through", queue.pop() is None)
    check("his message is buffered like anyone's",
          len(chat._buffer) == 1, str(len(chat._buffer)))
    check("and the scoring bonus still favours him",
          score_message("exiledra1n", "gg", set())
          > score_message("someviewer", "gg", set()))
    check("but not a near-miss login",
          score_message("exiled", "gg", set())
          == score_message("someviewer", "gg", set()))


def main():
    test_normalise_keeps_every_script()
    test_shipped_identity_file()
    test_his_message_is_never_dropped()
    test_owner_beats_game_events()
    test_chat_without_identity_is_unchanged()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
