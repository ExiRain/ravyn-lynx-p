"""
YouTube chat source — read-only, YouTube Data API v3.

Posts every chat message into the shared ChatRoom (sources/chat_room.py), the
same room Twitch posts into, so she has one stream of messages to pick from.

Finding the chat. A live stream's chat has its own id (activeLiveChatId),
which only exists while you are live. It is found cheaply from your channel:
the newest uploads (playlistItems, 1 unit) and their live details (videos,
1 unit). If that finds nothing, a search (100 units) is the fallback, rationed
by YT_SEARCH_INTERVAL. RAVYN_YT_VIDEO_ID skips the lookup.

Reading it. liveChatMessages.list returns new messages, a nextPageToken for
the next read, and pollingIntervalMillis. Each read costs 5 units of the free
10,000 a day, so reads are spaced at least YT_MIN_POLL apart. The page that is
already there when she joins is skipped — she does not answer a backlog.

Who is the owner. YouTube marks the channel owner's own messages with
authorDetails.isChatOwner. That is the only thing trusted: display names on
YouTube are not unique, so a name match would let anyone who calls themselves
ExiledRain take his priority and skip the voice gate.

Field names are from the API's discovery document (revision 20241022). The
quota costs could not be checked against Google's docs from where this was
written; the startup log prints what each lookup found, and errors print
YouTube's own reason, so a wrong assumption shows up as a line, not silence.
"""

from __future__ import annotations

import time
from collections import deque

from app.settings import get_settings

settings = get_settings()

API = "https://youtube.googleapis.com/youtube/v3"

# A chat that is gone: find the stream again.
CHAT_GONE = {"liveChatEnded", "liveChatNotFound", "liveChatDisabled"}
# YouTube will not let this key read chat at all. The API's own definition
# lists sign-in scopes for reading chat; a plain key is expected to work for a
# public stream, and if it does not, this is how that shows — once, loudly.
NOT_ALLOWED = {"forbidden", "insufficientPermissions", "authError",
               "unauthorized", "loginRequired"}
# Out of quota until Google resets it (midnight Pacific).
QUOTA = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}
# The key itself is wrong: nothing will work until it is fixed.
BAD_KEY = {"keyInvalid", "keyExpired", "accessNotConfigured", "badRequest"}

QUOTA_BACKOFF = 3600.0


