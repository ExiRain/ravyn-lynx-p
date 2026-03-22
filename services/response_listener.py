"""
Response listener — consumes LLM responses from ravyn.response queue,
runs Chatterbox TTS, and streams audio to Godot via local WebSocket.

Runs in its own thread, bridges between pika (sync) and
the async audio server event loop.
"""

from __future__ import annotations

import json
import re
import time
import asyncio
import pika

from app.settings import get_settings
from services.tts_engine import TTSEngine
from services import audio_server


settings = get_settings()

# TTS cleanup — same as notebook
def _clean_for_tts(text: str) -> str:
    text = re.sub(r'[\[\(][^\]\)]{1,20}[\]\)]', '', text)
    text = re.sub(r'\*[^*]{1,30}\*', '', text)
    text = re.sub(r'  +', ' ', text).strip()
    return text


def start_response_listener(tts: TTSEngine):
    """Blocking consumer — run in a daemon thread."""

    credentials = pika.PlainCredentials(settings.RABBIT_USER, settings.RABBIT_PASS)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.RABBIT_HOST,
            port=settings.RABBIT_PORT,
            credentials=credentials,
        )
    )

    channel = connection.channel()
    channel.queue_declare(queue=settings.QUEUE_RESPONSE)

    print("[response] Listening on", settings.QUEUE_RESPONSE)

    def callback(ch, method, properties, body):
        ts = time.strftime("%H:%M:%S")
        raw = body.decode()

        # parse JSON response from notebook
        try:
            msg = json.loads(raw)
            text = msg.get("text", "")
            mood = msg.get("mood") or 0.0
            tired = msg.get("tired") or 0.0
            source = msg.get("source", "")
            event_type = msg.get("event_type", "")
        except json.JSONDecodeError:
            # fallback for plain text (old notebook)
            text = raw
            mood = 0.0
            tired = 0.0
            source = ""
            event_type = ""

        if not text or not text.strip():
            print(f"[{ts}][response] Empty response — skipping")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        text = _clean_for_tts(text)
        if not text:
            print(f"[{ts}][response] Empty after cleanup — skipping")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        print(f"[{ts}][response] TTS: {text[:60]}  mood={mood} tired={tired}")

        # face prep for subs/follows
        if event_type in ("sub", "follow"):
            _send_face_async("SURPRISED")

        # generate audio
        wav_bytes = tts.generate(text, mood=float(mood), tired=float(tired))

        if not wav_bytes:
            print(f"[{ts}][response] TTS returned empty audio")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        # stream to Godot via async audio server
        _stream_audio_async(wav_bytes, float(mood), float(tired))

        print(f"[{ts}][response] Audio streamed to Godot")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(
        queue=settings.QUEUE_RESPONSE,
        on_message_callback=callback,
    )

    channel.start_consuming()


def _stream_audio_async(wav_bytes: bytes, mood: float, tired: float):
    """Bridge sync pika callback to async WebSocket server."""
    loop = audio_server.event_loop
    if loop is None:
        print("[response] WARNING: audio server event loop not ready")
        return

    future = asyncio.run_coroutine_threadsafe(
        audio_server.stream_audio_to_godot(wav_bytes, mood, tired),
        loop,
    )

    try:
        future.result(timeout=15)
    except Exception as e:
        print(f"[response] Stream error: {e}")


def _send_face_async(face_type: str):
    """Bridge sync to async for face commands."""
    loop = audio_server.event_loop
    if loop is None:
        return

    future = asyncio.run_coroutine_threadsafe(
        audio_server.send_face(face_type),
        loop,
    )

    try:
        future.result(timeout=2)
    except Exception:
        pass