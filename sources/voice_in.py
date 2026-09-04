"""
Hearing him — Whisper on the CPU, fed by the voice gate.

STATUS.md §8 wanted "wake word + STT so she can hear you (the gate is the
prerequisite, and it exists)". This is that, minus the wake word, and the
omission is deliberate: openWakeWord exists to stop Whisper running
continuously, and the gate already does that job. It knows when a sentence
starts and ends, so Whisper fires once per utterance — a few times a minute,
not continuously — which is what the wake word was for.

No second microphone stream either. The gate hands over the audio it already
captured (`VoiceGate(on_utterance=...)`). Two streams would disagree about
whether he is talking, and the one that mattered would be the one without the
mute logic — so she would transcribe her own voice coming back through the
speakers and answer herself.

CPU, int8, per §1: zero VRAM, which is the whole reason it can run beside a
5080 already holding the TTS.

Everything here degrades to silence. A missing dependency, a model that will
not load, an empty transcript — each logs once and leaves the gate doing its
original job. She simply does not hear you.
"""

from __future__ import annotations

import queue
import threading
import time

from app.settings import get_settings
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue


settings = get_settings()

# Transcription happens off the audio thread. One slot: if he is still talking
# while the last sentence is being transcribed, the newer one wins — an
# utterance that has been waiting is already stale by the time she could answer.
QUEUE_DEPTH = 1

# Whisper hallucinates confidently on silence, and it hallucinates the same
# handful of things. These are the ones that come back from an empty or noisy
# segment; treating them as speech would have her answering the room tone.
_HALLUCINATION_SOURCE = (
    "you", "thank you", "thanks for watching", "thank you for watching",
    "bye", "subtitles by the amara.org community",
    "продолжение следует", "спасибо за просмотр", "субтитры",
)


def _normalise(text: str) -> str:
    return (text or "").strip().strip(".,!?…-–— ").lower()


# Stored already normalised, because the comparison normalises too — keeping
# the punctuation here meant "Продолжение следует..." never matched its own
# entry once the trailing dots were stripped off the incoming text.
HALLUCINATIONS = {_normalise(h) for h in _HALLUCINATION_SOURCE}


def looks_like_speech(text: str) -> bool:
    """Reject Whisper's silence-hallucinations and single stray tokens."""
    cleaned = _normalise(text)
    if len(cleaned) < settings.VOICE_MIN_CHARS:
        return False
    if cleaned in HALLUCINATIONS:
        return False
    # A real sentence has more than one word. "You" and "Bye" are the two
    # Whisper reaches for most often on silence.
    return len(cleaned.split()) >= 2


class VoiceInput:
    """
    Turns captured speech into `voice` signals.

    Wire it by handing `submit` to the gate as its `on_utterance` callback;
    `run` then transcribes on its own thread.
    """

    def __init__(self, queue_: SignalQueue, identity=None):
        self.queue = queue_
        self.identity = identity
        self.available = False
        self._audio: queue.Queue = queue.Queue(maxsize=QUEUE_DEPTH)
        self._running = True
        self._model = None

    # ---------------------------------------------------------
    # from the audio thread
    # ---------------------------------------------------------

    def submit(self, samples) -> None:
        """Called by the voice gate. Must not block the audio callback."""
        if not self.available:
            return
        try:
            self._audio.put_nowait(samples)
        except queue.Full:
            # Drop the older one and take the newer: he has said something
            # since, and answering the previous sentence would be answering
            # the wrong thing.
            try:
                self._audio.get_nowait()
                self._audio.put_nowait(samples)
            except queue.Empty:
                pass

    # ---------------------------------------------------------
    # its own thread
    # ---------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            print(f"[hear] Disabled — missing dependency: {e}")
            print("[hear] pip install faster-whisper")
            return

        try:
            self._model = WhisperModel(
                settings.VOICE_STT_MODEL,
                device="cpu",
                compute_type="int8",
            )
        except Exception as e:
            print(f"[hear] Disabled — could not load {settings.VOICE_STT_MODEL}: {e}")
            return

        self.available = True
        print(f"[hear] Listening — {settings.VOICE_STT_MODEL} on CPU (int8)")

        while self._running:
            try:
                samples = self._audio.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle(samples)
            except Exception as e:
                print(f"[hear] Transcription failed: {e}")

        self.available = False

    def _handle(self, samples) -> None:
        t0 = time.time()
        seconds = len(samples) / 16000.0

        segments, info = self._model.transcribe(
            samples,
            language=settings.VOICE_STT_LANGUAGE or None,
            beam_size=1,            # greedy: latency matters more than the
                                    # last point of accuracy on one sentence
            vad_filter=False,       # the gate already did that, and better
        )
        text = " ".join(s.text for s in segments).strip()
        detected = getattr(info, "language", "") or ""

        print(f"[hear] {seconds:.1f}s audio, {time.time() - t0:.1f}s transcribe "
              f"[{detected}]: {text[:70]}")

        if not looks_like_speech(text):
            print("[hear]   ignored — not speech")
            return

        self.queue.push(Signal(
            source="voice",
            priority=settings.OWNER_PRIORITY,
            text=text,
            mode="improv",
            skip_llm=False,
            ttl=settings.VOICE_TTL,
            # Whisper heard which language he used, which is better evidence
            # than guessing from the text afterwards.
            lang="ru" if detected == "ru" else "en",
            context={
                "trigger": "voice",
                "user": settings.VOICE_SPEAKER,
                # The microphone is his. Anyone else in the room is a guest on
                # it, and there is no speaker identification here to tell them
                # apart — see STATUS.
                "is_owner": True,
                "heard_language": detected,
            },
        ))
        print(f"[hear]   -> queued as voice ({detected or 'unknown'})")

    def stop(self) -> None:
        self._running = False
