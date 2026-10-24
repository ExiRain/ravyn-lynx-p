# Ravyn-Lynx PC — Orchestrator

## What Ravyn is

A stream mascot with a voice and a face. She is not a co-host and not an
assistant; she is the thing on screen that reacts, and her jobs are in this
order:

1. **Alerts and paid messages.** Read a donation over $2 out loud, thank subs,
   follows, raids and bits — and eventually ask people to follow or subscribe.
   This is her reason to exist, not a feature.
2. **Chat.** Sometimes read a message and answer it.
3. **League co-commentary.** A second voice over the game, under rules and
   gates, never the main event.

Her character is the point of all three: fox spirit, dry, loyal to one person
(the streamer), rude about everyone losing him the game. What she must never be
is repetitive, and what she must never do is read something that should not be
said out loud.

## What this repo is responsible for

**Everything the viewer experiences.** What she reacts to, when she is allowed
to speak, her voice, her face, and every measurement of how she is doing.

The notebook (`ravyn-nb`) is a pure LLM service — it writes her lines and
nothing else. TTS, audio streaming, the avatar and her busy/idle state all live
here, which keeps the notebook's whole 4070 free for the model.

## What works

| | |
|---|---|
| **Dispatch** | priority queue with TTL, one signal in flight, busy watchdog, and she finishes a sentence before yielding the floor to something more important |
| **Hearing him** | VAD gate, Whisper STT per utterance, name gate, and a guard against the decoder reciting its own prompt back |
| **Speaking** | Qwen3-TTS voice cloning (Chatterbox fallback), sentence-by-sentence streaming, WebSocket to Godot with mood and face |
| **League** | Live Client polling, measured game state, per-event angles, the streamer's tone rulebook, themes, champion notes, identity across accounts, the end-of-game cheer and boo |
| **Chat** | Twitch IRC, one message picked per window by score |
| **Idle** | silence filler — improv seeds through the LLM, or quotes straight to TTS |
| **Language** | English and Russian, resolved before generation so the voice can be told too; a person's language sticks |
| **Temper** | supportive / neutral / negative, moved by the session and clamping how hard she is allowed to be |
| **Sanitizing** | viewer names and messages made safe to say out loud, with a blocklist matched against a normalised form |
| **Measurement** | every line logged with what produced it, a three-line summary per game, and a running table across sessions |

Eleven standalone test suites, no pytest and no network: `python tests/test_*.py`.

## What is not built yet

- **The alerts source.** Her first responsibility has no producer. The
  sanitizer, the priorities and the notebook's donor memory are all in place;
  nothing feeds them yet, because the integration depends on where the money
  arrives (Twitch EventSub for bits and subs, something else for donations).
  `sources/mock_events.py` fakes it for testing.
- **Asking for a follow or a sub.** Her third alert responsibility, not yet
  designed.
- **A non-League mode.** `--no-lol` stops the game source, but her persona
  still carries its League section, so she pulls other subjects back to the
  game. Needs an `isLeague` flag that reaches the prompt.
- **One view over both logs.** The PC records what she said and the notebook
  records what the model was asked; they join on `req_id` and nothing reads
  them together.
- **Her Russian character.** She speaks Russian; the persona that makes her
  *her* is English throughout.

## Architecture

```
PC (this repo)                              Notebook (Fedora)
┌───────────────────────────┐              ┌──────────────────────┐
│  Signal Sources           │              │  RabbitMQ             │
│  └─ Silence Filler        │              │                      │
│  └─ Twitch Chat           │ ravyn.request│                      │
│  └─ LoL Game API          ├─────────────►│  Worker → LLM        │
│  └─ Alerts / donations *  │              │         │            │
│  └─ Voice Input (STT)     │ravyn.response│         │            │
│                           │◄─────────────┼─────────┘            │
│  Priority Queue           │              └──────────────────────┘
│  Dispatcher (owns busy)   │
│         │                 │
│         ▼                 │
│  Response Listener        │
│    → TTS (per sentence)   │
│    → Audio Server ────────┼──► WebSocket → Godot
└───────────────────────────┘

* = not built yet — see "What is not built yet" above
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

orchestrator/
  sanitize.py          viewer text made safe to say out loud — names, messages
  temper.py            the slow axis — supportive / neutral / negative
  session_log.py       every dispatched signal + her full reply, as JSONL
  session_metrics.py   what counts as a repeat — shared by the app and the CLI

tools/
  analyze_session.py   repetition, knob attribution and heat, per session
  console_import.py    rebuilds a session from terminal scrollback
  test_hearing.py      mic level + what Whisper made of it, per utterance

data/
  stunts.json          improv seeds for LLM to riff on
  quotes.json          literal lines sent straight to TTS
  blocklist.json       names and words she will never say
  alert_lines.json     what she says instead when one of them cannot be read

logs/                  session-<date>-<time>.jsonl (gitignored)
  history.csv          one row per game, tracked — safe to commit and share
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

## Session log

The terminal prints `sentence[:50]`, so four near-identical roasts read as four
different lines and scroll away regardless. Every run therefore writes
`logs/session-<date>-<time>.jsonl` — one JSON line per dispatched signal, with
the trigger, the angle, the tone, her full reply, what was actually synthesised
and whether any of it was heard.

**You do not have to run anything.** When a game ends she prints the short
version herself, twenty seconds after the API goes away so her last line is
counted rather than cut off:

```
[session] Game over: 22 lines, 5 echoes (23%), 64% hot, longest streak 7
[session]   MyDeath: 5/9 angles used, 3 repeats
[session]   most reused: "games are won by" x6
```

The same three lines print for the whole stream on shutdown, and every one of
them appends a row to `logs/history.csv` — the table you read when you have
not been counting:

```
  when             scope    lines  repeat   hot streak  angles  most reused
  2026-09-21 20:58 game        22     23%   64%      7     5/9  games are won by
  2026-09-25 21:40 game        19     11%   38%      3     7/9  you are going to lose this
```

A row that looks wrong names the log file to open. The full report is there
when you want it:

```powershell
python tools/analyze_session.py                     # newest session
python tools/analyze_session.py --history           # the table above
python tools/analyze_session.py --lines             # the full transcript
python tools/analyze_session.py new.jsonl --compare old.jsonl
python tools/analyze_session.py scrollback.txt      # a pasted terminal log
```

It is standard library only — no RabbitMQ, no notebook, no GPU — and read
only, so it is safe to run mid-stream between games.

The report answers three questions:

| | |
|---|---|
| **repeat rate** | share of her lines that echo an earlier line this session |
| **knobs** | which `config_key` / `angle_id` / tone produced those echoes, and how much of each angle pool the session actually reached |
| **heat** | how many lines were aimed at him, the longest unbroken run of them, and the phrasings she keeps coming back to |

A session that only exists as scrollback can still be read: pass the saved
console output and it is reconstructed, with her lines cut at fifty characters
and every record flagged `truncated`.

`logs/` is gitignored **except `history.csv`**: the table is numbers and her
own phrasing, with no voice transcripts and no viewer names, so it is safe in
a public repo. The session files are not — they carry everything your
microphone heard and every chat message, by name.

Off with `SESSION_LOG_ENABLED = False`. `SESSION_LOG_FULL_CONTEXT = True` also
keeps the SITUATION block and the angle instruction verbatim, for when one
specific line needs explaining.

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