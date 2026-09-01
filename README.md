# Ravyn-Lynx PC — Orchestrator

Decision engine for Ravyn's stream presence. Runs on the PC, manages all signal sources,
and dispatches work to the notebook AI service over RabbitMQ.

The notebook is a pure LLM service — it writes Ravyn's lines and nothing else.
Everything the viewer experiences (what she reacts to, her voice, her face)
lives here on the PC, which keeps the notebook's whole 4070 free for the model.

## Architecture

```
PC (this repo)                              Notebook (Fedora)
┌───────────────────────────┐              ┌──────────────────────┐
│  Signal Sources           │              │  RabbitMQ             │
│  └─ Silence Filler        │              │                      │
│  └─ Twitch Chat           │ ravyn.request│                      │
│  └─ LoL Game API          ├─────────────►│  Worker → LLM        │
│  └─ Twitch Events *       │              │         │            │
│  └─ Voice Input *         │ravyn.response│         │            │
│                           │◄─────────────┼─────────┘            │
│  Priority Queue           │              └──────────────────────┘
│  Dispatcher (owns busy)   │
│         │                 │
│         ▼                 │
│  Response Listener        │
│    → TTS (per sentence)   │
│    → Audio Server ────────┼──► WebSocket → Godot
└───────────────────────────┘

* = planned, not yet implemented
```

Ravyn is marked busy when the dispatcher publishes a request and idle again
only once her audio has finished playing, so signals never overlap her voice.

## Setup

```powershell
.\scripts\setup_venv.ps1
```

## Run

```powershell
.\scripts\start_client.ps1
```

Or manually:

```powershell
.\venv\Scripts\Activate.ps1
python -m app.main
```

## Project Structure

```
app/
  main.py              entry point — starts all threads and dispatch loop
  settings.py          rabbit connection, orchestrator config, toggles

orchestrator/
  models.py            Signal dataclass — core data model
  priority_queue.py    thread-safe heapq with TTL expiry
  dispatcher.py        main loop — pulls queue, publishes to rabbit, owns busy state

services/
  response_listener.py consumes ravyn.response, drives TTS, clears busy
  tts_engine.py        Chatterbox wrapper — mood maps to exaggeration
  audio_server.py      WebSocket to Godot — audio, MOUTH, PHONEME, mood

sources/
  silence_filler.py    timer-based — improv seeds (LLM) or quotes (TTS direct)

data/
  stunts.json          improv seeds for LLM to riff on
  quotes.json          literal lines sent straight to TTS
```

## RabbitMQ Queues

| Queue | Direction | Purpose |
|---|---|---|
| `ravyn.request` | PC → Notebook | JSON message with prompt + flags |
| `ravyn.response` | Notebook → PC | Ravyn's line, plus mood/tired/source |

The notebook publishes exactly one `ravyn.response` per `ravyn.request`, including
on empty output and failures — the PC clears its busy flag on that message, so a
dropped one would leave the dispatcher stalled until its watchdog fires.

## Message Format

Messages on `ravyn.request` are JSON:

```json
{
  "text": "prompt or literal text",
  "source": "silence_filler",
  "mode": "improv",
  "skip_llm": false,
  "context": {}
}
```

When `skip_llm` is `true`, the notebook passes `text` straight through to
`ravyn.response` without calling the LLM.

Replies on `ravyn.response` are JSON:

```json
{
  "text": "what she says",
  "mood": -0.4,
  "tired": 0.2,
  "source": "game",
  "event_type": "MyDeath",
  "lang": "en"
}
```

## Voice gate

Silero VAD on the mic decides when she is allowed to *start*. She is never
interrupted mid-line — the dispatcher already refuses to send while she is
busy, and her audio always plays out.

- While you are talking, ordinary signals wait
- After your last word, `VOICE_HOLD_AFTER_SPEECH` of quiet before she may speak
- Subs, follows and donations (priority ≤ `VOICE_INTERRUPT_PRIORITY`) cut through

Held signals are checked with `peek()` rather than popped, so they keep their
place and keep ageing — a game reaction that waits out its TTL expires instead
of arriving late and out of context.

Her own voice is muted from the gate while she speaks; otherwise it returns
through the speakers, reads as you, and holds her off indefinitely.

Missing `silero-vad` or `sounddevice` disables the gate with a log line rather
than stopping her. Pick a mic with `VOICE_INPUT_DEVICE`:

```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```

