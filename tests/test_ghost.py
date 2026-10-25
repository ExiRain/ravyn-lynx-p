"""
Invisible until she speaks.

    python tests/test_ghost.py

`--ghost` is for a stream where the screen is not a game anyone is reading: she
fades in to say something and fades out again, so she is never sitting on top
of something that matters. It changes her avatar and nothing else about her.

The spec was "0 when silent, 100 when making sound". Taken literally — alpha
driven from the audio amplitude — she strobes, because speech hits zero
between syllables and does so several times a word. So visibility follows the
UTTERANCE: `SHOW:100:200` before START, `SHOW:0:400` after END, and MOUTH
keeps carrying the per-chunk detail it always did.

Off by default, and nothing is sent when it is off — a Godot build that has
never heard of SHOW behaves exactly as it does today.
"""

import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The audio server reaches for numpy and FastAPI at import time, and neither
# is involved in anything tested here: visibility is two text messages around
# an utterance. Stubbed rather than installed, the same way the other suites
# stub pika and requests, so this stays runnable with no dependencies.
class _FakeArray:
    """Just enough array for the envelope maths: a length and a size."""

    def __init__(self, values):
        self._values = list(values)

    size = property(lambda self: len(self._values))

    def __len__(self):
        return len(self._values)

    def __getitem__(self, item):
        result = self._values[item]
        return _FakeArray(result) if isinstance(item, slice) else result

    def astype(self, _dtype):
        return self

    def __pow__(self, _n):
        return self


