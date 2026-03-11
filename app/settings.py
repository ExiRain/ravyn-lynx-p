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


def get_settings():
    return Settings()