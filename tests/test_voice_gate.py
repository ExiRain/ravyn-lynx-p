"""
Voice gate behaviour — the rules, not the plumbing.

Silero, Rabbit, TTS and Godot are all stubbed, so this verifies decisions:
when the mic is deaf, what is dropped versus deferred, and that she never
starts a line she is not allowed to finish. Run it directly:

    python tests/test_voice_gate.py

The properties worth protecting, in order of how much it hurt to get them
wrong:

  1. The mic is live while she is *generating* and deaf only while she is
     *audible*. Tying the mute to the dispatcher's busy flag made her deaf
     through the whole LLM-plus-TTS window — deaf exactly when you were most
     likely to start talking, so she never heard you begin.
  2. The gate is asked again after synthesis, because the answer it gave at
     dispatch is several seconds old by then.
  3. Ambient chatter held by the gate is dropped, not queued.
  4. Busy always clears, on every path, or the dispatcher stalls for 90s.
"""

import json
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- stubs, installed before the modules under test are imported ---------
pika = types.ModuleType("pika")
pika.exceptions = types.SimpleNamespace(AMQPError=Exception)
sys.modules["pika"] = pika

tts_engine = types.ModuleType("services.tts_engine")
tts_engine.TTSEngine = object
sys.modules["services.tts_engine"] = tts_engine

# audio_server imports numpy and fastapi; neither is needed to test policy
audio = types.ModuleType("services.audio_server")
audio.event_loop = "loop"
audio.has_clients = lambda: True


async def _noop(*a, **k):
    return None


audio.begin_utterance = _noop
audio.end_utterance = _noop
audio.send_face = _noop
audio.push_sentence = _noop
sys.modules["services.audio_server"] = audio

from app.settings import get_settings                     # noqa: E402
from orchestrator.dispatcher import Dispatcher            # noqa: E402
from orchestrator.models import Signal                    # noqa: E402
from orchestrator.priority_queue import SignalQueue       # noqa: E402
from sources.voice_gate import VoiceGate, MUTE_SAFETY_TIMEOUT   # noqa: E402
import services.response_listener as rl                   # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# =========================================================== the mute window
def test_mute_window():
    print("\n--- mute window ---")
    gate = VoiceGate(S)
    gate.available = True

    # The bug this whole rework exists for: busy is set at publish, and she
    # stays silent for the LLM round trip and TTS after it.
    dispatcher = Dispatcher(SignalQueue(), voice_gate=gate)
    dispatcher.set_busy(True)
    with gate._lock:
        check("mic is live while she is generating, not yet audible",
              not gate._deaf())

    gate.set_muted(True)
    with gate._lock:
        check("mic is deaf while she is audible", gate._deaf())

    gate.set_muted(False)
    with gate._lock:
        check("tail keeps the mic deaf just after playback", gate._deaf())

    time.sleep(S.VOICE_MUTE_TAIL + 0.05)
    with gate._lock:
        check("mic is live again once the tail elapses", not gate._deaf())

    # Muting must not destroy the post-speech hold: it is measured from your
    # last real word, not from her first syllable.
    gate._speaking, gate._last_speech_at = True, time.time()
    gate.set_muted(True)
    check("mute clears the speaking flag the capture loop cannot",
          not gate._speaking)
    check("mute preserves last_speech_at", gate._last_speech_at > 0)
    check("post-speech hold survives her line", gate.should_hold())
    gate.set_muted(False)

    gate.set_muted(True)
    gate._muted_since = time.time() - MUTE_SAFETY_TIMEOUT - 1
    with gate._lock:
        gate._deaf()
    check("a stuck mute releases itself", not gate._muted)


# ====================================================== dispatch-side policy
class StubGate:
    def __init__(self, hold):
        self.hold = hold

    def should_hold(self):
        return self.hold


def test_dispatch_policy():
    print("\n--- dispatch policy ---")
    queue = SignalQueue()
    dispatcher = Dispatcher(queue, voice_gate=StubGate(True))

    ambient = Signal(source="silence_filler", priority=10, text="idle thought")
    chat = Signal(source="chat", priority=5, text="hello")
    sub = Signal(source="eventsub", priority=1, text="new sub")

    check("ambient is held", dispatcher._gate_holds(ambient))
    check("chat is held", dispatcher._gate_holds(chat))
    check("subs cut through", not dispatcher._gate_holds(sub))
    check("ambient is above the drop line",
          ambient.priority >= S.VOICE_AMBIENT_PRIORITY)
    check("chat is below the drop line",
          chat.priority < S.VOICE_AMBIENT_PRIORITY)

    # pop_head_if guards against a source pushing between peek and drop
    queue.push(ambient)
    queue.push(chat)
    check("head is the higher-priority signal", queue.peek() is chat)
    check("pop_head_if refuses anything but the head",
          queue.pop_head_if(ambient) is None)
    check("pop_head_if pops the head", queue.pop_head_if(chat) is chat)
    check("the other signal is untouched", queue.peek() is ambient)

    dispatcher.set_busy(True)
    dispatcher.set_inflight(ambient)
    check("in-flight priority is reported", dispatcher.inflight_priority() == 10)
    dispatcher.set_busy(False)
    check("in-flight clears with busy", dispatcher.inflight_priority() == 5)

    dispatcher.set_busy(True)
    dispatcher.set_inflight(chat)
    dispatcher._busy_since = time.time() - S.BUSY_TIMEOUT - 1
    dispatcher.is_busy()
    check("the busy watchdog clears in-flight too",
          dispatcher.inflight_priority() == 5)


