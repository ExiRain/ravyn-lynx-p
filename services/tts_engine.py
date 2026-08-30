"""
TTS engines for Ravyn's voice.

Two backends behind one interface, chosen by settings.TTS_BACKEND:

  "qwen"       Qwen3-TTS. Native Russian, better quality, and — when the
               faster-qwen3-tts wrapper is installed — several times faster
               than realtime. Clones from a reference wav plus its transcript.

  "chatterbox" Chatterbox Turbo. English only, and pinned against torch 2.6
               which cannot drive a Blackwell card, so it runs here only
               because that pin is overridden. Kept as a fallback.

Both run on the PC's GPU.
"""

from __future__ import annotations

import io
import time
import numpy as np
import soundfile as sf


# Qwen3-TTS language names, keyed by the values our resolver produces.
# "multilang" means the LLM mirrored whoever spoke, so we do not know the
# language up front — hand that to Qwen's own auto-detection.
QWEN_LANGUAGES = {
    "en": "English",
    "ru": "Russian",
    "multilang": "Auto",
}

WARMUP_TEXT = "Hello. This is a warmup line."


def _to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Float or int audio -> 16-bit PCM WAV bytes."""
    if audio is None:
        return b""

    audio = np.asarray(audio).squeeze()
    if audio.size == 0:
        return b""

    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


class TTSEngine:
    """Interface the response listener talks to."""

    DEFAULT_SAMPLE_RATE = 24000

    def __init__(self, device: str = "cuda", voice_ref: str | None = None):
        self.device = device
        self.voice_ref = voice_ref
        self.model = None
        self.sample_rate = self.DEFAULT_SAMPLE_RATE
        self._loaded = False

    def load(self) -> None:
        raise NotImplementedError

    def generate(self, text: str, mood: float = 0.0,
                 tired: float = 0.0, lang: str = "en") -> bytes:
        raise NotImplementedError

    @property
    def sr(self) -> int:
        return self.sample_rate

    def _warmup(self) -> None:
        """
        Burn the first generation here rather than on stream.

        The first call compiles CUDA kernels and runs cuDNN autotuning, which
        measured ~15s against ~2s for every call after it. Without this, the
        first thing Ravyn says each session lags far behind its trigger.
        """
        print("[tts] Warming up...")
        t0 = time.time()
        try:
            self.generate(WARMUP_TEXT)
            print(f"[tts] Warm in {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[tts] Warmup failed (continuing): {e}")


class QwenTTSEngine(TTSEngine):
    """
    Qwen3-TTS with voice cloning.

    Prefers the faster-qwen3-tts wrapper, which is where the speed actually
    comes from: the official package runs the reference implementation at
    roughly realtime (RTF ~1.3), while CUDA graphs plus a static KV cache take
    the same model to ~4.8x. Model size barely matters for this — at batch
    size 1 the bottleneck is kernel launch overhead, not compute.
    """

    def __init__(self, device="cuda", voice_ref=None, model_id="",
                 ref_text="", attn_implementation="sdpa"):
        super().__init__(device=device, voice_ref=voice_ref)
        self.model_id = model_id
        self.ref_text = ref_text
        self.attn_implementation = attn_implementation
        self.is_fast = False
        self._clone_prompt = None

    def load(self) -> None:
        import torch

        if not self.voice_ref:
            raise RuntimeError(
                "TTS_VOICE_REF is empty. Qwen3-TTS clones from a reference wav.")

        if not self.ref_text:
            raise RuntimeError(
                "TTS_QWEN_REF_TEXT is empty. Voice cloning needs the transcript "
                f"of {self.voice_ref} — write out exactly what is said in it, "
                "word for word, in app/settings.py. Cloning without it degrades "
                "badly.")

        print(f"[tts] Loading {self.model_id} on {self.device}...")
        t0 = time.time()

        try:
            from faster_qwen3_tts import FasterQwen3TTS
            self.model = FasterQwen3TTS.from_pretrained(self.model_id)
            self.is_fast = True
            print("[tts] Using faster-qwen3-tts (CUDA graphs)")
        except ImportError:
            from qwen_tts import Qwen3TTSModel
            self.model = Qwen3TTSModel.from_pretrained(
                self.model_id,
                device_map=self.device,
                dtype=torch.bfloat16,
                attn_implementation=self.attn_implementation,
            )
            self.is_fast = False
            print("[tts] Using official qwen-tts (no CUDA graphs — expect "
                  "roughly realtime; pip install faster-qwen3-tts for ~4x)")

        # Build the reference conditioning once. We generate sentence by
        # sentence, so recomputing the reference features on every call would
        # pay that cost several times per line.
        try:
            self._clone_prompt = self.model.create_voice_clone_prompt(
                ref_audio=self.voice_ref, ref_text=self.ref_text)
            print("[tts] Voice clone prompt cached")
        except Exception as e:
            print(f"[tts] Could not cache clone prompt ({e}) — "
                  f"passing the reference on every call instead")
            self._clone_prompt = None

        self._loaded = True
        print(f"[tts] Loaded in {time.time() - t0:.1f}s")
        self._warmup()
        print(f"[tts] sr={self.sample_rate}")

    def generate(self, text: str, mood: float = 0.0,
                 tired: float = 0.0, lang: str = "en") -> bytes:
        if not self._loaded:
            self.load()

        if not text or not text.strip():
            return b""

        language = QWEN_LANGUAGES.get(lang, "English")

        kwargs = {"text": text, "language": language}
        if self._clone_prompt is not None:
            kwargs["voice_clone_prompt"] = self._clone_prompt
        else:
            kwargs["ref_audio"] = self.voice_ref
            kwargs["ref_text"] = self.ref_text

        try:
            t0 = time.time()
            wavs, sr = self.model.generate_voice_clone(**kwargs)
            self.sample_rate = int(sr)

            audio = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
            print(f"[tts] Generated in {time.time() - t0:.2f}s  lang={language}")
            return _to_wav_bytes(audio, self.sample_rate)

        except Exception as e:
            print(f"[tts] Generation error: {e}")
            return b""


class ChatterboxEngine(TTSEngine):
    """Chatterbox Turbo. English only — `lang` is accepted and ignored."""

    def load(self) -> None:
        print(f"[tts] Loading Chatterbox Turbo on {self.device}...")
        t0 = time.time()

        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(device=self.device)

        self.sample_rate = int(getattr(self.model, "sr", self.DEFAULT_SAMPLE_RATE))

        self._loaded = True
        print(f"[tts] Loaded in {time.time() - t0:.1f}s  sr={self.sample_rate}")
        self._warmup()

    def generate(self, text: str, mood: float = 0.0,
                 tired: float = 0.0, lang: str = "en") -> bytes:
        if not self._loaded:
            self.load()

        if not text or not text.strip():
            return b""

        # neutral = 0.5; stronger feeling either way is more expressive,
        # tiredness flattens it
        exaggeration = max(0.1, min(1.0, 0.5 + abs(mood) * 0.3 - tired * 0.2))
        cfg_weight = 0.5 if abs(mood) < 0.3 else 0.3

        kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
        if self.voice_ref:
            kwargs["audio_prompt_path"] = self.voice_ref

        try:
            t0 = time.time()
            wav_tensor = self.model.generate(text, **kwargs)
            print(f"[tts] Generated in {time.time() - t0:.2f}s  "
                  f"exag={exaggeration:.2f} cfg={cfg_weight:.2f}")

            import torch
            if isinstance(wav_tensor, torch.Tensor):
                audio = wav_tensor.squeeze().cpu().numpy()
            else:
                audio = np.asarray(wav_tensor).squeeze()

            return _to_wav_bytes(audio, self.sample_rate)

        except Exception as e:
            print(f"[tts] Generation error: {e}")
            return b""


def build_engine(settings) -> TTSEngine:
    """Construct the engine named by settings.TTS_BACKEND."""
    backend = getattr(settings, "TTS_BACKEND", "chatterbox").lower()
    voice_ref = settings.TTS_VOICE_REF or None

    if backend == "qwen":
        return QwenTTSEngine(
            device=settings.TTS_DEVICE,
            voice_ref=voice_ref,
            model_id=settings.TTS_QWEN_MODEL,
            ref_text=settings.TTS_QWEN_REF_TEXT,
            attn_implementation=getattr(settings, "TTS_QWEN_ATTN", "sdpa"),
        )

    if backend == "chatterbox":
        return ChatterboxEngine(device=settings.TTS_DEVICE, voice_ref=voice_ref)

    raise ValueError(f"Unknown TTS_BACKEND {backend!r} — use 'qwen' or 'chatterbox'")
