"""
Ravyn-Lynx PC — Orchestrator + TTS + Audio Server

Usage:
    python -m app.main                # full stack: orchestrator + PC TTS
    python -m app.main --no-tts       # orchestrator only, use notebook TTS
    python -m app.main --test         # mock sources
    python -m app.main --no-twitch
    python -m app.main --no-lol
"""

import sys
import time
import uvicorn
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
NO_LOL = "--no-lol" in sys.argv
NO_TTS = "--no-tts" in sys.argv


def main():
    settings = get_settings()
    tts_enabled = settings.TTS_ENABLED and not NO_TTS

    print("=" * 50)
    print("  Ravyn-Lynx Orchestrator")
    if TEST_MODE:
        print("  *** TEST MODE ***")
    if tts_enabled:
        print("  *** PC TTS ACTIVE (Chatterbox Turbo) ***")
    else:
        print("  TTS: notebook (remote)")
    print("=" * 50)
    print(f"  Rabbit: {settings.RABBIT_HOST}:{settings.RABBIT_PORT}")
    if not NO_TWITCH and not TEST_MODE:
        print(f"  Twitch: #{settings.TWITCH_CHANNEL}")
    if not NO_LOL and not TEST_MODE:
        print(f"  LoL: active")
    if tts_enabled:
        print(f"  Audio: ws://localhost:{settings.AUDIO_SERVER_PORT}/ws/audio")
    print("=" * 50)

    # --- PC TTS pipeline (if enabled) ---
    if tts_enabled:
        # start local WebSocket audio server for Godot
        from services.audio_server import app as audio_app

        def _run_audio_server():
            uvicorn.run(
                audio_app,
                host=settings.AUDIO_SERVER_HOST,
                port=settings.AUDIO_SERVER_PORT,
                log_level="warning",
            )

        Thread(target=_run_audio_server, daemon=True, name="audio-server").start()
        time.sleep(1)  # let server start

        # load TTS engine
        from services.tts_engine import TTSEngine
        tts = TTSEngine(
            device=settings.TTS_DEVICE,
            voice_ref=settings.TTS_VOICE_REF or None,
        )
        tts.load()

        # start response listener (consumes LLM responses, runs TTS, streams to Godot)
        from services.response_listener import start_response_listener

        Thread(
            target=start_response_listener,
            args=(tts,),
            daemon=True,
            name="response-listener",
        ).start()

    # --- Orchestrator ---
    queue = SignalQueue()
    dispatcher = Dispatcher(queue)

    Thread(target=start_status_listener, args=(dispatcher,),
           daemon=True, name="status-listener").start()

    # --- Silence Filler ---
    silence = SilenceFiller(queue, DATA_DIR)
    dispatcher.on_dispatch(silence.on_activity)
    Thread(target=silence.run, daemon=True, name="silence-filler").start()

    # --- LoL ---
    lol = None
    if not NO_LOL and not TEST_MODE:
        from sources.lol_game import LolGameSource
        lol = LolGameSource(queue, DATA_DIR)

        def _sync_game(signal):
            if lol:
                silence.game_active = lol.is_game_active

        dispatcher.on_dispatch(_sync_game)
        Thread(target=lol.run, daemon=True, name="lol-game").start()

    # --- Twitch ---
    if not NO_TWITCH and not TEST_MODE:
        from sources.twitch_chat import TwitchChatSource
        twitch = TwitchChatSource(queue)
        Thread(target=twitch.run, daemon=True, name="twitch-chat").start()

    # --- Mock ---
    if TEST_MODE:
        from sources.mock_chat import MockChatSource
        from sources.mock_events import MockEventSource
        from sources.mock_game import MockGameSource
        Thread(target=MockChatSource(queue, 15.0, 45.0).run, daemon=True).start()
        Thread(target=MockEventSource(queue, 30.0, 90.0).run, daemon=True).start()
        Thread(target=MockGameSource(queue, 20.0, 60.0).run, daemon=True).start()

    # --- Run dispatcher (blocks) ---
    dispatcher.run()


if __name__ == "__main__":
    main()