# ================================================= the check that decides
GENERATED: list[str] = []


class StubTTS:
    sr = 24000

    def generate(self, text, **kw):
        GENERATED.append(text)
        return b"WAV"


class RecordingGate:
    """Records mute calls, so we can see whether anything reached Godot."""

    def __init__(self, hold):
        self.hold = hold
        self.mutes: list[bool] = []

    def should_hold(self):
        return self.hold

    def set_muted(self, state):
        self.mutes.append(state)


class _Channel:
    def queue_declare(self, **k):
        pass

    def basic_ack(self, **k):
        pass

    def basic_consume(self, queue=None, on_message_callback=None):
        self.cb = on_message_callback

    def start_consuming(self):
        pass


CHANNEL = _Channel()

TWO_CHUNKS = "First line here for you. Second line follows along nicely."


def deliver(gate, priority, text=TWO_CHUNKS):
    """Run one response end to end. Returns (elapsed, busy_cleared, gate)."""
    GENERATED.clear()
    cleared: list[bool] = []

    rl.start_response_listener(
        StubTTS(),
        on_complete=lambda: cleared.append(True),
        voice_gate=gate,
        get_priority=(lambda: priority) if gate else None,
    )

    body = json.dumps({"text": text, "mood": 0.0, "tired": 0.0,
                       "lang": "en"}).encode()
    t0 = time.time()
    CHANNEL.cb(CHANNEL, types.SimpleNamespace(delivery_tag=1), None, body)
    return time.time() - t0, cleared == [True], gate


def test_second_gate_check():
    print("\n--- the check that decides ---")

    gate, priority = RecordingGate(False), 5
    elapsed, cleared, gate = deliver(gate, priority)
    check("open gate: she speaks without waiting", elapsed < 0.5, f"{elapsed:.1f}s")
    check("open gate: every chunk synthesised", len(GENERATED) == 2, str(GENERATED))
    check("open gate: muted for the line and unmuted after",
          gate.mutes == [True, False], str(gate.mutes))
    check("open gate: busy cleared", cleared)

    elapsed, cleared, gate = deliver(RecordingGate(True), 5)
    check("held throughout: waits the defer budget",
          abs(elapsed - S.VOICE_MAX_DEFER) < 1.0, f"{elapsed:.1f}s")
    check("held throughout: only the opening chunk was paid for",
          len(GENERATED) == 1, str(GENERATED))
    check("held throughout: never muted, so Godot saw nothing",
          gate.mutes == [], str(gate.mutes))
    check("held throughout: busy still cleared", cleared)

    # You stop talking while her line is waiting at her mouth. This is the
    # payoff for synthesising first: she starts on your silence, not three
    # seconds after it.
    releasing = RecordingGate(True)
    threading.Thread(
        target=lambda: (time.sleep(1.0), setattr(releasing, "hold", False)),
        daemon=True,
    ).start()
    elapsed, cleared, gate = deliver(releasing, 5)
    check("released mid-wait: she speaks", gate.mutes == [True, False],
          str(gate.mutes))
    check("released mid-wait: starts on your silence, not on a timer",
          1.0 <= elapsed < 2.0, f"{elapsed:.1f}s")

    elapsed, cleared, gate = deliver(RecordingGate(True), 1)
    check("sub: ignores the gate", elapsed < 0.5, f"{elapsed:.1f}s")
    check("sub: spoken", gate.mutes == [True, False], str(gate.mutes))

    elapsed, cleared, _ = deliver(None, 5, text="Only line.")
    check("--no-voice: still speaks", GENERATED == ["Only line."], str(GENERATED))
    check("--no-voice: busy cleared", cleared)


def main():
    def run_async(coro, timeout):
        try:
            coro.close()
        except Exception:
            pass
        return 0.0      # zero-length audio, so no playback sleep

    rl._run_async = run_async

    pika.PlainCredentials = lambda *a, **k: None
    pika.ConnectionParameters = lambda **k: None
    pika.BlockingConnection = lambda *a, **k: types.SimpleNamespace(
        channel=lambda: CHANNEL)

    test_mute_window()
    test_dispatch_policy()
    test_second_gate_check()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
