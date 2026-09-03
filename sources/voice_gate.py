"""
Voice gate — keeps Ravyn off your voice.

Silero VAD on the microphone, exposing one question the dispatcher asks
before it sends anything: is he talking right now, or has he only just
stopped?

Three rules, from how it actually feels on stream:

  1. Once she starts a line she finishes it. Nothing here interrupts her —
     the dispatcher already refuses to send while she is busy, and her audio
     always plays to the end.
  2. While you are talking, ordinary signals wait. Game events carry TTLs, so
     ones that wait too long expire instead of arriving late and confusing.
  3. After your last word there is a hold before she may speak, so she does
     not jump into the half-second gap where you were drawing breath.

Subs, follows and donations are exempt — those are the moments a viewer paid
for and they should land promptly, so they cut through the gate.

The gate is asked TWICE per line, and the second time is the one that decides.
Asking only at dispatch was the original mistake: between that check and the
first syllable sit an LLM round trip and TTS, several seconds in which you can
easily start talking. The dispatch check only avoids paying for a line she
will not say; `services/response_listener.py` asks again with the audio
already synthesised, which is where a hold costs nothing.

Muting is likewise tied to her being AUDIBLE, not to the dispatcher being
busy. Busy starts at publish, so the old wiring made the mic deaf through the
whole generation window — deaf exactly when you were most likely to start
talking. It never heard you begin, so she spoke over you, and afterwards found
no recent speech to hold the next line against.

Degrades to "never hold" if the audio stack is missing, so a broken mic setup
leaves her behaving exactly as she does today rather than going silent.
"""

from __future__ import annotations

import threading
import time

# 512 samples at 16kHz is 32ms, which is the frame size Silero expects.
SAMPLE_RATE = 16000
FRAME_SAMPLES = 512

# Hysteresis, in frames. Entering speech quickly makes her stop talking over
# you promptly; leaving it slowly stops the gap between two words from
# registering as "he finished".
FRAMES_TO_START = 3     # ~96ms of speech before we believe it
FRAMES_TO_STOP = 25     # ~800ms of quiet before we call it finished

# 480ms was too short: ordinary pauses between phrases cleared it, so one
# sentence logged "you are talking / you stopped" three or four times and the
# post-speech hold kept re-arming from the middle of your thought. 800ms sits
# above a breath and below a real end of turn. It also lengthens the effective
# hold by its own duration, since the stop edge is what stamps last_speech_at.

# Safety net on the mute. If whatever muted her dies before unmuting, the mic
# stays deaf for the rest of the stream — which looks exactly like a broken
# gate and is miserable to diagnose live.
MUTE_SAFETY_TIMEOUT = 120.0


