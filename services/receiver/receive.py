import pika
import asyncio
import edge_tts
import uuid
import socket
import json
import os

RABBIT_HOST = "192.168.1.154"
QUEUE = "ravyn.response"

VOICE = "en-US-AriaNeural"

# MUST point to Godot project user folder
# Example:
#   Windows → GodotProject/userdata
#   Linux   → GodotProject/userdata
GODOT_USERDATA_DIR = r"C:/Users/ExiledR/AppData/Roaming/Godot/app_userdata/Lynx/"


# --------------------------------------------------
# TTS
# --------------------------------------------------
async def generate_tts(text: str, filepath: str):
    communicate = edge_tts.Communicate(
        text,
        VOICE,
        output_format="riff-24khz-16bit-mono-pcm"
    )
    await communicate.save(filepath)


# --------------------------------------------------
# SEND PATH TO GODOT
# --------------------------------------------------
def send_to_godot(filepath: str):

    # Godot must receive user:// path
    godot_path = "user://" + os.path.basename(filepath)

    payload = json.dumps({"audio": godot_path})

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", 8080))
        s.sendall(payload.encode("utf-8"))
        s.close()

        print("Sent to Godot:", godot_path)

    except Exception as e:
        print("Godot connection failed:", e)


# --------------------------------------------------
# RABBIT CALLBACK
# --------------------------------------------------
def callback(ch, method, properties, body):

    text = body.decode()
    print("Received:", text)

    os.makedirs(GODOT_USERDATA_DIR, exist_ok=True)

    filename = f"speech_{uuid.uuid4().hex}.wav"
    fullpath = os.path.join(GODOT_USERDATA_DIR, filename)

    asyncio.run(generate_tts(text, fullpath))

    send_to_godot(fullpath)

    ch.basic_ack(delivery_tag=method.delivery_tag)


# --------------------------------------------------
# RABBITMQ
# --------------------------------------------------
connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host=RABBIT_HOST,
        port=5672,
        credentials=pika.PlainCredentials("ravyn", "103595")
    )
)

channel = connection.channel()
channel.queue_declare(queue=QUEUE)

print("Waiting for response...")

channel.basic_consume(
    queue=QUEUE,
    on_message_callback=callback
)

channel.start_consuming()