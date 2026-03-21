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
    SILENCE_THRESHOLD = 10.0            # val(600)
    SILENCE_MIN_INTERVAL = 25.0         # val(120)
    IMPROV_ENABLED = True
    QUOTE_ENABLED = True
    IMPROV_WEIGHT = 0.6

    # --- Twitch ---
    TWITCH_CHANNEL = "exiledra1n"          # your channel name (lowercase)


def get_settings():
    return Settings()