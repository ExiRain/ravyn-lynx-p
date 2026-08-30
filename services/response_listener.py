"""
Response listener — consumes LLM responses from ravyn.response, runs TTS
sentence by sentence, and streams audio to Godot via the local WebSocket.

This is where Ravyn's busy state is cleared. The dispatcher marks her busy
when it publishes a request; she is only idle again once the last of her
audio has actually finished playing, which is here.

Runs in its own thread, bridging pika (sync) to the audio server's
async event loop.
"""

from __future__ import annotations

import json
import re
import time
import traceback
import asyncio
from typing import Callable

import pika

from app.settings import get_settings
from services.tts_engine import TTSEngine
from services import audio_server


settings = get_settings()

# Ravyn's system prompt caps her at 2-3 sentences. Anything beyond that is
# the model ignoring instructions, and speaking it just makes her ramble.
MAX_SENTENCES = 3

# Fragments shorter than this get glued onto the previous chunk. Cloning TTS
# renders one- and two-word stubs badly, so this protects voice quality — but
# it costs streaming: Ravyn's short punchy style ("Hah. That's rough. Try
# again.") merges into a single chunk, so she only starts speaking once the
# whole line is synthesised. Lower it to stream those, at the cost of
# artefacts on the stubs. Tune by ear.
MIN_WORDS_PER_CHUNK = 4

# Time-to-first-audio is just "how long is the first chunk" — she cannot start
# speaking until chunk 1 is synthesised. So break the opening on its own
# punctuation to get her talking sooner, and leave later chunks long (they
# generate while she is already speaking, so their length costs nothing).
#
# Only existing punctuation is used as a break point; splitting mid-clause to
# hit a word count makes the prosody obviously wrong.
FIRST_CHUNK_MAX_WORDS = 8   # above this, try to break the opening
FIRST_CHUNK_MIN_WORDS = 3   # below this, TTS renders stubs badly

_CLAUSE_BREAK = re.compile(r'(?<=[,;:—–])\s*')


def _clean_for_tts(text: str) -> str:
    text = re.sub(r'[\[\(][^\]\)]{1,20}[\]\)]', '', text)
    text = re.sub(r'\*[^*]{1,30}\*', '', text)
    text = re.sub(r'  +', ' ', text).strip()
    return text


