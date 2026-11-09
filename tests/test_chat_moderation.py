"""
Bans, timeouts, deleted messages and likely scams in chat.

    python tests/test_chat_moderation.py

On 2026-11-09 a first-time chatter ran the usual small-streamer scam —
flattery, "connect after work", "Let's connect on discord", a Discord handle.
She answered all four warmly, and after the streamer banned him she kept
talking about him: his messages were still waiting in the batch and her
replies in the queue. The lines below are his, fed in as Twitch sends them.
"""

import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pika", types.ModuleType("pika"))

from orchestrator.dispatcher import Dispatcher            # noqa: E402
from orchestrator.models import Signal                    # noqa: E402
from orchestrator.priority_queue import SignalQueue       # noqa: E402
from sources.chat_guard import ScamWatch, signs_in        # noqa: E402
from sources.twitch_chat import TwitchChatSource, split_tags  # noqa: E402

FAILURES: list[str] = []
CHAN = "exiledra1n"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def privmsg(user, text):
    return (f"@badge-info=;color=;display-name={user};mod=0;user-type= "
            f":{user}!{user}@{user}.tmi.twitch.tv PRIVMSG #{CHAN} :{text}")


def ban(user, seconds=None):
    tags = "room-id=1;target-user-id=2;tmi-sent-ts=3"
    if seconds:
        tags = f"ban-duration={seconds};" + tags
    return f"@{tags} :tmi.twitch.tv CLEARCHAT #{CHAN} :{user}"


def drain(queue):
    out = []
    while (s := queue.pop()) is not None:
        out.append(s)
    return out


SCAMMER = [
    "I catch part of your stream tbh you're amazing and I have dropped a follow",
    "I would like to play with you but at work now, we can connect after work "
    "if you don't mind",
    "Let's connect on discord",
    "Determined_8",
]


def test_the_scam_is_recognised():
    print("\n--- the 11-09 scam, message by message ---")
    watch = ScamWatch()
    flags = [bool(watch.observe("d", m)) for m in SCAMMER]
    check("flattery alone and 'connect after work' alone are not enough",
          flags[:2] == [False, False], str(flags))
    check("'Let's connect on discord' makes it a likely scam",
          flags[2], str(flags))

    normal = ScamWatch()
    for m in ["do you have a discord?", "gg that was clean", "lol nice",
              "what rank are you"]:
        normal.observe("r", m)
    check("a regular asking about Discord is not flagged",
          normal.reasons("r") == [])
    check("selling viewers flags on its own",
          ScamWatch().observe("x", "best viewers on streamboo dot com") != [])
    check("so does a design pitch",
          ScamWatch().observe("y", "I'm a graphic designer, I can make you "
                                   "an overlay") != [])
    check("'connect my controller' is not a pitch",
          signs_in("I need to connect my controller later") == [])


def test_she_answers_a_scammer_once():
    print("\n--- answered once, warily, then skipped ---")
    queue = SignalQueue()
    room = TwitchChatSource(queue)
    for m in SCAMMER[:3]:
        room._on_line(privmsg("determined811", m))
        room.flush()
    signals = drain(queue)
    flagged = [s for s in signals if s.context.get("scam_suspect")]
    check("the reply to the third message carries the warning",
          len(flagged) == 1 and "discord" in flagged[0].text.lower(),
          str([(s.text[:20], s.context.get("scam_suspect")) for s in signals]))
    check("with the reasons for the notebook",
          "moves you to a private app" in flagged[0].context["scam_reasons"])

    room._on_line(privmsg("determined811", "Determined_8"))
    check("after one wary reply, his flagged messages are skipped",
          room.flush() is None)

    known = TwitchChatSource(SignalQueue(), known_users={"buddy"})
    for m in ("let's connect on discord", "collab sometime?"):
        known._on_line(privmsg("buddy", m))
    sig = known.flush()
    check("a known regular is never flagged",
          sig is not None and not sig.context.get("scam_suspect"))