## TTS

Two backends, switched by `TTS_BACKEND`:

| | Languages | Notes |
|---|---|---|
| `qwen` | RU + EN + 8 more | Qwen3-TTS 1.7B, Apache 2.0, clones from a reference wav |
| `chatterbox` | EN only | Fallback. Pinned to torch 2.6, which cannot drive a Blackwell card — it runs only because setup overrides that pin. |

**Qwen needs `TTS_QWEN_REF_TEXT`**: the exact transcript of `TTS_VOICE_REF`, word
for word. Cloning aligns the reference audio against that text, so a wrong or
missing one degrades the voice badly. Startup refuses rather than sounding bad.

**Install `faster-qwen3-tts` or you get no speed benefit.** The official package
runs the reference implementation at roughly realtime (RTF ~1.3); CUDA graphs
plus a static KV cache take the same model to ~4.8x. At batch size 1 this model
is bound by kernel launch overhead, not compute, which is also why 1.7B costs
almost nothing over 0.6B. The engine prefers the fast wrapper and falls back to
the official package with a warning.

Mood and tiredness do not modulate the Qwen voice — `Base` cloning has no
equivalent of Chatterbox's `exaggeration`. Consistent with the project's rule
that emotion comes from what she writes, not from post-processing; the values
still drive her face.

## Language

Resolved once in the dispatcher, immediately before publishing, so no signal
source can forget to set it. The rule splits on whether anyone actually spoke
to her:

- **Ambient** — `silence_filler`, `promotion`, `game`. Nobody addressed her, so
  there is no language to mirror. Always `LANG_AMBIENT`. This is what stops her
  flipping language mid-stream.
- **Addressed** — `chat`, `voice`. Follows `LANG_REPLY`.

`LANG_REPLY` options:

| Value | Behaviour |
|---|---|
| `en` / `ru` | Always that language. `ru` is the way to test her Russian. |
| `multilang` | The LLM mirrors whoever wrote to her |
| `detect` | Decided from the message text *before* generating |

`detect` is the one that will also work for TTS: it resolves the language
before the LLM runs, so the voice can be told too. With `multilang` you only
learn the language from her output, which means detecting on the way out.

Precedence: `Signal.lang` (a source that knows) → `SPEAKER_LANG` → ambient →
`LANG_REPLY`.

Note that her persona is written in English — the banned openers, "fufu", the
teammate vocabulary. None of that survives translation, so Russian output
currently loses those voice rules until a Russian persona addendum exists.

## Configuration

All settings are in `app/settings.py`. Key toggles:

| Setting | Default | Purpose |
|---|---|---|
| `SILENCE_THRESHOLD` | 600s | Quiet time before silence filler activates |
| `SILENCE_MIN_INTERVAL` | 120s | Minimum gap between fillers |
| `IMPROV_ENABLED` | True | LLM-powered improvisation on/off |
| `QUOTE_ENABLED` | True | Direct TTS quotes on/off |
| `IMPROV_WEIGHT` | 0.6 | Probability of improv vs quote |
| `TTS_ENABLED` | True | PC TTS on/off (`--no-tts` for silent mode) |
| `TTS_BACKEND` | `"qwen"` | `qwen` (RU+EN) or `chatterbox` (EN only, fallback) |
| `VOICE_GATE_ENABLED` | True | Hold her back while you talk (`--no-voice` to disable) |
| `VOICE_HOLD_AFTER_SPEECH` | 5.0s | Quiet needed after your last word |
| `VOICE_INTERRUPT_PRIORITY` | 2 | Signals at or below this ignore the gate |
| `REACTION_CHANCE` | dict | Per-event chance she says anything at all |
| `TTS_QWEN_REF_TEXT` | `""` | **Required** — transcript of the voice reference wav |
| `LANG_AMBIENT` | `"en"` | Her idle voice — filler, game, promos |
| `LANG_REPLY` | `"en"` | How she answers someone: `en`/`ru`/`multilang`/`detect` |
| `SPEAKER_LANG` | `{}` | Per-person overrides, e.g. `{"someguy": "ru"}` |
| `BUSY_TIMEOUT` | 90s | Watchdog — force idle if no response comes back |

## Requirements

- Python 3.11+
- RabbitMQ running on the notebook
- espeak-ng on PATH for `PHONEME` mouth shapes (optional — without it Godot
  still gets `MOUTH` amplitude, so lips move but shapes are flat)