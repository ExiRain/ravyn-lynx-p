"""
Hearing him — Whisper on the CPU, fed by the voice gate.

STATUS.md §8 wanted "wake word + STT so she can hear you (the gate is the
prerequisite, and it exists)". Both halves are here, but split in two, because
the wake word was doing two unrelated jobs:

  * Stopping Whisper running continuously — the GATE does that now. It knows
    when a sentence starts and ends, so Whisper fires once per utterance, a few
    times a minute.
  * Deciding whether she was addressed — done on the TRANSCRIPT instead, by
    `VOICE_REQUIRE_NAME`. Cheaper and far more reliable: Whisper has already
    turned the audio into words, and matching text beats matching a waveform.

The second half is not optional in practice. Without it she answers every
sentence the microphone hears, including a gank call on Discord or swearing at
the screen. The gate cannot tell those apart from a question; only the words
can.

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
from orchestrator import language
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


def addressed_to_her(text: str) -> bool:
    """Did he say her name? Substring, so "Ravyn," and "Ravyn's" both count."""
    if not settings.VOICE_REQUIRE_NAME:
        return True
    lowered = (text or "").lower()
    return any(name in lowered for name in settings.VOICE_NAMES)


def looks_like_speech(text: str, addressed: bool = False) -> bool:
    """
    Reject Whisper's silence-hallucinations and single stray tokens.

    `addressed` relaxes the two-word rule: "Ravyn?" on its own is one word and
    is unmistakably her being spoken to, whereas a bare "you" is Whisper
    hallucinating at room tone.
    """
    cleaned = _normalise(text)
    if len(cleaned) < settings.VOICE_MIN_CHARS:
        return False
    if cleaned in HALLUCINATIONS:
        return False
    if addressed:
        return True
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

    def _transcribe(self, samples, forced: str):
        """One pass. `forced` empty means let Whisper detect."""
        segments, info = self._model.transcribe(
            samples,
            language=forced or None,
            initial_prompt=settings.VOICE_STT_PROMPTS.get(forced or "en"),
            beam_size=settings.VOICE_STT_BEAM,
            vad_filter=False,       # the gate already did that, and better
            # Whisper loops when it conditions on its own previous output —
            # "Хм, хм, хм, хм, хм, хм, хм" out of 1.8s of audio, which also
            # burned eight seconds of CPU producing it. Each utterance is
            # independent here anyway, so there is nothing to condition on.
            condition_on_previous_text=False,
            # Drop segments that decoded badly rather than emitting confident
            # nonsense. A high compression ratio IS a repetition loop.
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        return " ".join(seg.text for seg in segments).strip(), info

    def _choose_language(self, info) -> str:
        """
        The best of the languages he actually speaks.

        Whisper ranks all ninety-nine, and on two seconds of audio the winner
        is routinely something he has never spoken — a live session produced
        de, pl, lv and sv from Russian. Restricting the choice to two makes a
        wrong answer recoverable instead of nonsense.
        """
        probs = getattr(info, "all_language_probs", None)
        allowed = settings.VOICE_LANGUAGES

        if probs:
            scores = dict(probs)
            return max(allowed, key=lambda lang: scores.get(lang, 0.0))

        detected = getattr(info, "language", "") or ""
        return detected if detected in allowed else allowed[0]

    def _handle(self, samples) -> None:
        t0 = time.time()
        seconds = len(samples) / 16000.0

        pinned = settings.VOICE_STT_LANGUAGE
        text, info = self._transcribe(samples, pinned)
        detected = pinned or (getattr(info, "language", "") or "")

        if not pinned:
            chosen = self._choose_language(info)
            if chosen != detected:
                # The first pass decoded as a language he does not speak, so
                # its text is not worth keeping. Redo it pinned — this is the
                # only case that costs a second pass.
                print(f"[hear]   heard as [{detected}], not a language he "
                      f"speaks — retrying as [{chosen}]")
                text, info = self._transcribe(samples, chosen)
            detected = chosen

        # Last word goes to the script itself. If the transcript is Cyrillic it
        # is Russian, whatever Whisper labelled it — this is the same detector
        # the chat path uses, and it cannot be argued with.
        if text and language.cyrillic_ratio(text) >= language.CYRILLIC_THRESHOLD:
            detected = "ru"

        print(f"[hear] {seconds:.1f}s audio, {time.time() - t0:.1f}s transcribe "
              f"[{detected}]: {text[:70]}")

        addressed = addressed_to_her(text)

        if not looks_like_speech(text, addressed):
            print("[hear]   ignored — not speech")
            return

        if not addressed:
            # Heard clearly, just not aimed at her. Logged rather than silent
            # so the transcription can be seen working while she stays quiet.
            print("[hear]   heard, but she was not addressed — staying quiet")
            return

        self.queue.push(Signal(
            source="voice",
            priority=settings.OWNER_PRIORITY,
            text=text,
            mode="improv",
            skip_llm=False,
            ttl=settings.VOICE_TTL,
            # Settled above: constrained detection, then the script of the
            # transcript itself as the tiebreaker. Anything that is not
            # Russian by then is English, because those are the only two.
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
