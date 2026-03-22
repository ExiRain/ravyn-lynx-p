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
    QUEUE_STATUS = "ravyn.status"

    # --- Dispatcher ---
    DISPATCH_POLL_INTERVAL = 0.1
    IDLE_POLL_INTERVAL = 0.5

    # --- Silence Filler ---
    SILENCE_THRESHOLD = 600.0
    SILENCE_MIN_INTERVAL = 120.0
    IMPROV_ENABLED = True
    QUOTE_ENABLED = True
    IMPROV_WEIGHT = 0.6

    # --- Twitch ---
    TWITCH_CHANNEL = "exiledra1n"

    # --- PC TTS ---
    TTS_ENABLED = True                      # set False to use notebook TTS instead
    TTS_DEVICE = "cuda"                     # "cuda" or "cpu"
    TTS_VOICE_REF = "data/ravyn_voice_ref.wav"                      # path to reference wav for voice cloning, empty = default
    AUDIO_SERVER_HOST = "0.0.0.0"
    AUDIO_SERVER_PORT = 9000                # Godot connects to ws://localhost:9000/ws/audio


def get_settings():
    return Settings()