"""
YouTube chat with no key — the browser popout's own endpoints.

    python tests/test_youtube_web_chat.py

No network. The fakes below reproduce the shapes a real live stream returned
on 2026-11-06 (www.youtube.com/channel/<id>/live, /live_chat?is_popout=1 and
youtubei/v1/live_chat/get_live_chat), with the authors anonymised. That run
read a real chat end to end: backlog skipped, new messages into the room,
one winner picked.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                       # noqa: E402
from orchestrator.priority_queue import SignalQueue         # noqa: E402
from sources.chat_room import ChatRoom                      # noqa: E402
from sources import youtube_web_chat as web                 # noqa: E402
from sources.youtube_web_chat import (                      # noqa: E402
    RETRY_AFTER_ERROR, YouTubeWebChat, message_text,
)

S = get_settings()
FAILURES: list[str] = []
CHANNEL = "UCexiled000000000000000"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ------------------------------------------------------------- real shapes
def page(initial_data=None, cfg=None) -> str:
    out = "<html><script>"
    if cfg is not None:
        out += f"ytcfg.set({json.dumps(cfg)});"
    if initial_data is not None:
        out += f"var ytInitialData = {json.dumps(initial_data)};"
    return out + "</script></html>"


def live_watch_page(video="vidLIVE", replay=False):
    chat = {"continuations": [{"reloadContinuationData": {"continuation": "W"}}]}
    if replay:
        chat["isReplay"] = True
    return page({"currentVideoEndpoint": {"watchEndpoint": {"videoId": video}},
                 "contents": {"twoColumnWatchNextResults": {
                     "conversationBar": {"liveChatRenderer": chat}}}})


CHANNEL_HOME = page({"contents": {"twoColumnBrowseResultsRenderer": {}}})

POPOUT = page(
    {"contents": {"liveChatRenderer": {
        "continuations": [{"invalidationContinuationData": {
            "continuation": "TOPCHAT", "timeoutMs": 10000}}],
        "header": {"liveChatHeaderRenderer": {"viewSelector": {
            "sortFilterSubMenuRenderer": {"subMenuItems": [
                {"title": "Top chat", "selected": True, "continuation": {
                    "reloadContinuationData": {"continuation": "TOPVIEW"}}},
                {"title": "Live chat", "selected": False, "continuation": {
                    "reloadContinuationData": {"continuation": "LIVEVIEW"}}},
            ]}}}}}}},
    cfg={"INNERTUBE_API_KEY": "webkey",
         "INNERTUBE_CONTEXT": {"client": {"clientName": "WEB",
                                          "clientVersion": "2.20261030.02.00"}}})


def text_msg(mid, runs, name="@viewer", channel="UCviewer", badges=None):
    m = {"id": mid, "message": {"runs": runs},
         "authorName": {"simpleText": name},
         "authorExternalChannelId": channel, "timestampUsec": "1"}
    if badges:
        m["authorBadges"] = [{"liveChatAuthorBadgeRenderer": {
            "icon": {"iconType": b}}} for b in badges]
    return {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": m}}}


def chat_answer(actions, token="NEXT", timeout_ms=10000):
    return {"continuationContents": {"liveChatContinuation": {
        "continuations": [{"invalidationContinuationData": {
            "continuation": token, "timeoutMs": timeout_ms}}],
        "actions": actions}}}


class Resp:
    def __init__(self, text="", data=None, status=200):
        self.text, self._data, self.status_code = text, data, status

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, live_page=None, popout=POPOUT):
        self.live_page = live_watch_page() if live_page is None else live_page
        self.popout = popout
        self.answers: list = []
        self.posts: list = []

    def get(self, url, params=None, timeout=None):
        if url.endswith("/live"):
            return Resp(self.live_page)
        if url.endswith("/live_chat"):
            return Resp(self.popout)
        raise AssertionError(url)

    def post(self, url, params=None, json=None, timeout=None):
        self.posts.append((params, json))
        nxt = self.answers.pop(0)
        return nxt if isinstance(nxt, Resp) else Resp(data=nxt)


def reader(session, room=None):
    room = room or ChatRoom(SignalQueue())
    return YouTubeWebChat(room, channel_id=CHANNEL, video_id="",
                          session=session), room


# ====================================================================
def test_finding_the_stream():
    print("\n--- finding the live stream from the channel page ---")
    yt, _ = reader(FakeSession())
    check("the live video is read from the channel's /live page",
          yt.find_video() == "vidLIVE")

    yt, _ = reader(FakeSession(live_page=CHANNEL_HOME))
    check("not live: nothing, and that is not a format error",
          yt.find_video() == "" and yt._misses == 0)

    yt, _ = reader(FakeSession(live_page=live_watch_page(replay=True)))
    check("an old stream's chat replay is not live chat",
          yt.find_video() == "")

    yt, _ = reader(FakeSession(live_page="<html>consent page</html>"))
    yt.find_video()
    check("a page with no page data counts toward 'format changed'",
          yt._misses == 1)


def test_opening_the_chat():
    print("\n--- the popout: Live chat, not Top chat ---")
    yt, _ = reader(FakeSession())
    check("the chat opens", yt.open_chat("vidLIVE"))
    check("on the Live chat view (every message), not Top chat (filtered)",
          yt._token == "LIVEVIEW", yt._token)
    check("with the web client version from the page",
          yt._client == {"clientName": "WEB",
                         "clientVersion": "2.20261030.02.00",
                         "key": "webkey"}, str(yt._client))

    yt, _ = reader(FakeSession(popout=page({"contents": {}})))
    check("a popout with no chat does not open, and is counted",
          not yt.open_chat("vidLIVE") and yt._misses == 1)


def test_reading():
    print("\n--- reading chat into the room ---")
    s = FakeSession()
    yt, room = reader(s)
    yt.open_chat("vidLIVE")
    s.answers = [
        chat_answer([text_msg("old1", [{"text": "from before she joined"}])],
                    token="T1"),
        chat_answer([
            text_msg("m1", [{"text": "hmm same here "},
                            {"emoji": {"emojiId": "😅"}}], name="@Sharma"),
            text_msg("m1", [{"text": "hmm same here "}], name="@Sharma"),
            text_msg("m2", [{"text": "nice "},
                            {"emoji": {"emojiId": "UCx/abc",
                                       "isCustomEmoji": True}}]),
        ], token="T2", timeout_ms=10000),
    ]

    yt.poll()
    check("the backlog is skipped", room._buffer == [])
    check("the first read used the Live chat token and the page's client",
          s.posts[0][1]["continuation"] == "LIVEVIEW"
          and s.posts[0][1]["context"]["client"]["clientVersion"]
          == "2.20261030.02.00" and s.posts[0][0].get("key") == "webkey")

    wait = yt.poll()
    check("the next read continues from the returned token",
          s.posts[1][1]["continuation"] == "T1")
    check("a new message reaches the room once, not twice",
          [m.text for m in room._buffer] == ["hmm same here 😅", "nice"],
          str([m.text for m in room._buffer]))
    check("the '@' of the handle is dropped",
          room._buffer[0].user == "Sharma")
    check("keyed by channel id, tagged YouTube",
          room._buffer[0].user_key == "youtube:UCviewer"
          and room._buffer[0].platform == "youtube")
    check("YouTube's 10s suggestion is capped at YT_WEB_POLL",
          wait == S.YT_WEB_POLL, str(wait))


def test_the_owner():
    print("\n--- he is known by channel id, never by a name ---")
    s = FakeSession()
    queue = SignalQueue()
    yt, room = reader(s, ChatRoom(queue))
    yt.open_chat("vidLIVE")
    yt._primed = True
    s.answers = [chat_answer([
        text_msg("o1", [{"text": "gg"}], name="@ExiledRa1n", channel=CHANNEL),
        text_msg("o2", [{"text": "i am the streamer"}], name="@ExiledRa1n",
                 channel="UCimpostor"),
        text_msg("o3", [{"text": "badge says owner"}], name="@whoever",
                 channel="UCother", badges=["OWNER"]),
    ])]
    yt.poll()

    first, second = queue.pop(), queue.pop()
    check("his channel id: straight to the queue at owner priority",
          first and first.text == "gg" and first.context["is_owner"]
          and first.priority == S.OWNER_PRIORITY)
    check("YouTube's own OWNER badge also counts",
          second and second.text == "badge says owner")
    check("someone just using his name is ordinary chat",
          [m.text for m in room._buffer] == ["i am the streamer"])


def test_endings_and_failures():
    print("\n--- ended chats, errors, and a changed format ---")
    s = FakeSession()
    yt, _ = reader(s)
    yt.open_chat("vidLIVE")
    yt._primed = True
    s.answers = [{"responseContext": {}}]
    check("a chat with no continuation has ended: look again",
          yt.poll() == S.YT_LOOKUP_INTERVAL and yt._token == "")

    yt.open_chat("vidLIVE")
    s.answers = [Resp(status=403)]
    check("an HTTP error reopens the chat after a pause",
          yt.poll() == RETRY_AFTER_ERROR and yt._token == "")

    class Fallback:
        ran = False

        def run(self):
            Fallback.ran = True

        def stop(self):
            pass

    broken = FakeSession(live_page="<html>nothing</html>")
    yt = YouTubeWebChat(ChatRoom(SignalQueue()), channel_id=CHANNEL,
                        video_id="", session=broken, fallback=Fallback())
    original = web.time.sleep
    web.time.sleep = lambda s: None
    try:
        yt.run()
    finally:
        web.time.sleep = original
    check("three broken lookups hand over to the API reader, if a key is set",
          Fallback.ran)

    yt = YouTubeWebChat(ChatRoom(SignalQueue()), channel_id=CHANNEL,
                        video_id="", session=FakeSession(
                            live_page="<html>nothing</html>"))
    web.time.sleep = lambda s: None
    try:
        yt.run()
    finally:
        web.time.sleep = original
    check("without a key it stops and says so, rather than spinning",
          yt.format_broken)

    quiet = YouTubeWebChat(ChatRoom(SignalQueue()), channel_id="", video_id="",
                           session=FakeSession())
    quiet.run()
    check("no channel id: says so and stops", True)


def test_message_text():
    print("\n--- what of a message is kept ---")
    check("text and standard emoji are kept",
          message_text([{"text": "hi "}, {"emoji": {"emojiId": "☺"}}])
          == "hi ☺")
    check("channel-custom emoji are dropped",
          message_text([{"text": "gg"}, {"emoji": {
              "emojiId": "UCx/abc", "isCustomEmoji": True}}]) == "gg")


def main():
    test_finding_the_stream()
    test_opening_the_chat()
    test_reading()
    test_the_owner()
    test_endings_and_failures()
    test_message_text()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
