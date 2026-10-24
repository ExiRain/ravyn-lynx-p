"""
Can she hear you, and does she believe what she heard?

    python tools/test_hearing.py             # listen until Ctrl-C
    python tools/test_hearing.py --seconds 60
    python tools/test_hearing.py --selftest  # no microphone, check the maths

Talk at it the way you talk during a game — normal volume, normal distance,
including the quiet asides. It runs the real voice gate and the real Whisper
model, and prints what each utterance looked like on the way in:

    [1] 1.2s  peak 0.08  rms 0.011 (-39 dBFS)  QUIET
        heard [en]: "Ravyn."
        logprob -1.42  no-speech 0.88   NOT SUPPORTED BY THE AUDIO
        -> dropped: her name alone, and the audio does not carry it

"QUIET" and "NOT SUPPORTED" are the two different failures, and they are
usually the same event: a thin clip gives the decoder nothing to work with, so
it falls back on whatever it was primed with. One live session produced five
transcripts in a row that all began with her name because the name was in the
decoder's prompt and the clips were barely a second long.

So this answers the only question worth asking before tuning anything: is the
microphone too quiet, or is the decoder guessing?
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import get_settings                              # noqa: E402
from orchestrator import language                                  # noqa: E402
from sources.voice_in import (                                     # noqa: E402
    ECHO_MAX_NO_SPEECH, ECHO_MIN_LOGPROB, addressed_to_her, bare_name,
    confident, echoes_prompt, looks_like_speech,
)

settings = get_settings()

# Below this an utterance is thin enough that Whisper starts inventing. Not a
# hard rule — a measurement to compare against, taken from clips that failed.
QUIET_RMS = 0.02
VERY_QUIET_RMS = 0.008


def level(samples) -> tuple[float, float, float]:
    """peak, rms, dBFS. No numpy needed for the fallback path."""
    try:
        import numpy as np
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
    except Exception:
        values = [abs(float(s)) for s in samples] or [0.0]
        peak = max(values)
        rms = (sum(v * v for v in values) / len(values)) ** 0.5

    import math
    dbfs = 20 * math.log10(rms) if rms > 0 else -120.0
    return peak, rms, dbfs


def verdict(text: str, lang: str, conf: dict) -> tuple[bool, str]:
    """
    Exactly the decisions sources/voice_in.py makes, in the same order, so
    this cannot disagree with what she actually does.
    """
    prompt = settings.VOICE_STT_PROMPTS.get(lang or "en", "")

    if echoes_prompt(text, prompt) and not confident(conf):
        return False, "Whisper echoed its own prompt"

    addressed = addressed_to_her(text)

    if addressed and bare_name(text) and not confident(conf):
        return False, "her name alone, and the audio does not carry it"

    if not looks_like_speech(text, addressed):
        return False, "not speech (too short, or a known hallucination)"

    if not addressed:
        return False, "heard, but she was not addressed"

    return True, "reaches her"


def describe(index: int, samples, text: str, lang: str, conf: dict,
             seconds: float, elapsed: float) -> dict:
    peak, rms, dbfs = level(samples)

    tags = []
    if rms < VERY_QUIET_RMS:
        tags.append("VERY QUIET")
    elif rms < QUIET_RMS:
        tags.append("QUIET")

    print(f"\n[{index}] {seconds:.1f}s  peak {peak:.3f}  "
          f"rms {rms:.4f} ({dbfs:.0f} dBFS)  {' '.join(tags)}")
    print(f"    heard [{lang}] in {elapsed:.1f}s: {text!r}")

    supported = confident(conf)
    print(f"    logprob {conf['avg_logprob']:.2f}  "
          f"no-speech {conf['no_speech_prob']:.2f}   "
          f"{'ok' if supported else 'NOT SUPPORTED BY THE AUDIO'}")

    reaches, why = verdict(text, lang, conf)
    print(f"    -> {'REACHES HER' if reaches else 'dropped'}: {why}")

    return {"rms": rms, "peak": peak, "dbfs": dbfs, "seconds": seconds,
            "supported": supported, "reaches": reaches, "text": text}


def summarise(rows: list[dict]) -> None:
    print("\n" + "=" * 68)
    if not rows:
        print("  Nothing was captured at all.")
        print("  The gate never fired: either the wrong input device, or the "
              "VAD\n  never crossed "
              f"VOICE_VAD_THRESHOLD = {settings.VOICE_VAD_THRESHOLD}.")
        print("  Check VOICE_INPUT_DEVICE, then lower the threshold.")
        print("=" * 68 + "\n")
        return

    rms = [r["rms"] for r in rows]
    median = statistics.median(rms)
    quiet = sum(1 for r in rms if r < QUIET_RMS)
    unsupported = sum(1 for r in rows if not r["supported"])
    reached = sum(1 for r in rows if r["reaches"])

    print(f"  {len(rows)} utterances captured")
    print(f"  median rms          : {median:.4f}  "
          f"({'thin' if median < QUIET_RMS else 'healthy'})")
    print(f"  quiet clips         : {quiet}/{len(rows)}")
    print(f"  not supported by audio: {unsupported}/{len(rows)}")
    print(f"  would reach her     : {reached}/{len(rows)}")
    print("-" * 68)

    if median < VERY_QUIET_RMS:
        print("  The microphone is the problem, not the model. Raise the input")
        print("  gain in Windows (Sound > Input > device properties) or move")
        print("  closer, then run this again. Tuning thresholds against audio")
        print("  this thin only trades silence for invention.")
    elif median < QUIET_RMS:
        print("  Borderline. Raise the input gain a little; if you would")
        print("  rather not, VOICE_VAD_THRESHOLD = 0.35 makes the gate start")
        print(f"  on quieter speech (currently "
              f"{settings.VOICE_VAD_THRESHOLD}).")
    elif unsupported > len(rows) / 3:
        print("  Level is fine and the decoder is still unsure, so this is the")
        print(f"  model: VOICE_STT_MODEL = \"{settings.VOICE_STT_MODEL}\" ->")
        print("  \"medium\" is markedly better on short clips, at more CPU per")
        print("  utterance. CPU int8, so it costs latency, not VRAM.")
    else:
        print("  Hearing looks healthy. If she still answers things you did")
        print("  not say, it is the decision path, not the audio — send the")
        print("  session log.")

    short = [r for r in rows if r["seconds"] < 1.5]
    if short:
        print(f"\n  {len(short)} clip(s) under 1.5s. Short clips are where the")
        print("  decoder leans hardest on its prompt — the failures in the")
        print("  live session were all 1.1-1.2s.")

    print("=" * 68 + "\n")


def selftest() -> int:
    """No microphone involved — checks the maths and the decision order."""
    print("\n--- levels ---")
    loud = [0.5, -0.5] * 100
    thin = [0.005, -0.005] * 100
    for name, samples in (("loud", loud), ("thin", thin)):
        peak, rms, dbfs = level(samples)
        print(f"  {name:5} peak {peak:.3f}  rms {rms:.4f}  {dbfs:.0f} dBFS")
    print(f"  silence -> {level([])}")

    print("\n--- the decisions, same order as sources/voice_in.py ---")
    shaky = {"avg_logprob": -1.4, "no_speech_prob": 0.9}
    sure = {"avg_logprob": -0.2, "no_speech_prob": 0.05}
    cases = [
        ("Ravyn.", shaky, False),
        ("Ravyn?", sure, True),
        ("League of Legends.", shaky, False),
        ("Ravyn, what do you make of this?", shaky, True),
        ("go bot now", sure, False),
        ("you", shaky, False),
    ]
    failures = 0
    for text, conf, expected in cases:
        reaches, why = verdict(text, "en", conf)
        ok = reaches == expected
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {text!r:36} -> "
              f"{'reaches' if reaches else 'dropped'}: {why}")

    print(f"\n  thresholds: logprob >= {ECHO_MIN_LOGPROB}, "
          f"no-speech <= {ECHO_MAX_NO_SPEECH}")
    print(f"  prompt [en]: {settings.VOICE_STT_PROMPTS['en']!r}")
    print()
    return 1 if failures else 0


def listen(seconds: float | None) -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        print(f"Missing dependency: {e}\npip install faster-whisper")
        return 1
    try:
        from sources.voice_gate import VoiceGate
    except Exception as e:
        print(f"Could not load the voice gate: {e}")
        return 1

    print(f"Loading {settings.VOICE_STT_MODEL} on CPU (int8)...")
    model = WhisperModel(settings.VOICE_STT_MODEL, device="cpu",
                         compute_type="int8")

    rows: list[dict] = []
    index = 0

    def on_utterance(samples) -> None:
        nonlocal index
        index += 1
        t0 = time.time()
        pinned = settings.VOICE_STT_LANGUAGE or None

        segments, info = model.transcribe(
            samples,
            language=pinned,
            initial_prompt=settings.VOICE_STT_PROMPTS.get(pinned or "en"),
            beam_size=settings.VOICE_STT_BEAM,
            vad_filter=False,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        segs = list(segments)
        text = " ".join(s.text for s in segs).strip()
        conf = {
            "avg_logprob": min((getattr(s, "avg_logprob", 0.0) for s in segs),
                               default=0.0),
            "no_speech_prob": max((getattr(s, "no_speech_prob", 0.0)
                                   for s in segs), default=0.0),
        }

        lang = pinned or (getattr(info, "language", "") or "en")
        if text and language.cyrillic_ratio(text) >= language.CYRILLIC_THRESHOLD:
            lang = "ru"

        rows.append(describe(index, samples, text, lang, conf,
                             len(samples) / 16000.0, time.time() - t0))

    gate = VoiceGate(settings, on_utterance=on_utterance)

    import threading
    threading.Thread(target=gate.run, daemon=True, name="gate").start()

    print("Talk the way you talk mid-game. Ctrl-C when done.\n")
    deadline = time.time() + seconds if seconds else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            gate.stop()
        except Exception:
            pass

    summarise(rows)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--seconds", type=float,
                    help="stop after this long (default: until Ctrl-C)")
    ap.add_argument("--selftest", action="store_true",
                    help="no microphone — check the maths and the decisions")
    args = ap.parse_args()

    return selftest() if args.selftest else listen(args.seconds)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
