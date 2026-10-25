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
  END                → audio done (sent, not yet played)
  SHOW:0:fade_ms     → ghost mode only: fade her out again, once Godot has
                       finished PLAYING — not straight after END

Sentences are streamed as they are generated, so Godot starts playing
sentence 1 while sentence 2 is still being synthesised.

GHOST MODE (`--ghost`, for a stream where the screen is not a game): she is
invisible until she speaks. `SHOW:100:200` before START, `SHOW:0:400` once
her audio has finished playing, and Godot fades her alpha over that many
milliseconds. Nothing is sent
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
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

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

    # Ghost mode starts her hidden. Godot loads her fully visible, so without
    # this she sat on top of the game until her first line — and again after
    # any reconnect.
    if settings.GHOST_MODE:
        try:
            await ws.send_text("SHOW:0:0")
        except Exception:
            clients.discard(ws)

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
    """Close an utterance: no more audio is coming. Godot is still playing."""
    await send_text_to_godot("END")

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}][audio_server] END")


async def fade_out() -> None:
    """
    Ghost mode: fade her out. Call once Godot has finished PLAYING the
    utterance — the response listener does, after its playback wait.

    It used to go out with END, i.e. when the last chunk was SENT. TTS runs
    several times faster than real time, so a twelve-second line was sent in
    about three and she vanished for the rest of it while still talking; a
    one-sentence line faded out milliseconds after it faded in. In the
    2026-10-25 ghost session she was effectively never visible.

    Slower than the fade in: vanishing on the last syllable reads as a glitch,
    lingering for a moment reads as her having finished.
    """
    if settings.GHOST_MODE:
        await set_visibility(0, settings.GHOST_FADE_OUT_MS)


async def send_face(face_type: str):
    """Send face preparation command (e.g. FACE:SURPRISED)."""
    await send_text_to_godot(f"FACE:{face_type}")


def has_clients() -> bool:
    return len(clients) > 0


# =========================================================
# DEBUG: fire a test alert into the live pipeline
# =========================================================

# Set by app/main.py only when started with --debug-alerts, to
# StreamElementsSource._handle of the SAME instance real donations go
# through — same sanitizer, same dedup, same Signal shape. Left unset on an
# ordinary run, so the route 404s instead of silently doing nothing: a test
# endpoint that exists on every stream, reachable on 0.0.0.0, is worse than
# one that is visibly off by default.
_alert_injector = None
_promo_injector = None   # (fire, status) — see register_promo_injector
_sanitizer_ref = None    # the live Sanitizer, for /debug/sanitizer-check


def register_alert_injector(handler) -> None:
    global _alert_injector
    _alert_injector = handler


def register_sanitizer(sanitizer) -> None:
    global _sanitizer_ref
    _sanitizer_ref = sanitizer


def register_promo_injector(fire, status) -> None:
    """
    fire(pool|None) -> Signal|None   — PromoSource.fire, gates ignored
    status() -> str                  — PromoSource._blocked(now), "" if she may ask
    """
    global _promo_injector
    _promo_injector = (fire, status)


@app.post("/debug/alert")
async def debug_alert(activity: dict = Body(...)):
    """
    Fire one StreamElements-shaped activity through the real pipeline —
    parse, sanitize, compose, push onto the live queue TTS/OBS consume from.

    Same shape `_parse_activity` reads: {"type": ..., "data": {...}}. Paste
    one straight from a `[se] FIRST ... payload` log line, or use
    tools/fire_alert.py to build one from plain arguments.
    """
    if _alert_injector is None:
        return JSONResponse(
            {"error": "debug alerts are off — start app.main with "
                      "--debug-alerts to turn this on"},
            status_code=404,
        )

    signal = _alert_injector(activity)
    if signal is None:
        return {"fired": False,
                "reason": "parsed to nothing — unknown type, duplicate id, "
                          "or a field name that did not match"}
    return {"fired": True, "text": signal.text, "source": signal.source}


@app.get("/debug/sanitizer-check")
async def debug_sanitizer_check():
    """
    Proves the live blocklist actually catches something, without ever
    printing the flagged term anywhere — it never leaves this process.

    Picks one real entry from YOUR data/blocklist.json (not a hardcoded
    guess) and runs it through the same Sanitizer.clean() every donation
    goes through, once embedded in a name and once in a message. Answers
    whether each was caught — the file loading with N entries only proves
    it parsed, not that a real hit gets replaced before TTS ever sees it.
    """
    if _sanitizer_ref is None:
        return JSONResponse(
            {"error": "debug alerts are off — start app.main with "
                      "--debug-alerts to turn this on"},
            status_code=404,
        )

    import random
    bl = _sanitizer_ref.blocklist
    terms = list(bl.substrings) + list(bl.words)
    if not terms:
        return {"checked": False,
                "reason": "blocklist.json has no entries loaded — "
                          "nothing is being filtered right now"}

    term = random.choice(terms)
    name_result = _sanitizer_ref.clean(f"user_{term}_test", "")
    message_result = _sanitizer_ref.clean(
        "test_user", f"this message has {term} hidden in it")

    return {
        "checked": True,
        "name_blocked": bool(name_result.name_blocked),
        "message_blocked": bool(message_result.message_blocked),
        "entries_in_blocklist": len(terms),
    }


@app.post("/debug/promo")
async def debug_promo(body: dict = Body(default={})):
    """
    Force one promo ask through, gates ignored — PromoSource.fire(pool).

    body: {"pool": "follow" | "subscribe" | "end_wonder"}, or {} / omitted
    to let her pick the next one in her normal alternating order.
    """
    if _promo_injector is None:
        return JSONResponse(
            {"error": "debug alerts are off — start app.main with "
                      "--debug-alerts to turn this on"},
            status_code=404,
        )
    fire, _status = _promo_injector
    signal = fire(body.get("pool"))
    if signal is None:
        return {"fired": False,
                "reason": "no line configured for that pool in "
                          "data/promo.json"}
    return {"fired": True, "text": signal.text,
            "pool": signal.context.get("promo")}


@app.get("/debug/promo/status")
async def debug_promo_status():
    """Why she would not ask right now, or "" if nothing is blocking her."""
    if _promo_injector is None:
        return JSONResponse(
            {"error": "debug alerts are off — start app.main with "
                      "--debug-alerts to turn this on"},
            status_code=404,
        )
    _fire, status = _promo_injector
    reason = status()
    return {"blocked": bool(reason), "reason": reason}


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
