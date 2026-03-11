import requests
import pyaudio
from app.settings import get_settings


settings = get_settings()

CHUNK = 4096


def start_stream(stream_id: str = "default"):

    url = f"http://{settings.NOTEBOOK_IP}:{settings.API_PORT}/stream/{stream_id}"

    print("Connecting to audio stream:", url)

    p = pyaudio.PyAudio()

    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=22050,
        output=True
    )

    with requests.get(url, stream=True) as r:

        for chunk in r.iter_content(CHUNK):
            if chunk:
                stream.write(chunk)

    stream.stop_stream()
    stream.close()
    p.terminate()