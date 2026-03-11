import pika

from app.settings import get_settings


settings = get_settings()


def connect():

    credentials = pika.PlainCredentials(
        settings.RABBIT_USER,
        settings.RABBIT_PASS
    )

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.RABBIT_HOST,
            port=settings.RABBIT_PORT,
            credentials=credentials
        )
    )

    channel = connection.channel()

    channel.queue_declare(queue=settings.QUEUE_REQUEST)
    channel.queue_declare(queue=settings.QUEUE_RESPONSE)

    return connection, channel


def send_request(text: str):

    connection, channel = connect()

    channel.basic_publish(
        exchange="",
        routing_key=settings.QUEUE_REQUEST,
        body=text
    )

    connection.close()


def listen_response(callback):

    connection, channel = connect()

    def _callback(ch, method, properties, body):

        message = body.decode()

        callback(message)

        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(
        queue=settings.QUEUE_RESPONSE,
        on_message_callback=_callback
    )

    print("Waiting for notebook response...")

    channel.start_consuming()