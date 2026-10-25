"""
Ravyn-Lynx PC — Orchestrator + TTS + Audio Server

The PC owns everything the viewer experiences: it decides what Ravyn
reacts to, speaks it, and drives the avatar. The notebook is an LLM
service — it writes her lines and nothing else.

Usage:
    python -m app.main                # a stream: chat, voice, alerts, promos
    python -m app.main --league       # he is playing League
    python -m app.main --ghost        # invisible until she speaks

Two mode flags, both off by default, one per kind of stream — written that way
because the shortcuts are:

    --league   starts the game source, puts the game gates on her promos, and
               keeps the League part of her persona in the prompt. Without it
               she drags every subject back to a game nobody is playing
               (STATUS.md §7), so this is not only about the game source.
    --ghost    her avatar alone: she fades in when she speaks and out when she
               stops, so she is not sitting on top of something that matters.
               Nothing else about her changes.

The rest are switches for debugging, not modes:

    python -m app.main --no-tts       # silent — log her lines, no audio
    python -m app.main --no-voice     # disable the voice gate (VAD)
    python -m app.main --no-hear      # keep the gate, but do not transcribe
    python -m app.main --no-twitch    # no chat
    python -m app.main --no-alerts    # no StreamElements polling
    python -m app.main --no-promo     # she never asks for a follow or a sub
    python -m app.main --test         # mock sources
    python -m app.main --debug-alerts # /debug/alert and /debug/promo fire a
                                       # test event through the live pipeline
                                       # — real TTS, real Godot, no donation
                                       # or gate wait needed. Needs TTS on
                                       # (it rides the audio server). See
                                       # tools/test_live.py and
                                       # tools/fire_alert.py.
"""

import sys
import time
import uvicorn
from pathlib import Path
from threading import Thread

from app.settings import Settings, get_settings
from orchestrator import session_log, temper as temper_engine
from orchestrator.identity import Identity
from orchestrator.priority_queue import SignalQueue
from orchestrator.dispatcher import Dispatcher
from sources.silence_filler import SilenceFiller


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEST_MODE = "--test" in sys.argv
NO_TWITCH = "--no-twitch" in sys.argv
NO_TTS = "--no-tts" in sys.argv
NO_ALERTS = "--no-alerts" in sys.argv
NO_PROMO = "--no-promo" in sys.argv
NO_VOICE = "--no-voice" in sys.argv
NO_HEAR = "--no-hear" in sys.argv
DEBUG_ALERTS = "--debug-alerts" in sys.argv

# The two modes. Off by default and turned on per run — one shortcut per kind
# of stream, rather than a default that has to be argued out of.
LEAGUE = "--league" in sys.argv
GHOST = "--ghost" in sys.argv

