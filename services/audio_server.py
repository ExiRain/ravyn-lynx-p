"""
Local WebSocket audio server for Godot.

Same protocol as the notebook's original stream_api.py — Godot doesn't
know the difference. Runs on the PC alongside the game.

Protocol (one utterance):
  MOOD:float         → mood value
  TIRED:float        → tired value
  SHOW:pct:fade_ms   → ghost mode only: fade her in before she speaks
  START              → audio incoming
    first sentence only:
      RATE:int         → the sample rate the PCM is at
    per sentence:
      <binary chunks>  → WAV audio data (header on the first sentence only)
      MOUTH:float      → lip sync envelope
      PHONEME:p:t      → phoneme timeline
  END                → audio done
  SHOW:0:fade_ms     → ghost mode only: fade her out again

Sentences are streamed as they are generated, so Godot starts playing
sentence 1 while sentence 2 is still being synthesised.

GHOST MODE (`--ghost`, for a stream where the screen is not a game): she is
invisible until she speaks. `SHOW:100:200` before START, `SHOW:0:400` after
END, and Godot fades her alpha over that many milliseconds. Nothing is sent
when ghost mode is off, so a Godot build that ignores SHOW behaves exactly as
it does today.

Visibility deliberately follows the UTTERANCE rather than the amplitude:
alpha driven straight from the audio would strobe, because speech hits zero
between syllables. MOUTH already carries that detail.
"""

from __future__ import annotations

import asyncio
import time
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.settings import get_settings

# Read per call rather than copied into a local: `--ghost` is written onto the
# class in app/main.py, and a snapshot taken at import time would have been
# the default instead of the flag.
settings = get_settings()

app = FastAPI()

clients: set[WebSocket] = set()
event_loop = None

AUDIO_CHUNK_BYTES = 8192
DEFAULT_SAMPLE_RATE = 24000
WAV_HEADER_SIZE = 44

# envelope state — reset per utterance, see begin_utterance()
_running_peak = 1e-6
_previous_env = 0.0

# phonemizer is optional: it needs espeak-ng installed as a system package,
# which is awkward on Windows. Without it Godot still gets MOUTH (amplitude
# drives how far the mouth opens); it just loses PHONEME (which drives shape).
_phonemizer_backend = None
_phonemizer_tried = False


def _get_phonemizer():
    global _phonemizer_backend, _phonemizer_tried

    if _phonemizer_tried:
        return _phonemizer_backend

    _phonemizer_tried = True
    try:
        from phonemizer.backend import EspeakBackend
        _phonemizer_backend = EspeakBackend(
            "en-us", preserve_punctuation=False, with_stress=False
        )
        print("[audio_server] Phonemizer ready — PHONEME enabled")
    except Exception as e:
        print(f"[audio_server] Phonemizer unavailable ({e}) — "
              f"MOUTH only, no PHONEME. Install espeak-ng to enable mouth shapes.")
        _phonemizer_backend = None

    return _phonemizer_backend


@app.on_event("startup")
async def startup():
    global event_loop
    event_loop = asyncio.get_running_loop()
    _get_phonemizer()
    print("[audio_server] WebSocket server ready")


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


# =========================================================
# UTTERANCE STREAMING
# =========================================================

async def set_visibility(percent: int, fade_ms: int) -> None:
    """
    Ghost mode: how visible she should be, and how long to take about it.

    0 is gone, 100 is fully there. Sent only in ghost mode — see the module
    docstring for why this follows the utterance rather than the waveform.
    """
    await send_text_to_godot(f"SHOW:{int(percent)}:{int(fade_ms)}")


async def begin_utterance(mood: float = 0.0, tired: float = 0.0) -> None:
    """Open an utterance: reset lip sync state, send mood, send START."""
    global _running_peak, _previous_env

    # Reset per utterance. These decay at 0.995/chunk, so without a reset a
    # loud line leaves the peak high and the next quiet line renders with a
    # nearly motionless mouth.
    _running_peak = 1e-6
    _previous_env = 0.0

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}][audio_server] START  mood={mood} tired={tired}")

    await send_text_to_godot(f"MOOD:{mood}")
    await send_text_to_godot(f"TIRED:{tired}")

    # Before START, so the fade has run by the time the first syllable
    # arrives: appearing mid-word is worse than not fading at all.
    if settings.GHOST_MODE:
        await set_visibility(100, settings.GHOST_FADE_IN_MS)

    await send_text_to_godot("START")


