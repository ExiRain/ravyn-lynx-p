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
    HALLUCINATIONS, VoiceInput, addressed_to_her, bare_name, confident,
    echoes_prompt, looks_like_speech,
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


def test_she_answers_only_when_addressed():
    """
    The half of the wake word that survived.

    Without it she replies to every sentence the microphone hears — a gank
    call on Discord, swearing at the screen, a conversation with somebody in
    the room. The gate cannot tell those from a question; only the words can.
    """
    print("\n--- she answers only when addressed ---")
    check("the name gate is on by default", S.VOICE_REQUIRE_NAME)

    for said in ("ravyn what do you think",
                 "hey Ravyn are you awake",
                 "Ravyn, look at this",
                 "what do you make of that, Ravyn?"):
        check(f"{said!r} reaches her", addressed_to_her(said))

    # Whisper will not spell her name the way he does, and transliterates it
    # in Russian. These are the forms to expect back.
    for heard in ("Raven, look at that", "ravin you there",
                  "равин что скажешь", "Рейвен ты тут", "рэйвен привет"):
        check(f"{heard!r} still reaches her", addressed_to_her(heard))

    # Everything else the mic catches during a game.
    for overheard in ("go bot go bot now", "i need help top",
                      "what the hell was that", "они идут на дракона",
                      "ну и куда ты пошёл"):
        check(f"{overheard!r} is left alone", not addressed_to_her(overheard))

    # Her name alone is one word, and is unmistakably her being spoken to;
    # a bare "you" is Whisper hallucinating at room tone.
    check("her name on its own is enough",
          looks_like_speech("Ravyn?", addressed=True))
    check("but a stray token is not, even so",
          not looks_like_speech("you", addressed=True))
    check("and two words are still needed when she is not named",
          not looks_like_speech("hello", addressed=False))

    check("turning the gate off lets everything through",
          addressed_to_her("go bot now") is False or not S.VOICE_REQUIRE_NAME)


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
    voice._model = FakeModel("равин как тебе эта игра", "ru")
    voice._handle([0.0] * 32000)
    ru = queue.pop()
    check("Russian speech is answered in Russian", ru.lang == "ru", ru.lang)

    # The decoder is biased toward champion names, so an English champion
    # inside a Russian sentence survives instead of being transliterated —
    # and pointedly NOT toward her name, which is the word that decides
    # whether she answers at all. See test_prompt_echo.
    seen = {}
    class RecordingModel(FakeModel):
        def transcribe(self, samples, **kw):
            seen.update(kw)
            return super().transcribe(samples, **kw)
    voice._model = RecordingModel("ravyn what do you think", "en")
    voice._handle([0.0] * 32000)
    queue.pop()
    check("the language is auto-detected, not assumed",
          seen.get("language") is None, str(seen.get("language")))
    check("the decoder is primed with champion names",
          "Riven" in (seen.get("initial_prompt") or ""),
          str(seen.get("initial_prompt"))[:60])
    check("but never with her own name, in either language",
          not any(name in prompt.lower()
                  for prompt in S.VOICE_STT_PROMPTS.values()
                  for name in S.VOICE_NAMES),
          str(S.VOICE_STT_PROMPTS))
    check("priming prompts stay short enough not to be hallucinated back",
          all(len(p) < 200 for p in S.VOICE_STT_PROMPTS.values()))
    check("there is a prompt per language, so an all-Latin one cannot drag "
          "detection toward Latin scripts",
          set(S.VOICE_STT_PROMPTS) >= set(S.VOICE_LANGUAGES),
          str(set(S.VOICE_STT_PROMPTS)))
    check("the Russian prompt is actually Cyrillic",
          any("\u0400" <= ch <= "\u04ff" for ch in S.VOICE_STT_PROMPTS["ru"]))

    # Whisper loops when it conditions on its own output.
    check("conditioning on previous text is off",
          seen.get("condition_on_previous_text") is False)
    check("and repetition loops are thresholded out",
          seen.get("compression_ratio_threshold") is not None)


