"""
Session log — what she actually said, in full, with what produced it.

The terminal is not a record. It truncates her lines at fifty characters,
interleaves them with VAD chatter and scrolls away, so the one question that
matters after a stream — *did she repeat herself, and which knob made her* —
cannot be answered from it. Three near-identical roasts look like three
different lines when you only ever see their first eight words.

So every signal that reaches dispatch is written here as one JSON line: the
trigger, the angle and tone that framed it, her full reply, the sentences that
were actually synthesised, and whether any of it was heard. `tools/analyze_session.py`
reads the file back and measures the repetition.

One record per dispatched signal, written once its fate is known. Exactly one
signal is in flight at a time (the dispatcher's busy flag guarantees it), so
the request side and the response side need no correlation id — the pending
record *is* the correlation.

Nothing in here is allowed to raise. A logging bug must never be the reason
she goes quiet mid-stream, so every public method swallows its own errors and
the worst case is a missing line in a file nobody is reading yet.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path


# Context keys worth keeping on every record. These are the knobs: if a line
# came out stale, the answer is almost always one of these repeating.
CONTEXT_KEYS = (
    "event_type", "config_key", "angle_id", "tone", "theme_id",
    "teammate_rank", "user", "is_owner", "trigger", "death_count",
)

# The full context carries the situation block, the angle instruction and the
# tone instruction verbatim — a few KB per event. Useful when you are asking
# "what exactly did she see", noise when you are counting repeats, so it is
# opt-in via SESSION_LOG_FULL_CONTEXT.
VERBOSE_KEYS = ("situation", "angle", "tone_instruction", "player_notes",
                "teammate_words", "theme_opening")


class SessionLog:
    """
    One file per run. Append-only JSONL, flushed per record — a session that
    ends in a crash or a Ctrl-C is exactly the one worth reading.
    """

    def __init__(self, directory: Path | str, enabled: bool = True,
                 full_context: bool = False):
        self.enabled = enabled
        self.full_context = full_context
        self.path: Path | None = None
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._seq = 0
        self._started = time.time()

        if not enabled:
            return

        try:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._started))
            self.path = directory / f"session-{stamp}.jsonl"
            self._write({
                "kind": "session_start",
                "t": self._started,
                "iso": _iso(self._started),
            })
            print(f"[session] Recording this session to {self.path}")
        except Exception as e:
            self.enabled = False
            print(f"[session] Disabled — could not open log: {e}")

    # -----------------------------------------------------------------
    # request side (dispatcher thread)
    # -----------------------------------------------------------------

    def dispatched(self, signal) -> None:
        """
        A signal just went to the notebook. Opens a record; it is written when
        the response listener reports what became of it.
        """
        if not self.enabled:
            return
        try:
            with self._lock:
                # A pending record still open means the previous request never
                # came back — the watchdog case. Write it as lost rather than
                # dropping it: a stalled notebook is exactly the sort of thing
                # you want to find in the log afterwards.
                if self._pending is not None:
                    self._flush_locked(self._pending, "lost")

                self._seq += 1
                ctx = getattr(signal, "context", None) or {}

                record = {
                    "kind": "line",
                    "seq": self._seq,
                    "t": time.time(),
                    "iso": _iso(),
                    "elapsed": round(time.time() - self._started, 1),
                    "source": getattr(signal, "source", ""),
                    "priority": getattr(signal, "priority", None),
                    "mode": getattr(signal, "mode", ""),
                    "lang": getattr(signal, "lang", None),
                    "trigger_text": getattr(signal, "text", ""),
                }

                for key in CONTEXT_KEYS:
                    if key in ctx and ctx[key] not in (None, ""):
                        record[key] = ctx[key]

                if self.full_context:
                    record["context"] = {k: ctx[k] for k in VERBOSE_KEYS if k in ctx}

                self._pending = record
        except Exception as e:
            print(f"[session] dispatched() failed: {e}")

    # -----------------------------------------------------------------
    # response side (response-listener thread)
    # -----------------------------------------------------------------

    def responded(self, text: str, mood=None, tired=None, lang=None,
                  event_type: str = "") -> None:
        """Her line came back from the notebook — raw, before TTS cleaning."""
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._pending is None:
                    # Something answered that we never recorded going out —
                    # a replayed message, or a restart mid-flight. Keep it;
                    # an orphan line in the transcript beats a silent hole.
                    self._seq += 1
                    self._pending = {
                        "kind": "line", "seq": self._seq, "t": time.time(),
                        "iso": _iso(), "source": "?", "orphan": True,
                        "elapsed": round(time.time() - self._started, 1),
                    }

                self._pending["said"] = text
                self._pending["reply_latency"] = round(
                    time.time() - self._pending["t"], 2)
                if mood is not None:
                    self._pending["mood"] = mood
                if tired is not None:
                    self._pending["tired"] = tired
                if lang:
                    self._pending["reply_lang"] = lang
                if event_type:
                    self._pending.setdefault("event_type", event_type)
        except Exception as e:
            print(f"[session] responded() failed: {e}")

    def spoke_sentence(self, sentence: str, gen_s: float = 0.0,
                       audio_s: float = 0.0) -> None:
        """One synthesised chunk actually went out to Godot."""
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._pending is None:
                    return
                self._pending.setdefault("sentences", []).append({
                    "text": sentence,
                    "gen_s": round(gen_s, 2),
                    "audio_s": round(audio_s, 2),
                })
        except Exception as e:
            print(f"[session] spoke_sentence() failed: {e}")

    def finished(self, outcome: str, note: str = "") -> None:
        """
        Close the record.

        outcome is one of:
            spoken       — audio went to Godot
            silent       — --no-tts, her line exists but was never synthesised
            dropped_gate — synthesised, then dropped because he was still talking
            empty        — the notebook returned nothing to say
            tts_failed   — nothing could be synthesised
            lost         — no response ever came back (written by the next dispatch)
        """
        if not self.enabled:
            return
        try:
            with self._lock:
                if self._pending is None:
                    return
                self._flush_locked(self._pending, outcome, note)
                self._pending = None
        except Exception as e:
            print(f"[session] finished() failed: {e}")

    # -----------------------------------------------------------------

    def _flush_locked(self, record: dict, outcome: str, note: str = "") -> None:
        record["outcome"] = outcome
        if note:
            record["note"] = note

        sentences = record.get("sentences") or []
        if sentences:
            record["audio_s"] = round(sum(s["audio_s"] for s in sentences), 2)
            record["spoken_text"] = " ".join(s["text"] for s in sentences)

        self._write(record)

    def _write(self, record: dict) -> None:
        if not self.path:
            return
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[session] write failed: {e}")


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t or time.time()))


# ---------------------------------------------------------------------
# module singleton — the call sites are three different threads in two
# packages, and threading a log object through all of them buys nothing.
# ---------------------------------------------------------------------

_LOG: SessionLog | None = None


def init(directory: Path | str, enabled: bool = True,
         full_context: bool = False) -> SessionLog:
    global _LOG
    _LOG = SessionLog(directory, enabled=enabled, full_context=full_context)
    return _LOG


def get() -> SessionLog:
    """Never None: an uninitialised log is a disabled one, not a crash."""
    global _LOG
    if _LOG is None:
        _LOG = SessionLog("", enabled=False)
    return _LOG
