"""
Local WebSocket audio server for Godot.

Same protocol as notebook's stream_api.py — Godot doesn't know
the difference. Runs on PC alongside the game.

Protocol:
  START              → audio incoming
  <binary chunks>    → WAV audio data
  MOUTH:float        → lip sync envelope
  PHONEME:p:t        → phoneme timeline
  MOOD:float         → mood value
  TIRED:float        → tired value
  FACE:type          → face preparation (SURPRISED etc)
  END                → audio done
"""

from __future__ import annotations

import asyncio
import time
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

clients: set[WebSocket] = set()
event_loop = None

AUDIO_CHUNK_BYTES = 8192
SAMPLE_RATE = 24000
WAV_HEADER_SIZE = 44

# envelope state
_running_peak = 1e-6
_previous_env = 0.0


@app.on_event("startup")
async def startup():
    global event_loop
    event_loop = asyncio.get_running_loop()
    print("[audio_server] WebSocket server ready on port 9000")


@app.websocket("/ws/audio")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    print("[audio_server] Godot connected")

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        print("[audio_server] Godot disconnected")
    finally:
        clients.discard(ws)


async def send_text_to_godot(msg: str):
    """Send a text message to all connected Godot clients."""
    for ws in list(clients):
        try:
            await ws.send_text(msg)
        except Exception:
            clients.discard(ws)


async def send_bytes_to_godot(data: bytes):
    """Send binary data to all connected Godot clients."""
    for ws in list(clients):
        try:
            await ws.send_bytes(data)
        except Exception:
            clients.discard(ws)


async def stream_audio_to_godot(wav_bytes: bytes, mood: float = 0.0, tired: float = 0.0):
    """
    Stream WAV audio to Godot with lip sync data.
    Matches the exact protocol Godot expects.
    """
    global _running_peak, _previous_env

    if not clients:
        print("[audio_server] No Godot clients connected")
        return

    if len(wav_bytes) < WAV_HEADER_SIZE:
        print("[audio_server] Audio too short")
        return

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}][audio_server] Streaming {len(wav_bytes)} bytes to Godot")

    pcm_bytes = wav_bytes[WAV_HEADER_SIZE:]
    pcm_samples = np.frombuffer(pcm_bytes, dtype=np.int16)

    # send mood/tired first
    await send_text_to_godot(f"MOOD:{mood}")
    await send_text_to_godot(f"TIRED:{tired}")

    # START
    await send_text_to_godot("START")

    # audio chunks (full WAV with header)
    for i in range(0, len(wav_bytes), AUDIO_CHUNK_BYTES):
        await send_bytes_to_godot(wav_bytes[i:i + AUDIO_CHUNK_BYTES])
        await asyncio.sleep(0)

    # mouth envelope
    samples_per_chunk = AUDIO_CHUNK_BYTES // 2
    for i in range(0, len(pcm_samples), samples_per_chunk):
        chunk = pcm_samples[i:i + samples_per_chunk]
        env = _compute_envelope(chunk)
        await send_text_to_godot(f"MOUTH:{env}")
        await asyncio.sleep(0)

    # END
    await send_text_to_godot("END")


async def send_face(face_type: str):
    """Send face preparation command (e.g. FACE:SURPRISED)."""
    await send_text_to_godot(f"FACE:{face_type}")


def _compute_envelope(samples: np.ndarray) -> float:
    global _running_peak, _previous_env

    if samples.size == 0:
        return 0.0

    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    _running_peak = max(_running_peak * 0.995, rms)
    env = rms / _running_peak if _running_peak > 0 else 0.0
    env = max(0.0, min(env, 1.0))
    smoothed = env * 0.65 + _previous_env * 0.35
    _previous_env = smoothed
    return smoothed