def test_a_ban_ends_the_conversation():
    print("\n--- banned: nothing of his is answered ---")
    queue = SignalQueue()
    room = TwitchChatSource(queue)
    room._on_line(privmsg("determined811", "you're amazing"))
    room.flush()                                   # a reply waiting in the queue
    room._on_line(privmsg("determined811", "add me on discord"))  # in the batch
    room._on_line(privmsg("someoneelse", "what champ is next?"))

    room._on_line(ban("determined811"))
    waiting = drain(queue)
    check("his waiting reply and his batched message are gone",
          not any(s.context.get("user") == "determined811" for s in waiting),
          str([s.context.get("user") for s in waiting]))
    check("she says one short line about it, without his name",
          any(s.context.get("moderation") == "ban"
              and "determined811" not in s.text for s in waiting))
    check("someone else's message is untouched",
          any(m.user == "someoneelse" for m in room._buffer))

    room._on_line(privmsg("determined811", "please unban"))
    check("he is ignored for the rest of the stream",
          not any(m.user == "determined811" for m in room._buffer))

    d = Dispatcher(SignalQueue())
    d.moderation = room
    d.set_inflight(Signal(source="chat", priority=5, text="x",
                          context={"user": "determined811",
                                   "platform": "twitch"}))
    check("a reply already being written for him is not spoken",
          d.inflight_still_wanted() is False)
    d.set_inflight(Signal(source="chat", priority=5, text="y",
                          context={"user": "someoneelse", "platform": "twitch"}))
    check("a reply to anyone else still is", d.inflight_still_wanted() is True)
    d.set_inflight(Signal(source="game", priority=3, text="z"))
    check("and game lines are never affected", d.inflight_still_wanted())


def test_timeouts_and_deletions():
    print("\n--- timeouts end, deletions are precise ---")
    queue = SignalQueue()
    room = TwitchChatSource(queue)
    room._on_line(ban("loud", seconds=1))
    check("a timeout is noted as a timeout",
          any(s.context.get("moderation") == "timeout" for s in drain(queue)))
    room._on_line(privmsg("loud", "sorry"))
    check("ignored while it lasts", not room._buffer)
    room._removed["twitch:loud"] = time.time() - 1      # it has run out
    room._on_line(privmsg("loud", "ok I'm back, what rank are you?"))
    check("heard again once it is over", len(room._buffer) == 1)

    room._on_line(privmsg("pat", "first message here"))
    room._on_line(privmsg("pat", "something rude"))
    room._on_line("@login=pat;room-id=1;target-msg-id=abc;tmi-sent-ts=2 "
                  f":tmi.twitch.tv CLEARMSG #{CHAN} :something rude")
    texts = [m.text for m in room._buffer if m.user == "pat"]
    check("a deleted message is dropped, his others kept",
          texts == ["first message here"], str(texts))

    room._on_line(f"@room-id=1;tmi-sent-ts=2 :tmi.twitch.tv CLEARCHAT #{CHAN}")
    check("a cleared chat drops everything waiting", not room._buffer)

    tags, rest = split_tags("@a=1;b= :rest of line")
    check("tags are parsed", tags == {"a": "1", "b": ""} and rest == ":rest of line")
    room._on_line(privmsg("plain", "hello there friend"))
    check("tagged messages are still read",
          any(m.user == "plain" for m in room._buffer))


def test_youtube_removal():
    print("\n--- YouTube: removing someone's messages is a ban ---")
    queue = SignalQueue()
    room = TwitchChatSource(queue)
    room.post("youtube", "Spammy", "dm me for cheap viewers",
              user_key="youtube:UCspam")
    room.moderate("youtube", user_key="youtube:UCspam", kind="ban")
    check("their waiting message is gone", not room._buffer)
    room.post("youtube", "Spammy", "hello?", user_key="youtube:UCspam")
    check("and later ones ignored", not room._buffer)


def main():
    test_the_scam_is_recognised()
    test_she_answers_a_scammer_once()
    test_a_ban_ends_the_conversation()
    test_timeouts_and_deletions()
    test_youtube_removal()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
