"""
Hearing him.

    python tests/test_voice_in.py

Two design decisions this protects.

**No second microphone stream.** The voice gate hands over the audio it already
captured. Opening another stream would give two components separate opinions
about whether he is talking, and the second one would not have the mute logic —
so she would transcribe her own voice coming back through the speakers and
answer herself.

**No wake word.** STATUS §8 planned openWakeWord to stop Whisper running
continuously. The gate already does that: it knows where a sentence starts and
ends, so Whisper fires once per utterance rather than on every frame.

Everything here degrades to silence rather than to noise.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                    # noqa: E402
from orchestrator.priority_queue import SignalQueue      # noqa: E402
from sources.voice_in import (                           # noqa: E402
    HALLUCINATIONS, VoiceInput, looks_like_speech,
)

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_hallucination_filter():
    print("\n--- Whisper hallucinates on silence ---")
    # These are what an empty or noisy segment actually returns, and they are
    # confident, well-punctuated sentences. Answering them means answering the
    # room tone.
    for junk in ("you", "You.", "Thank you", "Thanks for watching",
                 "bye", "...", "Продолжение следует...", "Субтитры"):
        check(f"{junk!r} is ignored", not looks_like_speech(junk))

    for real in ("what do you think of this matchup",
                 "ravyn are you awake",
                 "как тебе эта игра"):
        check(f"{real!r} is heard", looks_like_speech(real))

    check("a single word is not a sentence", not looks_like_speech("hello"))
    check("empty is not speech", not looks_like_speech(""))
    check("whitespace is not speech", not looks_like_speech("   "))
    check("the filter list is lowercase, as it is compared",
          all(h == h.lower() for h in HALLUCINATIONS))


def test_submit_is_safe_from_the_audio_thread():
    print("\n--- submit never blocks the audio callback ---")
    voice = VoiceInput(SignalQueue())

    # Before the model loads, audio is simply dropped.
    voice.submit([0.0] * 16000)
    check("nothing is queued while unavailable", voice._audio.qsize() == 0)

    voice.available = True
    voice.submit("first")
    check("one utterance is held", voice._audio.qsize() == 1)

    # He kept talking while the last sentence was still transcribing. The newer
    # one wins: answering the previous sentence answers the wrong thing.
    voice.submit("second")
    check("the queue stays shallow", voice._audio.qsize() == 1,
          str(voice._audio.qsize()))
    check("and holds the NEWER utterance",
          voice._audio.get_nowait() == "second")


def test_signal_shape():
    print("\n--- what reaches the queue ---")
    queue = SignalQueue()
    voice = VoiceInput(queue)
    voice.available = True

    class FakeSegment:
        def __init__(self, text): self.text = text

    class FakeModel:
        def __init__(self, text, lang):
            self._text, self._lang = text, lang
        def transcribe(self, samples, **kw):
            return ([FakeSegment(self._text)],
                    types.SimpleNamespace(language=self._lang))

    voice._model = FakeModel(" ravyn what do you think ", "en")
    voice._handle([0.0] * 32000)

    signal = queue.pop()
    check("it becomes a voice signal",
          signal is not None and signal.source == "voice")
    check("transcribed text is trimmed",
          signal.text == "ravyn what do you think", repr(signal.text))
    check("at owner priority — the mic is his",
          signal.priority == S.OWNER_PRIORITY, str(signal.priority))
    check("and flagged as him, so she gets the loyal framing",
          signal.context["is_owner"] is True)
    check("attributed to his name, so it joins his memory thread",
          signal.context["user"] == S.VOICE_SPEAKER)
    check("it expires rather than answering a minute late",
          signal.ttl == S.VOICE_TTL, str(signal.ttl))
    check("the language comes from what Whisper HEARD, not from the text",
          signal.lang == "en", signal.lang)

    # Russian speech gets Russian back, on the same evidence.
    voice._model = FakeModel("как тебе эта игра", "ru")
    voice._handle([0.0] * 32000)
    ru = queue.pop()
    check("Russian speech is answered in Russian", ru.lang == "ru", ru.lang)

    # And a hallucination never becomes a signal.
    voice._model = FakeModel("Thanks for watching!", "en")
    voice._handle([0.0] * 32000)
    check("a hallucinated transcript is dropped", queue.pop() is None)


def test_degrades_to_silence():
    print("\n--- it fails quiet ---")
    voice = VoiceInput(SignalQueue())
    check("unavailable until a model actually loads", not voice.available)

    # run() with faster_whisper absent must return, not raise.
    saved = sys.modules.get("faster_whisper")
    sys.modules["faster_whisper"] = None      # import raises ImportError
    try:
        voice.run()
        check("a missing dependency returns instead of raising", True)
    except ImportError:
        check("a missing dependency returns instead of raising", False)
    finally:
        if saved is None:
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = saved

    check("still unavailable afterwards", not voice.available)


def test_gate_capture_contract():
    print("\n--- the gate's side of the contract ---")
    import sources.voice_gate as vg

    check("a gate with no listener captures nothing",
          vg.VoiceGate(S)._on_utterance is None)

    sink = []
    gate = vg.VoiceGate(S, on_utterance=sink.append)
    check("a gate with a listener holds it", gate._on_utterance is not None)
    gate._on_utterance("audio")
    check("and calling it reaches the listener", sink == ["audio"], str(sink))

    # The pre-roll exists because FRAMES_TO_START has already consumed ~100ms
    # of speech by the time it is confident.
    check("the pre-roll outlasts the start delay",
          vg.PREROLL_FRAMES > vg.FRAMES_TO_START,
          f"{vg.PREROLL_FRAMES} vs {vg.FRAMES_TO_START}")
    check("a cough is below the minimum utterance",
          vg.MIN_UTTERANCE_FRAMES * 0.032 >= 0.4,
          f"{vg.MIN_UTTERANCE_FRAMES * 0.032:.2f}s")
    check("and there is a ceiling on a stuck stream",
          vg.MAX_UTTERANCE_FRAMES * 0.032 <= 90,
          f"{vg.MAX_UTTERANCE_FRAMES * 0.032:.0f}s")


def main():
    test_hallucination_filter()
    test_submit_is_safe_from_the_audio_thread()
    test_signal_shape()
    test_degrades_to_silence()
    test_gate_capture_contract()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