def split_sentences(text: str) -> list[str]:
    """
    Split into speakable chunks. Long sentences break on commas; fragments
    shorter than 4 words get glued onto the previous chunk so TTS never
    receives a stub like "Right." on its own.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    result: list[str] = []

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s.split()) > 20:
            for part in re.split(r'(?<=,)\s+', s):
                if result and len(part.split()) < MIN_WORDS_PER_CHUNK:
                    result[-1] += " " + part
                else:
                    result.append(part)
        elif result and len(s.split()) < MIN_WORDS_PER_CHUNK:
            result[-1] += " " + s
        else:
            result.append(s)

    return _split_first_chunk(result[:MAX_SENTENCES])


def _split_first_chunk(chunks: list[str]) -> list[str]:
    """Break a long opening chunk on clause punctuation so she starts sooner."""
    if not chunks:
        return chunks

    first = chunks[0]
    if len(first.split()) <= FIRST_CHUNK_MAX_WORDS:
        return chunks

    parts = [p for p in _CLAUSE_BREAK.split(first) if p and p.strip()]
    if len(parts) < 2:
        return chunks  # nothing to break on; a long opening it is

    # Smallest prefix that is still long enough to synthesise cleanly.
    head_parts: list[str] = []
    taken = 0
    for i, part in enumerate(parts):
        head_parts.append(part)
        taken = i + 1
        if len(" ".join(head_parts).split()) >= FIRST_CHUNK_MIN_WORDS:
            break

    head = " ".join(head_parts).strip()
    rest = " ".join(parts[taken:]).strip()

    if not head or not rest:
        return chunks

    return [head, rest] + chunks[1:]


def start_response_listener(
    tts: TTSEngine | None,
    on_complete: Callable[[], None] | None = None,
):
    """
    Blocking consumer — run in a daemon thread.

    tts=None is silent mode (--no-tts): responses are logged and busy is
    still cleared, so the orchestrator keeps cycling without audio.

    on_complete fires exactly once per message, whatever happens, including
    empty responses and TTS failures. Skipping it would leave the dispatcher
    busy until its watchdog trips.
    """

    credentials = pika.PlainCredentials(settings.RABBIT_USER, settings.RABBIT_PASS)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.RABBIT_HOST,
            port=settings.RABBIT_PORT,
            credentials=credentials,
            heartbeat=600,
        )
    )

    channel = connection.channel()
    channel.queue_declare(queue=settings.QUEUE_RESPONSE)

    mode = "TTS" if tts else "silent"
    print(f"[response] Listening on {settings.QUEUE_RESPONSE} ({mode} mode)")

    def callback(ch, method, properties, body):
        ts = time.strftime("%H:%M:%S")

        try:
            _handle(ch, method, body, ts)
        except Exception:
            # Never let this escape: pika kills the consumer thread on an
            # exception out of the callback, which would leave Ravyn mute
            # for the rest of the stream over one bad response.
            print(f"[{ts}][response] Handler error:")
            traceback.print_exc()
        finally:
            # busy must clear even if handling blew up
            if on_complete:
                on_complete()

    def _handle(ch, method, body, ts):
        raw = body.decode()

        try:
            msg = json.loads(raw)
            text = msg.get("text", "")
            mood = msg.get("mood") or 0.0
            tired = msg.get("tired") or 0.0
            event_type = msg.get("event_type", "")
            lang = msg.get("lang") or "en"
        except json.JSONDecodeError:
            text, mood, tired, event_type, lang = raw, 0.0, 0.0, "", "en"

        ch.basic_ack(delivery_tag=method.delivery_tag)

        text = _clean_for_tts(text)
        if not text:
            print(f"[{ts}][response] Empty response — nothing to say")
            return

        if tts is None:
            print(f"[{ts}][response] (silent) {text}")
            return

        # face prep for subs/follows — lands before the audio does
        if event_type in ("sub", "follow"):
            _run_async(audio_server.send_face("SURPRISED"), timeout=2)

        sentences = split_sentences(text)
        print(f"[{ts}][response] Speaking {len(sentences)} sentence(s), "
              f"mood={mood} tired={tired} lang={lang}")

        _speak(sentences, float(mood), float(tired), lang)

    def _speak(sentences: list[str], mood: float, tired: float, lang: str):
        had_clients = audio_server.has_clients()
        if not had_clients:
            print("[response] WARNING: no Godot client connected")

        _run_async(audio_server.begin_utterance(mood, tired), timeout=5)

        first_audio_at = None
        total_duration = 0.0
        is_first = True

        for idx, sentence in enumerate(sentences, 1):
            t0 = time.time()

            try:
                wav_bytes = tts.generate(sentence, mood=mood,
                                         tired=tired, lang=lang)
            except Exception as e:
                # One failed sentence shouldn't cost the whole line
                print(f"[response]   [{idx}/{len(sentences)}] TTS failed: {e}")
                continue

            if not wav_bytes:
                print(f"[response]   [{idx}/{len(sentences)}] TTS returned nothing")
                continue

            duration = _run_async(
                audio_server.push_sentence(
                    wav_bytes,
                    text=sentence,
                    is_first=is_first,
                    sample_rate=tts.sr,
                ),
                timeout=15,
            ) or 0.0

            if first_audio_at is None:
                first_audio_at = time.time()

            total_duration += duration
            is_first = False

            print(f"[response]   [{idx}/{len(sentences)}] "
                  f"gen {time.time() - t0:.2f}s, audio {duration:.2f}s: "
                  f"{sentence[:50]}")

        _run_async(audio_server.end_utterance(), timeout=5)

        # Hold busy until Godot has actually finished playing. Measured from
        # when the first audio went out, not from now — Godot has been playing
        # sentence 1 while the later ones were still generating, so sleeping
        # the full total here would leave dead air between utterances.
        if had_clients and first_audio_at is not None:
            remaining = (first_audio_at + total_duration) - time.time()
            if remaining > 0:
                print(f"[response] Waiting {remaining:.1f}s for playback")
                time.sleep(remaining)

    channel.basic_consume(
        queue=settings.QUEUE_RESPONSE,
        on_message_callback=callback,
    )

    channel.start_consuming()


def _run_async(coro, timeout: float):
    """Bridge a coroutine onto the audio server's event loop and wait for it."""
    loop = audio_server.event_loop

    if loop is None:
        print("[response] WARNING: audio server event loop not ready")
        coro.close()
        return None

    future = asyncio.run_coroutine_threadsafe(coro, loop)

    try:
        return future.result(timeout=timeout)
    except Exception as e:
        print(f"[response] Stream error: {e}")
        return None
