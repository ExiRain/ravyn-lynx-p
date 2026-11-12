"""
What the avatar DID, written on the PC.

Nobody can watch her for a whole stream. Godot sends one small record per
action — a blink, a look, an ear perk, an expression, the start and end of a
line — down the WebSocket it already has open (ravyn-godot/scripts/
action_log.gd), as `LOG:<json array>`, and this files them:

    logs/
      pc/      session-<date>-<time>.jsonl   what she said
      nb/      worker-<date>-<time>.jsonl    what the model was asked
      godot/   godot-<date>-<time>.jsonl     what her face and body did

One file per PC run, named when the PC starts, so the three logs of one
stream sit side by side. Count them with tools/godot_stats.py.

Each record keeps Godot's own clock (`t`) and gets the PC's (`pc_t`): Godot
holds records while the socket is down and sends them late, so the two can
differ, and `t` is when it happened.

Never raises into the audio server: a broken log is a missing line, not a
silent streamer.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# One LOG: message is a batch of at most a hundred records (action_log.gd),
# a few KB. Anything far past that is not Godot.
MAX_MESSAGE_CHARS = 200_000
MAX_KIND_CHARS = 40


class GodotLog:

    def __init__(self, directory: Path | str, enabled: bool = True):
        self.enabled = enabled
        self.directory = Path(directory)
        self.path = self.directory / time.strftime("godot-%Y%m%d-%H%M%S.jsonl")
        self.records = 0
        self._lock = threading.Lock()
        self._announced = False

    def write(self, payload: str) -> int:
        """One LOG: message, without the prefix. How many records were filed."""
        if not self.enabled:
            return 0
        try:
            if len(payload) > MAX_MESSAGE_CHARS:
                print("[godot-log] Refused an oversized message")
                return 0
            batch = json.loads(payload)
            if isinstance(batch, dict):
                batch = [batch]
            if not isinstance(batch, list):
                return 0
            now = time.time()
            lines = []
            for record in batch:
                kind = record.get("kind") if isinstance(record, dict) else None
                if not isinstance(kind, str) or not kind \
                        or len(kind) > MAX_KIND_CHARS:
                    continue
                t = record.get("t")
                if not isinstance(t, (int, float)) or isinstance(t, bool):
                    t = record["t"] = now
                record["iso"] = time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(t))
                record["pc_t"] = round(now, 3)
                lines.append(json.dumps(record, ensure_ascii=False))
            if not lines:
                return 0
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                self.records += len(lines)
                if not self._announced:
                    self._announced = True
                    print(f"[godot-log] Avatar log -> {self.path}")
            return len(lines)
        except Exception as e:
            print(f"[godot-log] Could not write an avatar record: {e}")
            return 0


_LOG: GodotLog | None = None


def init(directory: Path | str, enabled: bool = True) -> GodotLog:
    global _LOG
    _LOG = GodotLog(directory, enabled=enabled)
    return _LOG


def write(payload: str) -> int:
    """Safe before init(): the audio server may see Godot first."""
    return _LOG.write(payload) if _LOG is not None else 0