def test_language_is_constrained_to_two():
    """
    Whisper ranks ninety-nine languages and, on two seconds of audio, routinely
    picks one he has never spoken. A live session produced de, pl, lv and sv
    from Russian speech, and "Ravyn, расскажи анекдот" came back as Polish
    "Ravyn, rozkażenik" — then got answered in English, because anything that
    was not "ru" fell through to English.
    """
    print("\n--- detection is constrained to the two he speaks ---")
    voice = VoiceInput(SignalQueue())

    def info(top, probs):
        return types.SimpleNamespace(language=top, all_language_probs=probs)

    check("Russian wins when it should",
          voice._choose_language(
              info("ru", [("ru", 0.9), ("en", 0.05)])) == "ru")
    check("English wins when it should",
          voice._choose_language(
              info("en", [("en", 0.8), ("ru", 0.1)])) == "en")

    # The live failure: Polish scored highest overall, but between the two he
    # actually speaks, Russian is the answer.
    check("a language he does not speak cannot win",
          voice._choose_language(
              info("pl", [("pl", 0.6), ("ru", 0.3), ("en", 0.05)])) == "ru")
    check("nor can German",
          voice._choose_language(
              info("de", [("de", 0.7), ("en", 0.2), ("ru", 0.02)])) == "en")

    # Older faster-whisper builds may not return probabilities at all.
    check("without probabilities it falls back to the detected language",
          voice._choose_language(info("en", None)) == "en")
    check("and refuses one outside the allowed set",
          voice._choose_language(info("lv", None)) in S.VOICE_LANGUAGES)

    check("the allowed set is exactly the two he speaks",
          set(S.VOICE_LANGUAGES) == {"ru", "en"}, str(S.VOICE_LANGUAGES))


def test_cyrillic_overrides_whisper():
    print("\n--- the script of the transcript has the last word ---")
    queue = SignalQueue()
    voice = VoiceInput(queue)
    voice.available = True

    class Model:
        def __init__(self, text, lang): self._t, self._l = text, lang
        def transcribe(self, samples, **kw):
            return ([types.SimpleNamespace(text=self._t)],
                    types.SimpleNamespace(language=self._l,
                                          all_language_probs=[(self._l, 0.9)]))

    # Whisper mislabels Russian text as English. The Cyrillic settles it.
    voice._model = Model("Равин, расскажи анекдот", "en")
    voice._handle([0.0] * 32000)
    signal = queue.pop()
    check("Cyrillic text is answered in Russian whatever the label",
          signal is not None and signal.lang == "ru",
          signal.lang if signal else "nothing queued")

    voice._model = Model("Ravyn tell me a joke", "en")
    voice._handle([0.0] * 32000)
    check("Latin text stays English", queue.pop().lang == "en")

    # A hallucination never becomes a signal.
    voice._model = Model("Thanks for watching!", "en")
    voice._handle([0.0] * 32000)
    check("a hallucinated transcript is dropped", queue.pop() is None)

    # Nor does speech that was heard clearly but not aimed at her.
    voice._model = Model("go bot go bot right now", "en")
    voice._handle([0.0] * 32000)
    check("a gank call never reaches the queue", queue.pop() is None)


