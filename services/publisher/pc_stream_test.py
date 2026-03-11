import requests
import pyaudio

NOTEBOOK_IP = "192.168.1.154"
STREAM_URL = f"http://{NOTEBOOK_IP}:9000/stream/test"

CHUNK = 4096

p = pyaudio.PyAudio()

stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=22050,
    output=True
)

print("Connecting to audio stream...")

with requests.get(STREAM_URL, stream=True) as r:
    for chunk in r.iter_content(CHUNK):
        if chunk:
            stream.write(chunk)

stream.stop_stream()
stream.close()
p.terminate()