class YouTubeChatSource:

    def __init__(self, room, api_key: str | None = None,
                 channel_id: str | None = None, video_id: str | None = None,
                 http_get=None, alerts=None):
        self.room = room
        self.alerts = alerts    # see YouTubeWebChat: Super Chats, members
        self.key = settings.YT_API_KEY if api_key is None else api_key
        self.channel = (settings.YT_CHANNEL_ID if channel_id is None
                        else channel_id)
        self.video_override = (settings.YT_VIDEO_ID if video_id is None
                               else video_id)
        self._http_get = http_get       # injected by tests; requests otherwise
        self._running = True

        self.chat_id = ""
        self._page = None
        self._primed = False
        self._seen: deque = deque(maxlen=500)
        self._last_search = 0.0
        self._looking_logged = False

    # -----------------------------------------------------------------
    # http
    # -----------------------------------------------------------------

    def _get(self, path: str, params: dict) -> tuple[dict | None, str]:
        """(json, "") on success, (None, YouTube's error reason) on failure."""
        get = self._http_get
        if get is None:
            import requests
            get = requests.get
        try:
            resp = get(f"{API}/{path}", params={**params, "key": self.key},
                       timeout=10)
        except Exception as e:
            return None, f"network: {e}"
        try:
            data = resp.json()
        except Exception:
            data = {}
        if getattr(resp, "status_code", 200) >= 400 or "error" in data:
            err = data.get("error") or {}
            reasons = [e.get("reason") for e in err.get("errors") or []
                       if isinstance(e, dict)]
            return None, (reasons[0] if reasons and reasons[0]
                          else f"HTTP {getattr(resp, 'status_code', '?')}: "
                               f"{err.get('message', '')[:120]}")
        return data, ""

    # -----------------------------------------------------------------
    # finding the live chat
    # -----------------------------------------------------------------

    def _live_chat_of(self, video_ids: list[str]) -> str:
        if not video_ids:
            return ""
        data, err = self._get("videos", {"part": "liveStreamingDetails",
                                         "id": ",".join(video_ids[:50])})
        if data is None:
            self._report(err)
            return ""
        for item in data.get("items") or []:
            chat = (item.get("liveStreamingDetails") or {}).get(
                "activeLiveChatId")
            if chat:
                print(f"[youtube] Live: video {item.get('id')} — reading chat")
                return chat
        return ""

    def _recent_uploads(self) -> list[str]:
        # A channel's uploads playlist is its id with UC swapped for UU.
        if not self.channel.startswith("UC"):
            return []
        data, err = self._get("playlistItems", {
            "part": "contentDetails", "maxResults": 5,
            "playlistId": "UU" + self.channel[2:]})
        if data is None:
            self._report(err)
            return []
        return [i.get("contentDetails", {}).get("videoId")
                for i in data.get("items") or []
                if i.get("contentDetails", {}).get("videoId")]

    def _search_live(self) -> list[str]:
        now = time.time()
        if now - self._last_search < settings.YT_SEARCH_INTERVAL:
            return []
        self._last_search = now
        data, err = self._get("search", {
            "part": "id", "channelId": self.channel, "eventType": "live",
            "type": "video", "maxResults": 1})
        if data is None:
            self._report(err)
            return []
        return [i.get("id", {}).get("videoId") for i in data.get("items") or []
                if i.get("id", {}).get("videoId")]

    def find_chat(self) -> str:
        """The live chat id, or "" if nothing of his is live."""
        if self.video_override:
            return self._live_chat_of([self.video_override])
        chat = self._live_chat_of(self._recent_uploads())
        if not chat:
            chat = self._live_chat_of(self._search_live())
        if not chat and not self._looking_logged:
            self._looking_logged = True
            print("[youtube] Not live on YouTube yet — checking every "
                  f"{settings.YT_LOOKUP_INTERVAL:.0f}s")
        if chat:
            self._looking_logged = False
        return chat

    # -----------------------------------------------------------------
    # reading it
    # -----------------------------------------------------------------

    def poll(self) -> float:
        """One read. Returns how long to wait before the next."""
        params = {"liveChatId": self.chat_id, "part": "snippet,authorDetails",
                  "maxResults": 200}
        if self._page:
            params["pageToken"] = self._page
        data, err = self._get("liveChat/messages", params)

        if data is None:
            return self._on_error(err)

        items = data.get("items") or []
        if not self._primed:
            # Whatever was already in chat when she joined: remembered, not
            # answered.
            self._primed = True
            for item in items:
                self._seen.append(item.get("id"))
            print(f"[youtube] Joined chat — {len(items)} earlier message(s) "
                  f"skipped")
        else:
            for item in items:
                self._handle(item)

        self._page = data.get("nextPageToken") or self._page
        if data.get("offlineAt"):
            print("[youtube] Stream went offline — looking for the next one")
            self._reset()
            return settings.YT_LOOKUP_INTERVAL

        suggested = (data.get("pollingIntervalMillis") or 0) / 1000.0
        return max(suggested, settings.YT_MIN_POLL)

    def _handle(self, item: dict) -> None:
        msg_id = item.get("id")
        if msg_id in self._seen:
            return
        self._seen.append(msg_id)

        snippet = item.get("snippet") or {}
        kind = snippet.get("type")
        if kind == "chatEndedEvent":
            print("[youtube] Chat ended — looking for the next stream")
            self._reset()
            return
        if kind != "textMessageEvent":
            # Super Chats and memberships are alerts, not chat lines. They
            # used to be dropped here, so nobody paying on YouTube was thanked.
            from sources.youtube_alerts import from_api_item
            event = from_api_item(item)
            if event is not None and self.alerts is not None:
                self.alerts.push_external(event)
            return

        text = ((snippet.get("textMessageDetails") or {}).get("messageText")
                or snippet.get("displayMessage") or "").strip()
        author = item.get("authorDetails") or {}
        name = (author.get("displayName") or "").lstrip("@").strip()
        if not text or not name:
            return

        channel = author.get("channelId") or snippet.get("authorChannelId")
        self.room.post("youtube", name, text,
                       user_key=f"youtube:{channel}" if channel else "",
                       is_owner=author.get("isChatOwner") is True)

    def _on_error(self, reason: str) -> float:
        self._report(reason)
        if reason in CHAT_GONE:
            self._reset()
            return settings.YT_LOOKUP_INTERVAL
        if reason in QUOTA:
            return QUOTA_BACKOFF
        if reason in BAD_KEY or reason in NOT_ALLOWED:
            self._running = False
            return 0.0
        return settings.YT_MIN_POLL

    def _report(self, reason: str) -> None:
        if reason in QUOTA:
            print(f"[youtube] Out of API quota ({reason}) — chat paused, "
                  f"retrying in {QUOTA_BACKOFF / 60:.0f} min. Raise "
                  f"YT_MIN_POLL to make the daily quota last longer.")
        elif reason in NOT_ALLOWED:
            print(f"[youtube] YouTube refused to let this key read live chat "
                  f"({reason}). Reading chat may need a signed-in (OAuth) "
                  f"client instead of a plain key. YouTube chat is off until "
                  f"restart.")
        elif reason in BAD_KEY:
            print(f"[youtube] The API key was rejected ({reason}) — check "
                  f"RAVYN_YT_API_KEY, and that YouTube Data API v3 is "
                  f"enabled for it. YouTube chat is off until restart.")
        elif reason:
            print(f"[youtube] API error: {reason}")

    def _reset(self) -> None:
        self.chat_id = ""
        self._page = None
        self._primed = False

    # -----------------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        if not self.key:
            print("[youtube] Disabled — set RAVYN_YT_API_KEY to read "
                  "YouTube chat.")
            return
        if not self.channel and not self.video_override:
            print("[youtube] Disabled — set RAVYN_YT_CHANNEL_ID (starts with "
                  "UC) so she can find your live stream.")
            return

        self.room.start()
        print("[youtube] Listening for a live stream")
        while self._running:
            if not self.chat_id:
                self.chat_id = self.find_chat()
                if not self.chat_id:
                    time.sleep(settings.YT_LOOKUP_INTERVAL)
                    continue
            wait = self.poll()
            if self._running:
                time.sleep(wait)

    def stop(self) -> None:
        self._running = False
