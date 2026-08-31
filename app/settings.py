from dataclasses import dataclass


@dataclass
class Settings:

    NOTEBOOK_IP = "192.168.1.154"

    API_PORT = 9000

    RABBIT_HOST = NOTEBOOK_IP
    RABBIT_PORT = 5672

    RABBIT_USER = "ravyn"
    RABBIT_PASS = "103595"

    QUEUE_REQUEST = "ravyn.request"
    QUEUE_RESPONSE = "ravyn.response"

    # --- Dispatcher ---
    DISPATCH_POLL_INTERVAL = 0.1
    IDLE_POLL_INTERVAL = 0.5
    BUSY_TIMEOUT = 90.0                     # watchdog: force-idle if no response

    # --- Silence Filler ---
    SILENCE_THRESHOLD = 600.0
    SILENCE_MIN_INTERVAL = 120.0
    IMPROV_ENABLED = True
    QUOTE_ENABLED = True
    IMPROV_WEIGHT = 0.6

    # --- Game reaction rate ---
    # Chance she says anything at all about an event. Frequent, low-stakes
    # things get filtered here so she is not commentating every second.
    # Anything absent defaults to 1.0 (always). MyDeath is deliberately absent:
    # lol_game._handle_death already coin-flips deaths 1-4, so a second roll
    # here would silence her twice over.
    REACTION_CHANCE = {
        "AllyDeath":     0.6,
        "AllyKill":      0.35,
        "TurretKilled":  0.3,
        "HeraldKill":    0.5,
        "DragonKill":    0.7,
        "MyKill":        0.8,
        "InhibKilled":   0.9,
    }

    # --- Twitch ---
    TWITCH_CHANNEL = "exiledra1n"

    # --- Language ---
    # Ambient: her own idle voice — silence filler, game reactions, promos.
    # Nobody addressed her, so there is nothing to mirror. Keep this fixed;
    # it is what stops her flipping language mid-stream.
    LANG_AMBIENT = "en"

    # Reply: how she answers someone who spoke to her.
    #   "en"        — always English
    #   "ru"        — always Russian (use this to test her Russian)
    #   "multilang" — the LLM mirrors whoever wrote to her
    #   "detect"    — decide from the message text before generating
    #
    # "detect" is the one that also works for TTS: it resolves the language
    # BEFORE the LLM runs, so the voice can be told too. With "multilang"
    # you only learn the language from her output.
    LANG_REPLY = "en"

    # Known speakers, lowercase -> language. Overrides LANG_REPLY.
    # e.g. a Russian duo partner in Discord: {"someguy": "ru"}
    SPEAKER_LANG = {}

    # --- PC TTS ---
    TTS_ENABLED = True                      # False (or --no-tts) = silent mode
    TTS_DEVICE = "cuda"                     # "cuda" or "cpu"
    TTS_VOICE_REF = "data/ravyn_voice_ref.wav"   # reference wav for voice cloning

    # "qwen"       — Qwen3-TTS. Russian + English, better quality.
    # "chatterbox" — Chatterbox Turbo. English only. Fallback if qwen misbehaves.
    TTS_BACKEND = "qwen"

    TTS_QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

    # REQUIRED for cloning: exactly what is said in TTS_VOICE_REF, word for
    # word. Qwen aligns the reference audio against this transcript; a wrong
    # or empty one degrades the clone badly, so load() refuses to start
    # without it.
    TTS_QWEN_REF_TEXT = ""

    # "sdpa" works everywhere torch does. "flash_attention_2" is faster but
    # flash-attn is painful to build on Windows — only set it if you have it.
    TTS_QWEN_ATTN = "sdpa"
    AUDIO_SERVER_HOST = "0.0.0.0"
    AUDIO_SERVER_PORT = 9000                # Godot connects to ws://localhost:9000/ws/audio


def get_settings():
    return Settings()