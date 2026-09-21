"""
Rebuild a session from terminal scrollback.

The session log (`orchestrator/session_log.py`) only exists from the run that
created it onward, and the sessions worth studying right now are the ones that
already happened and live in a tmux buffer. This reads that scrollback back
into the same record shape, so `analyze_session.py` does not care which it got.

What it cannot give you is her full text: the console prints `sentence[:50]`,
so every reconstructed line is a prefix. Those records carry `truncated: true`
and the report says so — prefixes are still enough to find repeated openers
and repeated phrasing, which is most of what the repetition numbers measure,
but "she said X twice" from a truncated log means the first fifty characters
matched.

Use the JSONL log for anything that needs her whole sentence.
"""

from __future__ import annotations

import re
from pathlib import Path


# [20:35:19][response] Speaking 3 sentence(s), mood=0.1 tired=0.2 lang=en
RE_SPEAKING = re.compile(
    r'^(?:\[(?P<ts>\d\d:\d\d:\d\d)\])?\[response\] Speaking (?P<n>\d+) sentence',
)
RE_MOOD = re.compile(r'mood=(?P<mood>-?[\d.]+)\s+tired=(?P<tired>-?[\d.]+)'
                     r'(?:\s+lang=(?P<lang>\w+))?')

# [response]   [1/3] gen 1.21s, audio 2.56s: You're treating me like a menu...
RE_CHUNK = re.compile(
    r'\[response\]\s+\[(?P<idx>\d+)/(?P<total>\d+)\]\s+gen (?P<gen>[\d.]+)s,'
    r'\s+audio (?P<audio>[\d.]+)s:\s?(?P<text>.*)$'
)

# [dispatch] source=game  mode=improv  lang=en  skip_llm=False  text=...
RE_DISPATCH = re.compile(
    r'\[dispatch\] source=(?P<source>\S+)\s+mode=(?P<mode>\S+)\s+'
    r'lang=(?P<lang>\S+)\s+skip_llm=(?P<skip>\S+)\s+text=(?P<text>.*)$'
)

# [lol] MyDeath: I thought you wanted to win this game, no? Killed by...  [my_death_quiet]
RE_LOL_EVENT = re.compile(
    r'\[lol\] (?P<key>[A-Za-z_]+): (?P<text>.*?)(?:\s\s\[(?P<angle>[a-z0-9_]+)\])?$'
)

# [lol] Death #5 (traded 0k/0a) -> roast @ 90%
RE_DEATH = re.compile(
    r'\[lol\] Death #(?P<n>\d+) \(traded (?P<k>\d+)k/(?P<a>\d+)a\) -> '
    r'(?P<tone>\w+) @ (?P<chance>\d+)%'
)

RE_DROPPED = re.compile(r'\[response\] Dropped — .*?:\s?(?P<text>.*)$')
RE_SILENT = re.compile(r'\[response\] \(silent\)\s(?P<text>.*)$')
RE_TS = re.compile(r'^\[(?P<ts>\d\d:\d\d:\d\d)\]')

# [twitch] Picked: tracalley_25 (score=5.0) from 1 messages, window=5.0s
RE_PICKED = re.compile(r'\[twitch\] Picked: (?P<user>\S+) \(score=')

# The console truncates her sentences at this width; anything landing exactly
# on it was almost certainly cut.
CONSOLE_WIDTH = 50
TRIGGER_WIDTH = 60


