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
FRAMES_TO_STOP = 15     # ~480ms of quiet before we call it finished


class VoiceGate:

    def __init__(self, settings, is_muted=None):
        """
        is_muted: callable returning True while Ravyn herself is speaking.
        Without it her own voice comes back through the speakers, the gate
        hears it as you talking, and she holds herself off indefinitely.
        Headphones solve it too, but not everyone wears them all the time.
        """
        self.settings = settings
        self._is_muted = is_muted or (lambda: False)

        self._speaking = False
        self._last_speech_at = 0.0
        self._lock = threading.Lock()
        self._running = True

        self.available = False      # False until the model and mic are up

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
            import numpy as np
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

            # Ignore the mic entirely while she is talking, otherwise her own
            # voice through the speakers reads as him and holds her off.
            if self._is_muted():
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
