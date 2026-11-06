"""
YouTube chat without a key — read the way the browser's chat popout reads it.

No Google Cloud, no daily quota, and a message reaches her in a few seconds
rather than YT_MIN_POLL. The cost: these are YouTube's own web endpoints, not
a published API, so a change on their side can break it without notice. When
that happens it says so in the log, and if RAVYN_YT_API_KEY is set it hands
over to the official reader (sources/youtube_chat.py) instead of going deaf.

The flow, checked against a real live stream on 2026-11-06:

  1. www.youtube.com/channel/<id>/live — while you are live this serves the
     watch page of the stream. Its ytInitialData carries the video id
     (currentVideoEndpoint) and a liveChatRenderer when there is a live chat.
  2. www.youtube.com/live_chat?v=<video>&is_popout=1 — the chat popout. Its
     ytcfg gives the web client name and version; its header has two views,
     "Top chat" (filtered, the default) and "Live chat" (every message). She
     reads Live chat.
  3. POST youtubei/v1/live_chat/get_live_chat with that view's continuation:
     the first answer is the backlog (skipped — she does not answer it) and a
     next continuation; every later answer is the new messages and the next.

Messages arrive in the same ChatRoom as Twitch (sources/chat_room.py). The
owner is the author whose channel id is YT_CHANNEL_ID — set by YouTube, not a
display name anyone can copy.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque

from app.settings import get_settings

settings = get_settings()

BASE = "https://www.youtube.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/130.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
# Without these, a European visitor gets the cookie-consent page instead.
COOKIES = {"SOCS": "CAI", "CONSENT": "YES+cb"}

# Lookups that reached YouTube but found no chat where the format says there
# should be one. Past this, the page format has probably changed.
BROKEN_AFTER = 3
RETRY_AFTER_ERROR = 30.0

_EMBED = re.compile(r'(?:var\s+|window\[")ytInitialData"?\]?\s*=\s*')
_YTCFG = re.compile(r'ytcfg\.set\((\{.*?\})\);')


def embedded_initial_data(html: str) -> dict | None:
    m = _EMBED.search(html or "")
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html, m.end())[0]
    except ValueError:
        return None


def embedded_client(html: str) -> dict:
    cfg: dict = {}
    for m in _YTCFG.finditer(html or ""):
        try:
            cfg.update(json.loads(m.group(1)))
        except ValueError:
            pass
    client = (cfg.get("INNERTUBE_CONTEXT") or {}).get("client") or {}
    return {"clientName": client.get("clientName") or "WEB",
            "clientVersion": client.get("clientVersion") or "",
            "key": cfg.get("INNERTUBE_API_KEY") or ""}


def message_text(runs: list) -> str:
    """Text runs joined; standard emoji kept, channel-custom emoji dropped."""
    out = []
    for run in runs or []:
        if "text" in run:
            out.append(run["text"])
        elif "emoji" in run:
            emoji = run["emoji"]
            if not emoji.get("isCustomEmoji") and emoji.get("emojiId"):
                out.append(emoji["emojiId"])
    return "".join(out).strip()


def next_continuation(cont: dict) -> tuple[str, float]:
    """(token, seconds YouTube says to wait) from a liveChatContinuation."""
    for entry in cont.get("continuations") or []:
        for kind in ("invalidationContinuationData", "timedContinuationData",
                     "reloadContinuationData"):
            data = entry.get(kind)
            if data and data.get("continuation"):
                return data["continuation"], (data.get("timeoutMs") or 0) / 1000
    return "", 0.0


class YouTubeWebChat:

    def __init__(self, room, channel_id: str | None = None,
                 video_id: str | None = None, fallback=None, session=None):
        self.room = room
        self.channel = (settings.YT_CHANNEL_ID if channel_id is None
                        else channel_id)
        self.video_override = (settings.YT_VIDEO_ID if video_id is None
                               else video_id)
        self.fallback = fallback        # the API reader, if a key is set
        self._session = session         # injected by tests
        self._running = True

        self.video_id = ""
        self._client: dict = {}
        self._token = ""
        self._primed = False
        self._seen: deque = deque(maxlen=1000)
        self._seen_set: set = set()
        self._misses = 0
        self._looking_logged = False

    # -----------------------------------------------------------------
    # http
    # -----------------------------------------------------------------

    def _http(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
            self._session.cookies.update(COOKIES)
        return self._session

    def _get_page(self, path: str, params: dict | None = None) -> str | None:
        try:
            resp = self._http().get(f"{BASE}{path}", params=params,
                                    timeout=15)
        except Exception as e:
            print(f"[youtube] Could not reach YouTube: {e}")
            return None
        if getattr(resp, "status_code", 200) >= 400:
            print(f"[youtube] {path} answered HTTP {resp.status_code}")
            return None
        return resp.text

    # -----------------------------------------------------------------
    # finding the stream and opening its chat
    # -----------------------------------------------------------------

    def find_video(self) -> str:
        """The live video id, or "" if nothing of his is live with chat."""
        if self.video_override:
            return self.video_override
        html = self._get_page(f"/channel/{self.channel}/live")
        if html is None:
            return ""
        data = embedded_initial_data(html)
        if data is None:
            self._miss("the channel's /live page had no page data — a "
                       "consent or sign-in page, or a format change")
            return ""

        video = ((data.get("currentVideoEndpoint") or {})
                 .get("watchEndpoint") or {}).get("videoId", "")
        chat = (((data.get("contents") or {})
                 .get("twoColumnWatchNextResults") or {})
                .get("conversationBar") or {}).get("liveChatRenderer")
        if video and chat and not chat.get("isReplay"):
            self._misses = 0
            self._looking_logged = False
            print(f"[youtube] Live: video {video} — opening its chat")
            return video

        # Not live is the ordinary answer, not a failure.
        if not self._looking_logged:
            self._looking_logged = True
            print("[youtube] Not live on YouTube yet — checking every "
                  f"{settings.YT_LOOKUP_INTERVAL:.0f}s")
        return ""

    def open_chat(self, video_id: str) -> bool:
        html = self._get_page("/live_chat",
                              {"v": video_id, "is_popout": "1"})
        if html is None:
            return False
        data = embedded_initial_data(html)
        chat = ((data or {}).get("contents") or {}).get("liveChatRenderer")
        if not chat:
            self._miss("the chat popout had no live chat in it — chat may be "
                       "off for this stream, or the format changed")
            return False

        self._client = embedded_client(html)
        token = ""
        views = (((chat.get("header") or {}).get("liveChatHeaderRenderer")
                  or {}).get("viewSelector") or {}).get(
                      "sortFilterSubMenuRenderer", {}).get("subMenuItems", [])
        for view in views:
            if view.get("title") == "Live chat":
                token = ((view.get("continuation") or {})
                         .get("reloadContinuationData") or {}).get(
                             "continuation", "")
        if not token:       # fall back to whatever view the page opened on
            token, _ = next_continuation(chat)
        if not token:
            self._miss("the chat popout had no continuation token")
            return False

        self._misses = 0
        self._token = token
        self._primed = False
        return True

    def _miss(self, why: str) -> None:
        self._misses += 1
        print(f"[youtube] {why} ({self._misses}/{BROKEN_AFTER})")

    @property
    def format_broken(self) -> bool:
        return self._misses >= BROKEN_AFTER

    # -----------------------------------------------------------------
    # reading
    # -----------------------------------------------------------------

    def poll(self) -> float:
        """One read. Returns how long to wait before the next."""
        params = {"prettyPrint": "false"}
        if self._client.get("key"):
            params["key"] = self._client["key"]
        body = {"context": {"client": {
                    "clientName": self._client.get("clientName", "WEB"),
                    "clientVersion": self._client.get("clientVersion", ""),
                    "hl": "en", "gl": "US"}},
                "continuation": self._token}
        try:
            resp = self._http().post(
                f"{BASE}/youtubei/v1/live_chat/get_live_chat",
                params=params, json=body, timeout=15)
            data = resp.json() if getattr(resp, "status_code", 200) < 400 \
                else None
        except Exception as e:
            print(f"[youtube] Chat read failed: {e}")
            return RETRY_AFTER_ERROR
        if data is None:
            print(f"[youtube] Chat read answered HTTP "
                  f"{getattr(resp, 'status_code', '?')} — reopening the chat")
            self._reset()
            return RETRY_AFTER_ERROR

        cont = (data.get("continuationContents") or {}).get(
            "liveChatContinuation")
        token, wait = next_continuation(cont or {})
        if not cont or not token:
            print("[youtube] Chat ended — looking for the next stream")
            self._reset()
            return settings.YT_LOOKUP_INTERVAL

        actions = cont.get("actions") or []
        if not self._primed:
            self._primed = True
            for msg in self._text_messages(actions):
                self._remember(msg.get("id"))
            print(f"[youtube] Joined chat — earlier messages skipped")
        else:
            for msg in self._text_messages(actions):
                self._handle(msg)

        self._token = token
        return max(1.5, min(wait or settings.YT_WEB_POLL,
                            settings.YT_WEB_POLL))

    @staticmethod
    def _text_messages(actions: list) -> list[dict]:
        out = []
        for action in actions:
            item = ((action.get("addChatItemAction") or {}).get("item")
                    or {})
            msg = item.get("liveChatTextMessageRenderer")
            if msg:
                out.append(msg)
        return out

    def _remember(self, msg_id) -> bool:
        """True if new."""
        if not msg_id or msg_id in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(msg_id)
        self._seen_set.add(msg_id)
        return True

    def _handle(self, msg: dict) -> None:
        if not self._remember(msg.get("id")):
            return
        text = message_text((msg.get("message") or {}).get("runs"))
        name = ((msg.get("authorName") or {}).get("simpleText") or "") \
            .lstrip("@").strip()
        if not text or not name:
            return
        channel = msg.get("authorExternalChannelId") or ""
        badges = {((b.get("liveChatAuthorBadgeRenderer") or {}).get("icon")
                   or {}).get("iconType")
                  for b in msg.get("authorBadges") or []}
        is_owner = bool((channel and channel == self.channel)
                        or "OWNER" in badges)
        self.room.post("youtube", name, text,
                       user_key=f"youtube:{channel}" if channel else "",
                       is_owner=is_owner)

    def _reset(self) -> None:
        self.video_id = ""
        self._token = ""
        self._primed = False

    # -----------------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not self.channel.startswith("UC") and not self.video_override:
            print("[youtube] Disabled — set RAVYN_YT_CHANNEL_ID (starts with "
                  "UC) so she can find your live stream.")
            return

        self.room.start()
        print("[youtube] Listening for a live stream (no API key needed)")
        while self._running:
            if self.format_broken:
                if self.fallback is not None:
                    print("[youtube] The web chat format looks changed — "
                          "switching to the API reader (RAVYN_YT_API_KEY)")
                    self.fallback.run()
                else:
                    print("[youtube] The web chat format looks changed and "
                          "there is no RAVYN_YT_API_KEY to fall back on — "
                          "YouTube chat is off until restart.")
                return

            if not self._token:
                self.video_id = self.find_video()
                if not self.video_id or not self.open_chat(self.video_id):
                    self._reset()
                    time.sleep(settings.YT_LOOKUP_INTERVAL)
                    continue

            wait = self.poll()
            if self._running:
                time.sleep(wait)

    def stop(self) -> None:
        self._running = False
        if self.fallback is not None:
            self.fallback.stop()