_np = types.ModuleType("numpy")
_np.frombuffer = lambda buf, dtype=None: _FakeArray(
    [1] * (len(buf) // 2) if buf else [])
_np.abs = lambda x: x
_np.max = lambda x, **k: 0.0
_np.mean = lambda x, **k: 1.0
_np.sqrt = lambda x: 1.0
_np.int16 = "int16"
_np.float32 = "float32"
sys.modules.setdefault("numpy", _np)

_fastapi = types.ModuleType("fastapi")


class _App:
    """Enough FastAPI for the decorators at import time to be no-ops."""

    def websocket(self, *a, **k):
        return lambda fn: fn

    def on_event(self, *a, **k):
        return lambda fn: fn

    def get(self, *a, **k):
        return lambda fn: fn

    def post(self, *a, **k):
        return lambda fn: fn


_fastapi.FastAPI = _App
_fastapi.WebSocket = type("WebSocket", (), {})
_fastapi.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
_fastapi.Body = lambda *a, **k: None   # only used as a default-value marker
sys.modules.setdefault("fastapi", _fastapi)

_fastapi_responses = types.ModuleType("fastapi.responses")


class _JSONResponse:
    def __init__(self, content=None, status_code=200):
        self.content = content
        self.status_code = status_code


_fastapi_responses.JSONResponse = _JSONResponse
sys.modules.setdefault("fastapi.responses", _fastapi_responses)

from app.settings import Settings, get_settings                   # noqa: E402
from services import audio_server                                 # noqa: E402

S = get_settings()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeGodot:
    """Captures everything the server sends, in order."""

    def __init__(self):
        self.sent: list = []

    async def send_text(self, msg):
        self.sent.append(msg)

    async def send_bytes(self, data):
        self.sent.append(f"<{len(data)} bytes>")


LINGER = 0.05      # GHOST_LINGER_S for these tests, so they stay fast


def fresh_ghost_state() -> None:
    audio_server._visible = False
    audio_server._fade_task = None


def godot_sees(ghost: bool, script) -> list:
    """Run `script` (an async callable) and return what Godot was sent."""
    Settings.GHOST_MODE = ghost
    saved_linger = Settings.GHOST_LINGER_S
    Settings.GHOST_LINGER_S = LINGER
    fresh_ghost_state()
    client = FakeGodot()
    audio_server.clients.clear()
    audio_server.clients.add(client)
    try:
        asyncio.run(script())
    finally:
        audio_server.clients.discard(client)
        Settings.GHOST_MODE = False
        Settings.GHOST_LINGER_S = saved_linger
        fresh_ghost_state()
    return client.sent


async def _line() -> None:
    # The response listener's order: fade_out comes after its playback wait,
    # which tests/test_voice_gate.py times; here only the messages matter.
    await audio_server.begin_utterance(mood=0.2, tired=0.1)
    await audio_server.end_utterance()
    await audio_server.fade_out()


async def _run() -> None:
    await _line()
    await asyncio.sleep(LINGER * 3)     # let the scheduled fade out fire


def utterance(ghost: bool) -> list:
    """One line with ghost mode on or off, and what Godot saw."""
    return godot_sees(ghost, _run)


# ===================================================================== on/off
def test_off_by_default():
    print("\n--- off unless asked for ---")
    check("the setting is off by default", S.GHOST_MODE is False)

    sent = utterance(ghost=False)
    check("nothing about visibility is sent",
          not any(m.startswith("SHOW") for m in sent), str(sent))
    check("and the protocol is otherwise untouched",
          sent == ["MOOD:0.2", "TIRED:0.1", "START", "END"], str(sent))


def test_she_fades_in_and_out():
    print("\n--- in to speak, out when done ---")
    sent = utterance(ghost=True)
    shows = [m for m in sent if m.startswith("SHOW")]

    check("exactly two visibility messages", len(shows) == 2, str(shows))
    check("in before she speaks",
          shows[0] == f"SHOW:100:{S.GHOST_FADE_IN_MS}", shows[0])
    check("out after she stops",
          shows[1] == f"SHOW:0:{S.GHOST_FADE_OUT_MS}", shows[1])

    check("the fade in runs BEFORE START, so she is not appearing mid-word",
          sent.index(shows[0]) < sent.index("START"), str(sent))
    check("and the fade out AFTER END, so she does not vanish on the last "
          "syllable",
          sent.index(shows[1]) > sent.index("END"), str(sent))

    check("she lingers longer than she arrives",
          S.GHOST_FADE_OUT_MS > S.GHOST_FADE_IN_MS,
          f"{S.GHOST_FADE_IN_MS} in, {S.GHOST_FADE_OUT_MS} out")


def test_she_starts_hidden():
    print("\n--- a connecting Godot is told her state right now ---")
    WSD = sys.modules["fastapi"].WebSocketDisconnect

    class FakeSocket(FakeGodot):
        async def accept(self):
            pass

        async def receive_text(self):
            raise WSD()

    def connect(ghost: bool, visible: bool = False) -> list:
        Settings.GHOST_MODE = ghost
        audio_server._visible = visible
        sock = FakeSocket()
        try:
            asyncio.run(audio_server.websocket_endpoint(sock))
        finally:
            Settings.GHOST_MODE = False
            fresh_ghost_state()
        return sock.sent

    check("ghost mode hides her instantly on connect",
          connect(True) == ["SHOW:0:0"], str(connect(True)))
    check("but a reconnect mid-line shows her, instead of blanking her "
          "while she talks",
          connect(True, visible=True) == ["SHOW:100:0"],
          str(connect(True, visible=True)))
    check("and nothing is sent when ghost mode is off",
          connect(False) == [], str(connect(False)))


def test_back_to_back_lines_do_not_flicker():
    print("\n--- a line inside the linger keeps her up ---")

    async def two_lines_close():
        await _line()
        await _line()                      # starts inside the first linger
        await asyncio.sleep(LINGER * 3)

    sent = godot_sees(True, two_lines_close)
    shows = [m for m in sent if m.startswith("SHOW")]
    check("one fade in and one fade out across both lines — no out-and-in",
          shows == [f"SHOW:100:{S.GHOST_FADE_IN_MS}",
                    f"SHOW:0:{S.GHOST_FADE_OUT_MS}"], str(shows))
    check("the fade out comes after the second line's END",
          sent[-2:] == ["END", f"SHOW:0:{S.GHOST_FADE_OUT_MS}"], str(sent))

    async def two_lines_apart():
        await _line()
        await asyncio.sleep(LINGER * 3)    # the first fade out fires
        await _line()
        await asyncio.sleep(LINGER * 3)

    shows = [m for m in godot_sees(True, two_lines_apart)
             if m.startswith("SHOW")]
    check("lines further apart fade out and back in",
          [m.split(":")[1] for m in shows] == ["100", "0", "100", "0"],
          str(shows))

    async def not_yet():
        await _line()                      # finishes before the linger ends

    shows = [m for m in godot_sees(True, not_yet) if m.startswith("SHOW")]
    check("she does not vanish the instant playback ends — she lingers",
          shows == [f"SHOW:100:{S.GHOST_FADE_IN_MS}"], str(shows))


def test_the_sample_rate_is_announced():
    """
    It never was, and Godot assumed 24000 — true only while the TTS happens
    to run there. `TTSEngine.sample_rate` is read from the loaded model, so a
    backend at 22050 or 48000 would have played her back at the wrong pitch
    with nothing in either log to say why.
    """
    print("\n--- the rate the PCM is actually at ---")
    client = FakeGodot()
    audio_server.clients.clear()
    audio_server.clients.add(client)

    header = b"\x00" * audio_server.WAV_HEADER_SIZE
    body = b"\x01\x00" * 2400

    try:
        asyncio.run(audio_server.push_sentence(header + body, is_first=True,
                                               sample_rate=22050))
        first = list(client.sent)
        client.sent.clear()
        asyncio.run(audio_server.push_sentence(header + body, is_first=False,
                                               sample_rate=22050))
        later = list(client.sent)
    finally:
        audio_server.clients.discard(client)

    check("the first sentence says the rate", "RATE:22050" in first,
          str(first[:3]))
    check("before any audio",
          first.index("RATE:22050") < next(i for i, m in enumerate(first)
                                           if m.startswith("<")),
          str(first[:3]))
    check("and only once per utterance, not per sentence",
          not any(m.startswith("RATE") for m in later), str(later[:3]))


def test_the_message_shape():
    print("\n--- SHOW:percent:fade_ms ---")
    client = FakeGodot()
    audio_server.clients.clear()
    audio_server.clients.add(client)
    try:
        asyncio.run(audio_server.set_visibility(55, 1000))
        asyncio.run(audio_server.set_visibility(0.0, 250.7))
    finally:
        audio_server.clients.discard(client)

    check("percent and fade travel together",
          client.sent[0] == "SHOW:55:1000", client.sent[0])
    check("and both are whole numbers Godot can parse",
          client.sent[1] == "SHOW:0:250", client.sent[1])


def test_amplitude_still_drives_the_mouth():
    print("\n--- the amplitude detail is not what moves her alpha ---")
    source = (Path(__file__).resolve().parent.parent
              / "services" / "audio_server.py").read_text(encoding="utf-8")

    # The thing this test exists to prevent: somebody "improving" ghost mode
    # by driving SHOW from the envelope, which is where the strobing is.
    envelope_block = source.split("async def push_sentence")[1]
    check("push_sentence sends MOUTH", "MOUTH:" in envelope_block)
    check("and never SHOW — per-chunk visibility is the strobe",
          "SHOW" not in envelope_block.split("async def end_utterance")[0])


def test_it_is_only_about_her_avatar():
    print("\n--- and it changes nothing else ---")
    import subprocess
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "import re;"
         "src = open('sources/promo.py').read()"
         " + open('sources/stream_elements.py').read()"
         " + open('orchestrator/dispatcher.py').read();"
         "print('GHOST' in src)"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent))
    check("no source, dispatcher or promo rule reads the ghost flag",
          out.stdout.strip() == "False", out.stdout.strip())

    check("league mode and ghost mode are independent settings",
          S.LEAGUE_MODE is False and S.GHOST_MODE is False)


def main() -> int:
    test_off_by_default()
    test_she_fades_in_and_out()
    test_she_starts_hidden()
    test_back_to_back_lines_do_not_flicker()
    test_the_sample_rate_is_announced()
    test_the_message_shape()
    test_amplitude_still_drives_the_mouth()
    test_it_is_only_about_her_avatar()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
