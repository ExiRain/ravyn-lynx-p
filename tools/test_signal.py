"""
Test tool for pushing signals through the orchestrator.

Usage:
    python -m tools.test_signal                     # interactive menu
    python -m tools.test_signal chat "hello ravyn"   # direct chat signal
    python -m tools.test_signal quote                # random quote (skip LLM)
    python -m tools.test_signal sub "username"       # fake sub event
    python -m tools.test_signal raw "any text"       # plain text to LLM
"""

import sys
import json
import pika
from app.settings import get_settings


settings = get_settings()


PRESETS = {
    "chat": {
        "source": "chat",
        "priority": 5,
        "mode": "improv",
        "skip_llm": False,
        "ttl": 120,
        "context": {"trigger": "chat_message", "user": "test_viewer"},
    },
    "sub": {
        "source": "eventsub",
        "priority": 1,
        "mode": "improv",
        "skip_llm": False,
        "ttl": None,
        "context": {"trigger": "subscription", "event_type": "sub"},
    },
    "follow": {
        "source": "eventsub",
        "priority": 1,
        "mode": "improv",
        "skip_llm": False,
        "ttl": None,
        "context": {"trigger": "follow", "event_type": "follow"},
    },
    "quote": {
        "source": "silence_filler",
        "priority": 10,
        "mode": "quote",
        "skip_llm": True,
        "ttl": None,
        "context": {"trigger": "test"},
    },
    "raw": {
        "source": "test",
        "priority": 5,
        "mode": "improv",
        "skip_llm": False,
        "ttl": None,
        "context": {"trigger": "manual_test"},
    },
}


def send_signal(preset_name: str, text: str):
    """Build and publish a signal directly to ravyn.request."""

    preset = PRESETS.get(preset_name, PRESETS["raw"])

    payload = {
        "text": text,
        "source": preset["source"],
        "mode": preset["mode"],
        "skip_llm": preset["skip_llm"],
        "context": preset["context"],
    }

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.RABBIT_HOST,
            port=settings.RABBIT_PORT,
            credentials=pika.PlainCredentials(
                settings.RABBIT_USER,
                settings.RABBIT_PASS,
            ),
        )
    )

    channel = connection.channel()
    channel.queue_declare(queue=settings.QUEUE_REQUEST)

    channel.basic_publish(
        exchange="",
        routing_key=settings.QUEUE_REQUEST,
        body=json.dumps(payload),
    )

    connection.close()

    print(f"Sent [{preset_name}]: {text[:60]}...")


def interactive():
    """Interactive menu for testing different signal types."""

    print("\nRavyn Signal Tester")
    print("=" * 40)
    print("Commands:")
    print("  chat <message>     Chat message (goes through LLM)")
    print("  sub <username>     Fake subscription event")
    print("  follow <username>  Fake follow event")
    print("  quote <text>       Direct to TTS (skip LLM)")
    print("  raw <text>         Plain text to LLM")
    print("  exit               Quit")
    print("=" * 40)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            break

        parts = user_input.split(" ", 1)
        cmd = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        if cmd == "chat":
            if not text:
                text = input("  Message: ").strip()
            send_signal("chat", text)

        elif cmd == "sub":
            username = text or "test_viewer"
            send_signal("sub", f"{username} just subscribed to the channel!")

        elif cmd == "follow":
            username = text or "new_follower"
            send_signal("follow", f"{username} just followed the channel!")

        elif cmd == "quote":
            if not text:
                text = "Testing... one two three."
            send_signal("quote", text)

        elif cmd == "raw":
            if not text:
                text = input("  Text: ").strip()
            send_signal("raw", text)

        else:
            # treat everything else as a chat message
            send_signal("chat", user_input)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

        if cmd == "chat":
            send_signal("chat", text or "hello from test")
        elif cmd == "sub":
            send_signal("sub", f"{text or 'test_viewer'} just subscribed!")
        elif cmd == "follow":
            send_signal("follow", f"{text or 'new_follower'} just followed!")
        elif cmd == "quote":
            send_signal("quote", text or "Testing... one two three.")
        elif cmd == "raw":
            send_signal("raw", text or "hello")
        else:
            send_signal("raw", " ".join(sys.argv[1:]))
    else:
        interactive()