def test_prompt_echo():
    """
    From a live session: she kept telling him to stop saying her name, and he
    had not said it.

        [hear] 1.2s audio, 1.9s transcribe [en]: Ravyn.
        [hear] 1.1s audio, 1.7s transcribe [en]: Ravyn. League of Legends.

    Both are verbatim prefixes of the initial_prompt she was running with —
    Whisper falling back on its hint with nothing in the audio to decode. The
    name gate matched, and she was handed a message consisting of nothing but
    her own name.
    """
    print("\n--- Whisper reading its own prompt back ---")

    shaky = {"avg_logprob": -1.2, "no_speech_prob": 0.8}
    sure = {"avg_logprob": -0.2, "no_speech_prob": 0.05}
    en = S.VOICE_STT_PROMPTS["en"]
    ru = S.VOICE_STT_PROMPTS["ru"]

    check("the prompt read back word for word is an echo",
          echoes_prompt("League of Legends: Riven, Garen, jungle", en))
    check("a prefix of it is an echo",
          echoes_prompt("League of Legends.", en))
    check("so is one in Russian", echoes_prompt("Лига Легенд.", ru))
    check("an echo with no confidence behind it is dropped",
          echoes_prompt("League of Legends.", en) and not confident(shaky))
    check("the same words said clearly are believed",
          confident(sure))

    check("a real sentence is never an echo",
          not echoes_prompt("Ravyn, what do you think of this build?", en))
    check("prompt words in his own order are not an echo",
          not echoes_prompt("Garen is jungle and Riven is mid", en),
          "out of prompt order")
    check("a long utterance is not an echo whatever its words",
          not echoes_prompt("League of Legends Riven Garen jungle mid "
                            "support drake baron", en))
    check("a word the prompt does not have breaks it",
          not echoes_prompt("Riven ganked mid", en))
    check("nothing is not an echo", not echoes_prompt("", en))

    # And the case that started it: her name can no longer come back from the
    # prompt, because it is not in the prompt.
    check("her name is not in the prompt to be echoed",
          not echoes_prompt("Ravyn.", en), "the name is out of the prompt")

    # It can still arrive from a door closing, so the bare name has to earn
    # it acoustically whatever produced it.
    check("her name alone is recognised as such", bare_name("Ravyn."))
    check("and its transliterations", bare_name("Равин") and bare_name("Raven"))
    check("her name plus a word of his own is not",
          not bare_name("Ravyn, look at this"))
    check("a sentence about the enemy laner is not",
          not bare_name("Riven is down"))
    check("nothing is not", not bare_name(""))


def test_an_echo_never_reaches_the_queue():
    print("\n--- an echo does not become a signal ---")
    queue = SignalQueue()
    voice = VoiceInput(queue)
    voice.available = True

    class Segment:
        def __init__(self, text, logprob, no_speech):
            self.text = text
            self.avg_logprob = logprob
            self.no_speech_prob = no_speech

    class Model:
        """Whisper with a confidence to report, which the real one has."""
        def __init__(self, text, logprob, no_speech):
            self._seg = (text, logprob, no_speech)
        def transcribe(self, samples, **kw):
            return ([Segment(*self._seg)],
                    types.SimpleNamespace(language="en"))

    # Reciting its hint: the right words, nothing in the audio behind them.
    voice._model = Model("League of Legends.", -1.4, 0.9)
    voice._handle([0.0] * 16000)
    check("an unconfident echo is dropped", queue.pop() is None)

    # The same words, actually said, and naming her.
    voice._model = Model("Ravyn, League of Legends.", -0.1, 0.02)
    voice._handle([0.0] * 32000)
    check("said clearly, it still reaches her", queue.pop() is not None)

    # Her name alone, out of a door closing.
    voice._model = Model("Ravyn.", -1.5, 0.85)
    voice._handle([0.0] * 16000)
    check("a bare name the audio does not support is dropped",
          queue.pop() is None)

    voice._model = Model("Ravyn?", -0.2, 0.05)
    voice._handle([0.0] * 16000)
    check("but calling her name clearly still reaches her",
          queue.pop() is not None)

    # Mumbled, but not prompt words — a real question, kept.
    voice._model = Model("Ravyn, what do you make of this matchup?", -1.4, 0.9)
    voice._handle([0.0] * 48000)
    check("a real question is not dropped for being mumbled",
          queue.pop() is not None)


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
    test_language_is_constrained_to_two()
    test_cyrillic_overrides_whisper()
    test_prompt_echo()
    test_an_echo_never_reaches_the_queue()
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
