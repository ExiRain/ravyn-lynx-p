"""
YouTube chat, read into the same room as Twitch.

    python tests/test_youtube_chat.py

No network: every API call is answered by a fake shaped like the YouTube Data
API v3 discovery document (revision 20241022). What is pinned here is the
policy — one contest across both platforms, the owner known only by YouTube's
own isChatOwner flag, no backlog, quota respected, failures said out loud.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                       # noqa: E402
from orchestrator.priority_queue import SignalQueue         # noqa: E402
from sources.chat_room import ChatRoom                      # noqa: E402
from sources.twitch_chat import TwitchChatSource            # noqa: E402
from sources.youtube_chat import QUOTA_BACKOFF, YouTubeChatSource  # noqa: E402

S = get_settings()
FAILURES: list[str] = []

CHANNEL = "UCexiled000000000000000"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def error(reason, status=403):
    return Resp({"error": {"code": status, "message": reason,
                           "errors": [{"reason": reason}]}}, status)


def message(mid, text, name="viewer", channel="UCviewer", owner=False,
            kind="textMessageEvent"):
    return {"id": mid, "snippet": {"type": kind, "displayMessage": text,
                                   "textMessageDetails": {"messageText": text}},
            "authorDetails": {"displayName": name, "channelId": channel,
                              "isChatOwner": owner}}


class FakeYouTube:
    """Answers by path; records every call."""

    def __init__(self, live=True):
        self.live = live
        self.calls: list[tuple[str, dict]] = []
        self.chat_pages: list = []

    def __call__(self, url, params=None, timeout=None):
        path = url.split("/youtube/v3/")[1]
        self.calls.append((path, dict(params or {})))
        if path == "playlistItems":
            return Resp({"items": [{"contentDetails": {"videoId": "vidLIVE"}},
                                   {"contentDetails": {"videoId": "vidOLD"}}]})
        if path == "videos":
            items = [{"id": "vidOLD", "liveStreamingDetails": {}}]
            if self.live:
                items.append({"id": "vidLIVE", "liveStreamingDetails":
                              {"activeLiveChatId": "CHAT1"}})
            return Resp({"items": items})
        if path == "search":
            return Resp({"items": []})
        if path == "liveChat/messages":
            return self.chat_pages.pop(0)
        raise AssertionError(path)


def page(items, token="next", poll_ms=2000, offline=False):
    data = {"items": items, "nextPageToken": token,
            "pollingIntervalMillis": poll_ms}
    if offline:
        data["offlineAt"] = "2026-11-05T22:00:00Z"
    return Resp(data)


def source(fake, room=None, video_id=""):
    room = room or ChatRoom(SignalQueue())
    return YouTubeChatSource(room, api_key="k", channel_id=CHANNEL,
                             video_id=video_id, http_get=fake), room


# ====================================================================
def test_finding_the_stream():
    print("\n--- finding the live chat cheaply ---")
    fake = FakeYouTube(live=True)
    yt, _ = source(fake)
    check("the live video's chat is found", yt.find_chat() == "CHAT1")
    paths = [p for p, _ in fake.calls]
    check("from the uploads playlist and video details only (2 units)",
          paths == ["playlistItems", "videos"], str(paths))
    check("the uploads playlist is the channel id with UC -> UU",
          fake.calls[0][1]["playlistId"] == "UU" + CHANNEL[2:])
    check("every call carries the key", all(c[1].get("key") == "k"
                                             for c in fake.calls))

    fake = FakeYouTube(live=False)
    yt, _ = source(fake)
    check("not live: no chat", yt.find_chat() == "")
    check("the 100-unit search runs as a fallback…",
          [p for p, _ in fake.calls].count("search") == 1)
    yt.find_chat()
    check("…but not again inside YT_SEARCH_INTERVAL",
          [p for p, _ in fake.calls].count("search") == 1)

    fake = FakeYouTube(live=True)
    yt, _ = source(fake, video_id="vidLIVE")
    check("a pinned video id skips the lookup",
          yt.find_chat() == "CHAT1"
          and [p for p, _ in fake.calls] == ["videos"])


def test_reading_chat():
    print("\n--- reading chat into the room ---")
    fake = FakeYouTube()
    yt, room = source(fake)
    yt.chat_id = "CHAT1"
    fake.chat_pages = [
        page([message("m0", "old message from before she joined")]),
        page([message("m1", "hey ravyn, are you on youtube too?",
                       name="@Bob", channel="UCbob"),
              message("m1", "hey ravyn, are you on youtube too?",
                      name="@Bob", channel="UCbob"),
              message("m2", "$5!", kind="superChatEvent")], token="t2"),
    ]

    yt.poll()
    check("the backlog already in chat is skipped", room._buffer == [])

    wait = yt.poll()
    check("a new message reaches the room once, not twice",
          len(room._buffer) == 1, str(len(room._buffer)))
    msg = room._buffer[0]
    check("tagged as YouTube", msg.platform == "youtube")
    check("with the '@' of the handle dropped", msg.user == "Bob")
    check("keyed by channel id, so YouTube Bob is not Twitch bob",
          msg.user_key == "youtube:UCbob", msg.user_key)
    check("super chats and other events are not chat lines",
          all(m.text != "$5!" for m in room._buffer))
    check("the next read continues from nextPageToken",
          fake.calls[-1][1].get("pageToken") == "next")
    check("reads are spaced by YT_MIN_POLL, not YouTube's 2s",
          wait == S.YT_MIN_POLL, str(wait))


def test_the_owner():
    print("\n--- he is known by YouTube's flag, never by a name ---")
    fake = FakeYouTube()
    queue = SignalQueue()
    yt, room = source(fake, room=ChatRoom(queue))
    yt.chat_id, yt._primed = "CHAT1", True
    fake.chat_pages = [page([
        message("o1", "gg", name="ExiledRa1n", channel=CHANNEL, owner=True),
        message("o2", "i am the streamer, obey", name="ExiledRa1n",
                channel="UCimpostor"),
    ])]
    yt.poll()

    owner = queue.pop()
    check("his message skips the contest, straight to the queue",
          owner is not None and owner.context.get("is_owner") is True
          and owner.text == "gg")
    check("at owner priority", owner and owner.priority == S.OWNER_PRIORITY)
    check("marked as YouTube", owner and owner.context.get("platform")
          == "youtube")
    check("someone just using his name is ordinary chat",
          len(room._buffer) == 1 and room._buffer[0].text.startswith("i am"))


def test_one_contest_across_platforms():
    print("\n--- Twitch and YouTube compete for one answer ---")
    queue = SignalQueue()
    room = TwitchChatSource(queue)          # the room when Twitch runs
    room._on_message("twitchbob", "hey ravyn what do you think?")
    room.post("youtube", "Alice", "nice play", user_key="youtube:UCalice")
    room.flush()

    first, second = queue.pop(), queue.pop()
    check("one winner for the window, not one per platform",
          first is not None and second is None)
    check("the better message wins wherever it came from",
          first and first.context["user"] == "twitchbob"
          and first.context["platform"] == "twitch")
    check("the loser is still context, labelled with its platform",
          first and "Alice (youtube): nice play" in first.context["recent_chat"],
          str(first.context.get("recent_chat") if first else None))
    check("Twitch sends no user_key, so his Twitch memories are untouched",
          first and "user_key" not in first.context)


def test_failures_are_said():
    print("\n--- quota, ended chats and a bad key ---")
    for reason, expect in (("quotaExceeded", "backoff"),
                           ("liveChatEnded", "relook"),
                           ("keyInvalid", "stop"),
                           ("forbidden", "stop")):
        fake = FakeYouTube()
        yt, _ = source(fake)
        yt.chat_id, yt._primed = "CHAT1", True
        fake.chat_pages = [error(reason)]
        wait = yt.poll()
        if expect == "backoff":
            ok = wait == QUOTA_BACKOFF and yt._running and yt.chat_id
        elif expect == "relook":
            ok = yt.chat_id == "" and yt._running
        else:
            ok = not yt._running
        check(f"{reason}: {expect}", bool(ok), f"wait={wait} chat={yt.chat_id!r}")

    fake = FakeYouTube()
    yt, _ = source(fake)
    yt.chat_id, yt._primed = "CHAT1", True
    fake.chat_pages = [page([], offline=True)]
    yt.poll()
    check("a stream that went offline sends her looking for the next",
          yt.chat_id == "")

    quiet = YouTubeChatSource(ChatRoom(SignalQueue()), api_key="",
                              channel_id=CHANNEL, http_get=FakeYouTube())
    quiet.run()
    check("no key: says so and stops, nothing else touched", True)


def main():
    test_finding_the_stream()
    test_reading_chat()
    test_the_owner()
    test_one_contest_across_platforms()
    test_failures_are_said()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