async def push_sentence(
    wav_bytes: bytes,
    text: str = "",
    is_first: bool = False,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> float:
    """
    Stream one sentence of audio. Returns its playback duration in seconds.

    Only the first sentence carries its WAV header — joining chunks that each
    have one produces an audible crack at every sentence boundary.
    """
    if len(wav_bytes) < WAV_HEADER_SIZE:
        return 0.0

    payload = wav_bytes if is_first else wav_bytes[WAV_HEADER_SIZE:]
    pcm_samples = np.frombuffer(wav_bytes[WAV_HEADER_SIZE:], dtype=np.int16)

    if pcm_samples.size == 0:
        return 0.0

    duration = len(pcm_samples) / sample_rate

    # The rate the PCM is actually at, said out loud once per utterance.
    #
    # It was never sent, and Godot assumed 24000 — which is only true while
    # the TTS happens to run there. `TTSEngine.sample_rate` is read from the
    # loaded model (`self.sample_rate = int(sr)`), so a backend or checkpoint
    # at 22050 or 48000 would have played her back at the wrong pitch and
    # drifted the lip sync, with nothing in either log to say why.
    if is_first:
        await send_text_to_godot(f"RATE:{int(sample_rate)}")

    # audio
    for i in range(0, len(payload), AUDIO_CHUNK_BYTES):
        await send_bytes_to_godot(payload[i:i + AUDIO_CHUNK_BYTES])
        await asyncio.sleep(0)

    # mouth envelope
    samples_per_chunk = AUDIO_CHUNK_BYTES // 2
    for i in range(0, len(pcm_samples), samples_per_chunk):
        env = _compute_envelope(pcm_samples[i:i + samples_per_chunk])
        await send_text_to_godot(f"MOUTH:{env}")
        await asyncio.sleep(0)

    # phoneme timeline
    for phoneme, t in _get_phonemes(text, duration):
        await send_text_to_godot(f"PHONEME:{phoneme}:{t}")
        await asyncio.sleep(0)

    return duration


async def end_utterance() -> None:
    """Close an utterance."""
    await send_text_to_godot("END")

    # After END, and a slower fade than the way in: vanishing on the last
    # syllable reads as a glitch, while lingering for a moment reads as her
    # having finished.
    if settings.GHOST_MODE:
        await set_visibility(0, settings.GHOST_FADE_OUT_MS)

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}][audio_server] END")


async def send_face(face_type: str):
    """Send face preparation command (e.g. FACE:SURPRISED)."""
    await send_text_to_godot(f"FACE:{face_type}")


def has_clients() -> bool:
    return len(clients) > 0


# =========================================================
# LIP SYNC
# =========================================================

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


def _get_phonemes(text: str, audio_duration: float) -> list[tuple[str, float]]:
    """
    Word-level IPA phonemes with estimated timestamps.

    Godot splits these into individual characters and handles digraphs.
    Timing spreads the sentence duration across phonemes, weighting vowels
    1.5x since they are naturally longer.
    """
    backend = _get_phonemizer()

    if not text or backend is None or audio_duration <= 0:
        return []

    try:
        result = backend.phonemize([text], njobs=1)
        if not result:
            return []

        raw = result[0].replace("|", " ").split()
        phonemes = [p.strip() for p in raw if p.strip()]

        if not phonemes:
            return []

        VOWELS = set("aeiouæɑɐɔʊɪɛ")
        weights = [1.5 if (p and p[0] in VOWELS) else 1.0 for p in phonemes]

        total_weight = sum(weights)
        if total_weight <= 0:
            return []

        timeline = []
        t = 0.0
        for phoneme, weight in zip(phonemes, weights):
            timeline.append((phoneme, round(t, 4)))
            t += (weight / total_weight) * audio_duration

        return timeline

    except Exception as e:
        print(f"[audio_server] Phonemizer error: {e}")
        return []
