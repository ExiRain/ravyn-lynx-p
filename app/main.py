from threading import Thread

from adapters.mq.rabbitmq import send_request, listen_response
from adapters.audio.stream_client import start_stream


def on_response(msg):
    print("\nNotebook responded:", msg)


def main():

    # start audio stream listener
    stream_thread = Thread(target=start_stream, daemon=True)
    stream_thread.start()

    # start response listener
    response_thread = Thread(target=listen_response, args=(on_response,), daemon=True)
    response_thread.start()

    print("Connected. Type a message and press ENTER.")
    print("Type 'exit' to quit.\n")

    while True:

        user_input = input("YOU > ").strip()

        if user_input.lower() == "exit":
            break

        if not user_input:
            continue

        send_request(user_input)


if __name__ == "__main__":
    main()