# Written onto the class, so every component reads ONE answer to each: the
# promo's game gates, the dispatcher stamping league_mode onto every request
# for the notebook, the audio server's fades. `get_settings()` builds a fresh
# object per call and these are plain class attributes, so an instance would
# have been a copy that disagreed with the flag.
Settings.LEAGUE_MODE = LEAGUE
Settings.GHOST_MODE = GHOST


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
    print(f"  Mode: {'League' if LEAGUE else 'variety'}"
          + ("  + ghost" if GHOST else ""))
    if not NO_ALERTS and not TEST_MODE:
        print(f"  Alerts: StreamElements"
              + ("" if settings.SE_JWT else "  (no RAVYN_SE_JWT — off)"))
    if tts_enabled:
        print(f"  Audio: ws://localhost:{settings.AUDIO_SERVER_PORT}/ws/audio")
    print("=" * 50)

    # --- Session log ---
    # Opened before anything can dispatch: a signal that goes out before this
    # exists is a line missing from the transcript. See tools/analyze_session.py.
    session_log.init(
        Path(__file__).resolve().parent.parent / settings.SESSION_LOG_DIR,
        enabled=settings.SESSION_LOG_ENABLED,
        full_context=settings.SESSION_LOG_FULL_CONTEXT,
    )

    # --- Orchestrator core ---
    # Built first: the response listener clears its busy flag, so it needs
    # the dispatcher to exist before it starts consuming.
    # Who he is, loaded once and shared by chat and the game source. It used
    # to be three separate hardcoded lists.
    identity = Identity(DATA_DIR / "identity.json")

    queue = SignalQueue()
    dispatcher = Dispatcher(queue)

    # Her temper for this run — NEUTRAL at startup, and the session clock
    # starts here. It ages on its own, so a long stream softens or hardens
    # whether or not a game is ever played.
    temper = temper_engine.Temper()
    temper.start_session()

    # Voice gate. The response listener drives its mute around actual
    # playback and asks it again, with her line already synthesised, before
    # any of it is sent to Godot — see services/response_listener.py.
    #
    # It also feeds STT when that is on: one microphone stream, one opinion
    # about whether he is talking, and one place that knows to ignore her own
    # voice coming back through the speakers.
    if settings.VOICE_GATE_ENABLED and not NO_VOICE:
        from sources.voice_gate import VoiceGate

        hearing = None
        if settings.VOICE_INPUT_ENABLED and not NO_HEAR:
            from sources.voice_in import VoiceInput
            hearing = VoiceInput(queue, identity=identity)

        dispatcher.voice_gate = VoiceGate(
            settings, on_utterance=hearing.submit if hearing else None)
        Thread(target=dispatcher.voice_gate.run,
               daemon=True, name="voice-gate").start()

        if hearing:
            Thread(target=hearing.run, daemon=True, name="voice-in").start()

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
        kwargs={
            "on_complete": lambda: dispatcher.set_busy(False),
            "voice_gate": dispatcher.voice_gate,
            "get_priority": dispatcher.inflight_priority,
            "yield_to": dispatcher.more_important_waiting,
        },
        daemon=True,
        name="response-listener",
    ).start()

    # --- Silence Filler ---
    silence = SilenceFiller(queue, DATA_DIR)
    dispatcher.on_dispatch(silence.on_activity)
    Thread(target=silence.run, daemon=True, name="silence-filler").start()

    # --- Asking for a follow or a sub ---
    # Almost entirely made of reasons not to speak — see sources/promo.py.
    # Built before the game source so that source can hand it game state.
    promo = None
    if not NO_PROMO and not TEST_MODE:
        from sources.promo import PromoSource
        promo = PromoSource(queue, DATA_DIR, temper=temper)
        Thread(target=promo.run, daemon=True, name="promo").start()

    # --- LoL ---
    lol = None
    if LEAGUE and not TEST_MODE:
        from sources.lol_game import LolGameSource
        lol = LolGameSource(queue, DATA_DIR, identity=identity, temper=temper)

        def _sync_game(signal):
            if lol:
                # Both of them hold off while a game is live, for different
                # reasons: the filler has nothing to fill, and a promo would
                # be talking over the thing people came to watch.
                silence.game_active = lol.is_game_active
                if promo:
                    promo.game_active = lol.is_game_active

        dispatcher.on_dispatch(_sync_game)
        Thread(target=lol.run, daemon=True, name="lol-game").start()

    # --- Alerts and donations (StreamElements) ---
    # Her first responsibility. Quote signals only — the name and the message
    # are sanitised here and go straight to TTS, so nothing a viewer wrote
    # ever reaches the model. Silent without RAVYN_SE_JWT.
    alerts = None
    if not NO_ALERTS and not TEST_MODE:
        from sources.stream_elements import StreamElementsSource
        alerts = StreamElementsSource(queue, DATA_DIR)
        Thread(target=alerts.run, daemon=True, name="stream-elements").start()

    # --- Twitch ---
    if not NO_TWITCH and not TEST_MODE:
        from sources.twitch_chat import TwitchChatSource
        twitch = TwitchChatSource(queue, identity=identity)
        Thread(target=twitch.run, daemon=True, name="twitch-chat").start()

    # --- Mock ---
    if TEST_MODE:
        from sources.mock_chat import MockChatSource
        from sources.mock_events import MockEventSource
        from sources.mock_game import MockGameSource
        Thread(target=MockChatSource(queue, 15.0, 45.0).run, daemon=True).start()
        Thread(target=MockEventSource(queue, 30.0, 90.0).run, daemon=True).start()
        Thread(target=MockGameSource(queue, 20.0, 60.0).run, daemon=True).start()

    # --- Debug: fire alerts/promos into the live pipeline on demand ---
    # Opt-in and needs TTS (the endpoints ride the audio server's FastAPI
    # app) — see services/audio_server.py and tools/test_live.py.
    if DEBUG_ALERTS:
        if not tts_enabled:
            print("[debug] --debug-alerts needs TTS on (it rides the audio "
                  "server) — drop --no-tts to use it")
        else:
            from services.audio_server import (register_alert_injector,
                                               register_promo_injector)
            hooked = []
            if alerts is not None:
                register_alert_injector(alerts._handle)
                hooked.append("follow/sub/tip/cheer/raid")
            if promo is not None:
                register_promo_injector(
                    fire=promo.fire,
                    status=lambda: promo._blocked(time.time()))
                hooked.append("promo")
            if hooked:
                print(f"[debug] Live test endpoints up for: "
                      f"{', '.join(hooked)} — "
                      f"http://localhost:{settings.AUDIO_SERVER_PORT}/debug/..."
                      f"\n[debug] Run: python tools/test_live.py")
            else:
                print("[debug] --debug-alerts has nothing to hook into — "
                      "both alerts and promo are disabled "
                      "(--no-alerts/--no-promo/--test)")

    # --- Run dispatcher (blocks) ---
    try:
        dispatcher.run()
    finally:
        # The whole stream, however it ended. A game summary covers one game;
        # this is the one that includes chat, voice and the idle filler.
        session_log.get().report(scope="session")


if __name__ == "__main__":
    main()
