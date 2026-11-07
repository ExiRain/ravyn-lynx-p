"""
YouTube's paid moments — Super Chats, Super Stickers, new members, member
milestones and gifted memberships — as alert events.

Both YouTube readers used to skip every one of them ("not chat lines"), so a
viewer who paid on YouTube was never thanked. They are turned into the same
event dicts `sources/stream_elements.py` builds, and handed to its
`push_external`: the same sanitiser, the same quote-only path (nothing a
viewer wrote ever reaches the model), the same templates and priorities.

Two shapes, one per reader: the web chat's renderers and the Data API's
snippets.
"""

from __future__ import annotations

import re

from sources.youtube_web_chat import message_text


_NUMBER = re.compile(r"\d[\d\s.,]*")


def parse_amount(text: str) -> tuple[float, str]:
    """"$5.00" -> (5.0, "$"); "RUB 100.00" -> (100.0, "RUB"); "1.000,50 €"."""
    text = (text or "").strip()
    match = _NUMBER.search(text)
    if not match:
        return 0.0, text or "$"
    raw = match.group(0).strip().replace(" ", "").replace(" ", "")
    # The last separator followed by exactly two digits is the decimal one.
    if re.search(r"[.,]\d{2}$", raw):
        whole, cents = raw[:-3], raw[-2:]
        raw = re.sub(r"[.,]", "", whole) + "." + cents
    else:
        raw = re.sub(r"[.,]", "", raw)
    try:
        amount = float(raw)
    except ValueError:
        amount = 0.0
    currency = (text[:match.start()] + text[match.end():]).strip() or "$"
    return amount, currency


def _simple(obj) -> str:
    obj = obj or {}
    return obj.get("simpleText") or message_text(obj.get("runs"))


def _count(text: str) -> int:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 1


def _event(kind, msg_id, user, channel, amount=0.0, currency="$",
           message="", sender=""):
    return {"id": f"youtube:{msg_id}", "type": kind, "user": user,
            "amount": amount, "currency": currency, "message": message,
            "tier": "", "gifted": False, "sender": sender,
            "user_key": f"youtube:{channel}" if channel else "",
            "platform": "youtube"}


def from_web_item(item: dict) -> dict | None:
    """One addChatItemAction item from the web chat, or None."""
    for key in ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer"):
        r = item.get(key)
        if r:
            amount, currency = parse_amount(_simple(r.get("purchaseAmountText")))
            return _event("tip", r.get("id"),
                          _simple(r.get("authorName")).lstrip("@"),
                          r.get("authorExternalChannelId"), amount, currency,
                          message_text((r.get("message") or {}).get("runs")))

    r = item.get("liveChatMembershipItemRenderer")
    if r:
        # A milestone has its own comment; a new member has none.
        return _event("member", r.get("id"),
                      _simple(r.get("authorName")).lstrip("@"),
                      r.get("authorExternalChannelId"),
                      message=message_text((r.get("message") or {}).get("runs")))

    r = item.get("liveChatSponsorshipsGiftPurchaseAnnouncementRenderer")
    if r:
        header = ((r.get("header") or {})
                  .get("liveChatSponsorshipsHeaderRenderer") or {})
        gifter = _simple(header.get("authorName")).lstrip("@")
        return _event("gift", r.get("id"), gifter,
                      r.get("authorExternalChannelId"),
                      amount=_count(_simple(header.get("primaryText"))))
    return None


def from_api_item(item: dict) -> dict | None:
    """One liveChatMessages item from the Data API, or None."""
    snippet = item.get("snippet") or {}
    kind = snippet.get("type")
    author = item.get("authorDetails") or {}
    name = (author.get("displayName") or "").lstrip("@").strip()
    channel = author.get("channelId") or snippet.get("authorChannelId")
    msg_id = item.get("id")

    if kind in ("superChatEvent", "superStickerEvent"):
        details = (snippet.get("superChatDetails")
                   or snippet.get("superStickerDetails") or {})
        amount = (details.get("amountMicros") or 0)
        try:
            amount = int(amount) / 1_000_000
        except (TypeError, ValueError):
            amount = 0.0
        return _event("tip", msg_id, name, channel, amount,
                      details.get("currency") or "$",
                      details.get("userComment") or "")
    if kind in ("newSponsorEvent", "memberMilestoneChatEvent"):
        comment = ((snippet.get("memberMilestoneChatDetails") or {})
                   .get("userComment") or "")
        return _event("member", msg_id, name, channel, message=comment)
    if kind == "membershipGiftingEvent":
        count = ((snippet.get("membershipGiftingDetails") or {})
                 .get("giftMembershipsCount") or 1)
        return _event("gift", msg_id, name, channel, amount=int(count))
    return None
