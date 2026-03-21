# Ravyn-Lynx PC — Orchestrator

Decision engine for Ravyn's stream presence. Runs on the PC, manages all signal sources,
and dispatches work to the notebook AI service over RabbitMQ.

The notebook is a dumb AI service — it runs LLM, TTS, and streams audio to Godot.
All decision-making about what Ravyn says and when lives here.

## Architecture

```
PC (this repo)                          Notebook (Fedora)
┌─────────────────────┐                ┌──────────────────────┐
│  Signal Sources      │                │  RabbitMQ             │
│  └─ Silence Filler   │                │                      │
│  └─ Twitch Chat *    │   ravyn.request│                      │
│  └─ Twitch Events *  ├───────────────►│  Worker → LLM → TTS  │
│  └─ LoL Game API *   │                │         │            │
│  └─ Voice Input *    │   ravyn.status │         ▼            │
│                      │◄───────────────┤  WebSocket → Godot   │
│  Priority Queue      │                │                      │
│  Dispatcher          │                └──────────────────────┘
└─────────────────────┘

* = planned, not yet implemented
```

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
  dispatcher.py        main loop — pulls queue, publishes to rabbit
  status_listener.py   consumes ravyn.status (BUSY/IDLE from notebook)

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
| `ravyn.status` | Notebook → PC | `BUSY` or `IDLE` status updates |
| `ravyn.response` | Notebook → PC | LLM response text (optional) |

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

When `skip_llm` is `true`, the notebook sends `text` directly to TTS without calling the LLM.

## Configuration

All settings are in `app/settings.py`. Key toggles:

| Setting | Default | Purpose |
|---|---|---|
| `SILENCE_THRESHOLD` | 600s | Quiet time before silence filler activates |
| `SILENCE_MIN_INTERVAL` | 120s | Minimum gap between fillers |
| `IMPROV_ENABLED` | True | LLM-powered improvisation on/off |
| `QUOTE_ENABLED` | True | Direct TTS quotes on/off |
| `IMPROV_WEIGHT` | 0.6 | Probability of improv vs quote |

## Requirements

- Python 3.11+
- RabbitMQ running on the notebook
- Notebook worker updated to parse JSON and publish to `ravyn.status`