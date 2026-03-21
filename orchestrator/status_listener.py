from __future__ import annotations

import pika

from app.settings import get_settings


def start_status_listener(dispatcher) -> None:
    """
    Blocking consumer for ravyn.status queue.
    Run in a daemon thread.

    The notebook publishes:
      "BUSY"  — when it starts processing a request
      "IDLE"  — after END is sent to Godot (audio finished streaming)
    """

    s = get_settings()

    credentials = pika.PlainCredentials(s.RABBIT_USER, s.RABBIT_PASS)

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=s.RABBIT_HOST,
            port=s.RABBIT_PORT,
            credentials=credentials,
        )
    )

    channel = connection.channel()
    channel.queue_declare(queue=s.QUEUE_STATUS)

    print("[status] Listening on", s.QUEUE_STATUS)

    def on_message(ch, method, properties, body):
        msg = body.decode().strip().upper()

        if msg == "IDLE":
            dispatcher.set_busy(False)
            print("[status] Ravyn is IDLE")
        elif msg == "BUSY":
            dispatcher.set_busy(True)
            print("[status] Ravyn is BUSY")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(
        queue=s.QUEUE_STATUS,
        on_message_callback=on_message,
    )

    channel.start_consuming()