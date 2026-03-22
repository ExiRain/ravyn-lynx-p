"""
Chatterbox Turbo TTS engine.

Wraps Chatterbox for Ravyn's voice synthesis.
Supports emotion exaggeration mapped from LLM mood tags
and paralinguistic tags like [laugh], [cough].

Runs on GPU (PC's 5080).
"""

from __future__ import annotations

import io
import time
import torch
import numpy as np
import soundfile as sf
from pathlib import Path


class TTSEngine:

    SAMPLE_RATE = 24000

    def __init__(self, device: str = "cuda", voice_ref: str | None = None):
        self.device = device
        self.voice_ref = voice_ref
        self.model = None
        self._loaded = False

    def load(self):
        """Load Chatterbox Turbo model."""
        print(f"[tts] Loading Chatterbox Turbo on {self.device}...")
        t0 = time.time()

        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(device=self.device)

        self._loaded = True
        print(f"[tts] Loaded in {time.time() - t0:.1f}s")

    def generate(self, text: str, mood: float = 0.0, tired: float = 0.0) -> bytes:
        """
        Generate WAV audio from text.

        Args:
            text: The spoken text
            mood: -1.0 (angry) to 1.0 (happy) — maps to exaggeration
            tired: 0.0 (alert) to 1.0 (exhausted) — maps to lower energy

        Returns:
            WAV bytes (PCM 16-bit, 24kHz mono)
        """
        if not self._loaded:
            self.load()

        if not text or not text.strip():
            return b""

        # map mood to Chatterbox exaggeration parameter
        # neutral = 0.5, happy = 0.7-0.8, angry = 0.7-0.8 (both are expressive)
        # tired = lower exaggeration
        base_exaggeration = 0.5
        mood_boost = abs(mood) * 0.3   # stronger emotion = more expression
        tired_dampen = tired * 0.2      # tiredness reduces expression
        exaggeration = max(0.1, min(1.0,
            base_exaggeration + mood_boost - tired_dampen))

        # cfg_weight — lower for calmer, higher for more dramatic
        cfg_weight = 0.5 if abs(mood) < 0.3 else 0.3

        try:
            t0 = time.time()

            kwargs = {
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
            }

            if self.voice_ref:
                kwargs["audio_prompt_path"] = self.voice_ref

            wav_tensor = self.model.generate(text, **kwargs)

            gen_time = time.time() - t0
            print(f"[tts] Generated in {gen_time:.2f}s  exag={exaggeration:.2f}  cfg={cfg_weight:.2f}")

            # convert tensor to WAV bytes
            return self._tensor_to_wav(wav_tensor)

        except Exception as e:
            print(f"[tts] Generation error: {e}")
            return b""

    def _tensor_to_wav(self, wav_tensor) -> bytes:
        """Convert Chatterbox output tensor to WAV bytes."""
        if wav_tensor is None:
            return b""

        # chatterbox returns (1, samples) tensor
        if isinstance(wav_tensor, torch.Tensor):
            audio = wav_tensor.squeeze().cpu().numpy()
        else:
            audio = np.array(wav_tensor).squeeze()

        audio = audio.astype(np.float32)

        buf = io.BytesIO()
        sf.write(buf, audio, self.SAMPLE_RATE, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.read()

    @property
    def sr(self) -> int:
        return self.SAMPLE_RATE