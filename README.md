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
| `BUSY_TIMEOUT` | 90s | Watchdog — force idle if no response comes back |

## Requirements

- Python 3.11+
- RabbitMQ running on the notebook
- espeak-ng on PATH for `PHONEME` mouth shapes (optional — without it Godot
  still gets `MOUTH` amplitude, so lips move but shapes are flat)