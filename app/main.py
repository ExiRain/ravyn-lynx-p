"""
Ravyn-Lynx PC — Orchestrator entry point.

Usage:
    python -m app.main            # production — silence filler + twitch chat
    python -m app.main --test     # testing — all mock sources active
    python -m app.main --no-twitch # silence filler only, no twitch
"""

import sys
from pathlib import Path
from threading import Thread

from app.settings import get_settings
from orchestrator.priority_queue import SignalQueue
from orchestrator.dispatcher import Dispatcher
from orchestrator.status_listener import start_status_listener
from sources.silence_filler import SilenceFiller


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEST_MODE = "--test" in sys.argv
NO_TWITCH = "--no-twitch" in sys.argv


def main():

    settings = get_settings()

    print("=" * 50)
    print("  Ravyn-Lynx Orchestrator")
    if TEST_MODE:
        print("  *** TEST MODE — mock sources active ***")
    print("=" * 50)
    print(f"  Rabbit: {settings.RABBIT_HOST}:{settings.RABBIT_PORT}")
    print(f"  Silence threshold: {settings.SILENCE_THRESHOLD}s")
    print(f"  Improv: {'ON' if settings.IMPROV_ENABLED else 'OFF'}  "
          f"Quote: {'ON' if settings.QUOTE_ENABLED else 'OFF'}  "
          f"Weight: {settings.IMPROV_WEIGHT}")
    if not NO_TWITCH and not TEST_MODE:
        print(f"  Twitch: #{settings.TWITCH_CHANNEL}")
    print("=" * 50)

    queue = SignalQueue()

    # --- Dispatcher ---
    dispatcher = Dispatcher(queue)

    # --- Status listener (IDLE/BUSY from notebook) ---
    status_thread = Thread(
        target=start_status_listener,
        args=(dispatcher,),
        daemon=True,
        name="status-listener",
    )
    status_thread.start()

    # --- Silence Filler ---
    silence = SilenceFiller(queue, DATA_DIR)
    dispatcher.on_dispatch(silence.on_activity)

    silence_thread = Thread(
        target=silence.run,
        daemon=True,
        name="silence-filler",
    )
    silence_thread.start()

    # --- Twitch Chat (production mode) ---
    if not NO_TWITCH and not TEST_MODE:
        from sources.twitch_chat import TwitchChatSource

        twitch = TwitchChatSource(queue)
        dispatcher.on_dispatch(silence.on_activity)

        twitch_thread = Thread(
            target=twitch.run,
            daemon=True,
            name="twitch-chat",
        )
        twitch_thread.start()

    # --- Mock sources (test mode only) ---
    if TEST_MODE:
        from sources.mock_chat import MockChatSource
        from sources.mock_events import MockEventSource
        from sources.mock_game import MockGameSource

        mock_chat = MockChatSource(queue, min_interval=15.0, max_interval=45.0)
        Thread(target=mock_chat.run, daemon=True, name="mock-chat").start()

        mock_events = MockEventSource(queue, min_interval=30.0, max_interval=90.0)
        Thread(target=mock_events.run, daemon=True, name="mock-events").start()

        mock_game = MockGameSource(queue, min_interval=20.0, max_interval=60.0)
        Thread(target=mock_game.run, daemon=True, name="mock-game").start()

    # --- Run dispatcher (blocks) ---
    dispatcher.run()


if __name__ == "__main__":
    main()