class VoiceGate:

    def __init__(self, settings):
        self.settings = settings

        self._speaking = False
        self._last_speech_at = 0.0

        self._muted = False
        self._muted_since = 0.0
        self._unmuted_at = 0.0

        self._lock = threading.Lock()
        self._running = True

        self.available = False      # False until the model and mic are up

    # ---------------------------------------------------------
    # mute — held only while her own audio is audible
    # ---------------------------------------------------------

    def set_muted(self, state: bool) -> None:
        """
        Call this around actual playback, not around the request.

        Her voice returns through the speakers, reads as you, and would hold
        her off indefinitely — so the mic is ignored while she is audible.
        But only while she is audible: she is silent through the LLM round
        trip and the TTS that precede it, and those are the seconds in which
        you are most likely to start talking. See the module docstring.
        """
        with self._lock:
            if state:
                self._muted = True
                self._muted_since = time.time()
                # Do not carry a stale "he is speaking" through her line — the
                # capture loop cannot clear it while deaf. last_speech_at is
                # left alone, so the post-speech hold still measures from your
                # real last word rather than from her first syllable.
                self._speaking = False
            elif self._muted:
                self._muted = False
                self._unmuted_at = time.time()

    def _deaf(self) -> bool:
        """Caller must hold the lock."""
        now = time.time()

        if self._muted:
            if now - self._muted_since > MUTE_SAFETY_TIMEOUT:
                print(f"[voice] Mute stuck for {MUTE_SAFETY_TIMEOUT:.0f}s — "
                      f"releasing the mic")
                self._muted = False
                self._unmuted_at = now
            else:
                return True

        # Speaker-to-mic latency: her last syllable is still in the air.
        return (now - self._unmuted_at) < self.settings.VOICE_MUTE_TAIL

    # ---------------------------------------------------------
    # what the dispatcher asks
    # ---------------------------------------------------------

    def should_hold(self) -> bool:
        """True while he is speaking, or still inside the post-speech hold."""
        if not self.available:
            return False

        with self._lock:
            if self._speaking:
                return True
            if self._last_speech_at <= 0:
                return False
            quiet_for = time.time() - self._last_speech_at

        return quiet_for < self.settings.VOICE_HOLD_AFTER_SPEECH

    @property
    def speaking(self) -> bool:
        with self._lock:
            return self._speaking

    def quiet_for(self) -> float:
        """Seconds since his last word. Large number if he has not spoken."""
        with self._lock:
            if self._speaking:
                return 0.0
            if self._last_speech_at <= 0:
                return 1e9
            return time.time() - self._last_speech_at

    # ---------------------------------------------------------
    # capture loop
    # ---------------------------------------------------------

    def run(self) -> None:
        """Blocking. Run in a daemon thread."""
        try:
            import sounddevice as sd
            import torch
            from silero_vad import load_silero_vad
        except ImportError as e:
            print(f"[voice] Disabled — missing dependency: {e}")
            print("[voice] pip install silero-vad sounddevice")
            return

        try:
            model = load_silero_vad()
        except Exception as e:
            print(f"[voice] Disabled — could not load Silero VAD: {e}")
            return

        device = self.settings.VOICE_INPUT_DEVICE
        threshold = self.settings.VOICE_VAD_THRESHOLD

        speech_run = 0
        silence_run = 0

        def on_audio(indata, frames, time_info, status):
            nonlocal speech_run, silence_run

            if status:
                print(f"[voice] Stream status: {status}")

            # Ignore the mic entirely while she is audible, otherwise her own
            # voice through the speakers reads as him and holds her off.
            with self._lock:
                deaf = self._deaf()
            if deaf:
                speech_run = silence_run = 0
                return

            chunk = torch.from_numpy(indata[:, 0].copy())

            try:
                prob = float(model(chunk, SAMPLE_RATE).item())
            except Exception:
                return

            if prob >= threshold:
                speech_run += 1
                silence_run = 0
                if speech_run >= FRAMES_TO_START:
                    with self._lock:
                        if not self._speaking:
                            print("[voice] You are talking — holding her")
                        self._speaking = True
                        self._last_speech_at = time.time()
            else:
                silence_run += 1
                speech_run = 0
                if silence_run >= FRAMES_TO_STOP:
                    with self._lock:
                        if self._speaking:
                            self._speaking = False
                            self._last_speech_at = time.time()
                            print(f"[voice] You stopped — holding "
                                  f"{self.settings.VOICE_HOLD_AFTER_SPEECH:.0f}s more")

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="float32", blocksize=FRAME_SAMPLES,
                                device=device, callback=on_audio):
                self.available = True
                name = device if device is not None else "default"
                print(f"[voice] Gate active on {name} — "
                      f"threshold={threshold} hold={self.settings.VOICE_HOLD_AFTER_SPEECH}s")
                while self._running:
                    time.sleep(0.2)
        except Exception as e:
            print(f"[voice] Disabled — audio input failed: {e}")
            print("[voice] List devices with: python -c "
                  "\"import sounddevice; print(sounddevice.query_devices())\"")
        finally:
            self.available = False

    def stop(self) -> None:
        self._running = False