def parse(text: str) -> list[dict]:
    """Console text -> records in session_log shape."""
    records: list[dict] = []
    current: dict | None = None
    pending_lol: dict | None = None
    pending_death: dict | None = None
    pending_user: str | None = None
    seq = 0
    last_ts = ""

    def close(outcome: str | None = None) -> None:
        nonlocal current
        if current is None:
            return
        if outcome:
            current["outcome"] = outcome
        elif "outcome" not in current:
            current["outcome"] = "spoken" if current.get("sentences") else "unknown"
        _finalise(current)
        records.append(current)
        current = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue

        m = RE_TS.match(line)
        if m:
            last_ts = m.group("ts")

        m = RE_DEATH.search(line)
        if m:
            pending_death = {
                "death_count": int(m.group("n")),
                "verdict_tone": m.group("tone"),
                "traded_kills": int(m.group("k")),
                "traded_assists": int(m.group("a")),
            }
            continue

        m = RE_PICKED.search(line)
        if m:
            pending_user = m.group("user")
            continue

        if "[lol] " in line and "skipped (" not in line:
            m = RE_LOL_EVENT.search(line)
            if m and m.group("key") not in ("Death", "API", "Game", "Loaded",
                                            "WARNING", "CHEER", "BOO"):
                pending_lol = {
                    "config_key": m.group("key"),
                    "seed": m.group("text").strip(),
                }
                if m.group("angle"):
                    pending_lol["angle_id"] = m.group("angle")
                continue

        m = RE_DISPATCH.search(line)
        if m:
            close()
            seq += 1
            trigger = m.group("text")
            current = {
                "kind": "line",
                "seq": seq,
                "ts": last_ts,
                "source": m.group("source"),
                "mode": m.group("mode"),
                "lang": m.group("lang"),
                "trigger_text": trigger[:-3] if trigger.endswith("...") else trigger,
                "trigger_truncated": trigger.endswith("..."),
                "from_console": True,
            }
            if current["source"] == "game" and pending_lol:
                # The queued line is printed by the game source immediately
                # before the dispatcher publishes it, and nothing else can be
                # dispatched in between — the busy flag holds the loop. So the
                # most recent one is this one.
                current.update({k: v for k, v in pending_lol.items()
                                if k != "seed"})
                if pending_death and pending_lol["config_key"].lower().startswith("mydeath"):
                    current.update(pending_death)
                pending_lol = None
            elif current["source"] in ("chat", "twitch") and pending_user:
                current["user"] = pending_user
                pending_user = None
            continue

        if RE_SPEAKING.search(line):
            if current is None:      # scrollback started mid-utterance
                seq += 1
                current = {"kind": "line", "seq": seq, "ts": last_ts,
                           "source": "?", "orphan": True, "from_console": True}
            mm = RE_MOOD.search(line)
            if mm:
                current["mood"] = float(mm.group("mood"))
                current["tired"] = float(mm.group("tired"))
                if mm.group("lang"):
                    current["reply_lang"] = mm.group("lang")
            current["ts"] = last_ts or current.get("ts", "")
            continue

        m = RE_CHUNK.search(line)
        if m and current is not None:
            sentence = m.group("text")
            current.setdefault("sentences", []).append({
                "text": sentence,
                "gen_s": float(m.group("gen")),
                "audio_s": float(m.group("audio")),
                "truncated": len(sentence) >= CONSOLE_WIDTH,
            })
            continue

        m = RE_DROPPED.search(line)
        if m and current is not None:
            sentence = m.group("text")
            current.setdefault("sentences", []).append({
                "text": sentence, "gen_s": 0.0, "audio_s": 0.0,
                "truncated": len(sentence) >= CONSOLE_WIDTH,
            })
            close("dropped_gate")
            continue

        m = RE_SILENT.search(line)
        if m and current is not None:
            current["said"] = m.group("text")
            close("silent")
            continue

        if "Empty response" in line and current is not None:
            close("empty")
        elif "Nothing synthesised" in line and current is not None:
            close("tts_failed")

    close()
    return records


def _finalise(record: dict) -> None:
    sentences = record.get("sentences") or []
    if not sentences:
        return
    record["spoken_text"] = " ".join(s["text"] for s in sentences)
    record["audio_s"] = round(sum(s["audio_s"] for s in sentences), 2)
    record["truncated"] = any(s.get("truncated") for s in sentences)
    # The console never shows the notebook's raw reply, only what was spoken.
    record.setdefault("said", record["spoken_text"])


def parse_file(path: str | Path) -> list[dict]:
    return parse(Path(path).read_text(encoding="utf-8", errors="replace"))
