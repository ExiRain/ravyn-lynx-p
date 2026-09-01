"""
Ravyn-Lynx PC — Orchestrator + TTS + Audio Server

The PC owns everything the viewer experiences: it decides what Ravyn
reacts to, speaks it, and drives the avatar. The notebook is an LLM
service — it writes her lines and nothing else.

Usage:
    python -m app.main                # full stack: orchestrator + TTS
    python -m app.main --no-tts       # silent mode — log her lines, no audio
    python -m app.main --no-voice     # disable the voice gate (VAD)
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
from sources.silence_filler import SilenceFiller


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEST_MODE = "--test" in sys.argv
NO_TWITCH = "--no-twitch" in sys.argv
NO_LOL = "--no-lol" in sys.argv
NO_TTS = "--no-tts" in sys.argv
NO_VOICE = "--no-voice" in sys.argv


def main():
    settings = get_settings()
    tts_enabled = settings.TTS_ENABLED and not NO_TTS

    print("=" * 50)
    print("  Ravyn-Lynx Orchestrator")
    if TEST_MODE:
        print("  *** TEST MODE ***")
    if tts_enabled:
        print(f"  *** PC TTS ACTIVE ({settings.TTS_BACKEND}) ***")
    else:
        print("  *** SILENT MODE — no audio ***")
    print("=" * 50)
    print(f"  Rabbit: {settings.RABBIT_HOST}:{settings.RABBIT_PORT}")
    if not NO_TWITCH and not TEST_MODE:
        print(f"  Twitch: #{settings.TWITCH_CHANNEL}")
    if not NO_LOL and not TEST_MODE:
        print(f"  LoL: active")
    if tts_enabled:
        print(f"  Audio: ws://localhost:{settings.AUDIO_SERVER_PORT}/ws/audio")
    print("=" * 50)

    # --- Orchestrator core ---
    # Built first: the response listener clears its busy flag, so it needs
    # the dispatcher to exist before it starts consuming.
    queue = SignalQueue()
    dispatcher = Dispatcher(queue)

    # Voice gate. Built after the dispatcher so is_muted can be its bound
    # method: her own voice coming back through the speakers would otherwise
    # read as the streamer talking and hold her off indefinitely.
    if settings.VOICE_GATE_ENABLED and not NO_VOICE:
        from sources.voice_gate import VoiceGate
        dispatcher.voice_gate = VoiceGate(settings, is_muted=dispatcher.is_busy)
        Thread(target=dispatcher.voice_gate.run,
               daemon=True, name="voice-gate").start()

    # --- Audio pipeline ---
    tts = None

    if tts_enabled:
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

        from services.tts_engine import build_engine
        tts = build_engine(settings)
        tts.load()

    # Consumes ravyn.response, speaks it, then marks Ravyn idle again.
    # Runs in silent mode too — otherwise nothing would ever clear busy
    # and the dispatcher would stall after the first signal.
    from services.response_listener import start_response_listener

    Thread(
        target=start_response_listener,
        args=(tts,),
        kwargs={"on_complete": lambda: dispatcher.set_busy(False)},
        daemon=True,
        name="response-listener",
    ).start()

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
