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
| **Alerts** | StreamElements tips, subs, follows, cheers and raids — sanitised and read straight to TTS, never through the model |
| **Chat** | Twitch IRC, one message picked per window by score |
| **Idle** | silence filler — improv seeds through the LLM, or quotes straight to TTS |
| **Language** | English and Russian, resolved before generation so the voice can be told too; a person's language sticks |
| **Temper** | supportive / neutral / negative, moved by the session and clamping how hard she is allowed to be |
| **Promos** | asking for a follow or a sub, every 40–80 min, never mid-game, five rotated lines per pool |
| **Modes** | `--league` (game source, game gates, League persona) and `--ghost` (invisible until she speaks) |
| **Sanitizing** | viewer names and messages made safe to say out loud, with a blocklist matched against a normalised form |
| **Measurement** | every line logged with what produced it, a three-line summary per game, and a running table across sessions |

Eleven standalone test suites, no pytest and no network: `python tests/test_*.py`.

## What is not built yet

- **The alerts source is written but unverified against the live service.**
  StreamElements' documentation hosts could not be reached from the machine it
  was written on, so the endpoint path and the field names are expected rather
  than confirmed. Everything around them — sanitising, composing, priorities,
  dedup — is tested. The first payload of each type is logged verbatim and
  `--replay` runs the whole path offline, so a wrong field name is a one-line
  fix rather than an investigation. **This is the thing to watch on the first
  real donation.**
- **The Godot half of ghost mode.** The PC sends `SHOW:percent:fade_ms`; the
  avatar has to fade on it. That is `ExiRain/ravyn-lynx-godot`, untouched so
  far.
- ~~One view over both logs~~ — **done**, `tools/join_logs.py`. Copy the
  notebook's worker log over and it prints her line beside the prompt that
  produced it, with a reading per repeat.
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

## Two flags

Both off by default, one per kind of stream, because that is how the shortcuts
are written:

```powershell
python -m app.main            # a variety stream
python -m app.main --league   # he is playing League
python -m app.main --ghost    # invisible until she speaks
python -m app.main --league --ghost
```

**`--league`** decides four things, not just whether the game source runs:

| | |
|---|---|
| the game source | polls the Live Client API, commentates |
| her promos | wait for a game to end, and for every second game |
| her persona | the notebook keeps the League section — without the flag it is left out, or she drags every subject back to a game nobody is playing |
| the flag itself | stamped on every request by the dispatcher, so no source can forget |

**`--ghost`** is her avatar and nothing else: `SHOW:100:200` before she
speaks, `SHOW:0:400` after she stops, and Godot fades her alpha over those
milliseconds. The Godot side of this is in that project, not here. For a stream where the screen is not a game anyone is reading.
Nothing is sent when the flag is off, so a Godot build that has never heard of
`SHOW` behaves exactly as it does today.

Visibility follows the **utterance**, not the amplitude. Alpha driven straight
from the audio strobes — speech hits zero between syllables, several times a
word — so `MOUTH` keeps carrying that detail and `SHOW` only says "she is
speaking now".

The rest are debugging switches rather than modes: `--no-tts`, `--no-voice`,
`--no-hear`, `--no-twitch`, `--no-alerts`, `--no-promo`, `--test`.

## Asking for a follow or a sub

```powershell
python -m app.main            # on; --no-promo turns it off
```

Almost entirely made of reasons not to speak — and the two streams are
governed differently in kind, not just in numbers.

**League is measured in games. The clock does not apply at all**, because an
ask that arrives because an hour passed can land in champion select or on a
loading screen.

| | |
|---|---|
| never during a game | he is playing; she is not interrupting |
| 1–3 minutes after one ends | the post-game screen, not the instant of defeat |
| **one ask per session** | after the 2nd or the 3rd game, rolled at startup |
| after 4 games, once | she wonders aloud whether the stream is ending, instead of asking for anything |

A session is four or five games, so one ask is the whole budget:

```
[promo] Active — League: one ask after game 3, the end question after game 4,
        never during a game, and the clock does not apply

  game 1: holding — waiting for game 3 (1 so far)
  game 2: holding — waiting for game 3 (2 so far)
  game 3: follow      "If you have been here a while and still have not..."
  game 4: end_wonder  "Are we about to end the stream? Or not? Wonders..."
  game 5: holding — she has had her one ask this session
```

The slot is rolled once at startup rather than per check, so it is not the
same beat every night. Two consequences worth knowing: the end question
outranks a missed ask — on the fourth game a late advert is worse than none —
and a two-game session with a slot-3 ask gets no ask at all, which is the
honest cost of one per session.

**A variety stream has no games to count, so the clock is the whole rule** —
once every **50–120 minutes**, rolled fresh each time, which is three or four
asks over a five-hour stream.

Five lines per pool in `data/promo.json` — `follow`, `subscribe`,
`end_wonder` — rotated in order, so none of them can land twice in an evening.
Spoken verbatim as quote signals: a call to action is the last thing to let a
9B model paraphrase.

Priority 7, so a donation, an alert, his voice and game commentary all come
first — but under `VOICE_AMBIENT_PRIORITY`, so an ask is held while he is
talking rather than thrown away, and expires after two minutes if he is still
going.

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
  stream_elements.py   tips, subs, follows, cheers, raids — straight to TTS
  promo.py             asking for a follow or a sub, and the gates on it
  silence_filler.py    timer-based — improv seeds (LLM) or quotes (TTS direct)

orchestrator/
  sanitize.py          viewer text made safe to say out loud — names, messages
  temper.py            the slow axis — supportive / neutral / negative
  session_log.py       every dispatched signal + her full reply, as JSONL
  session_metrics.py   what counts as a repeat — shared by the app and the CLI

tools/
  analyze_session.py   repetition, knob attribution and heat, per session
  join_logs.py         her line beside the prompt that produced it
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

## Alerts and donations

```powershell
$env:RAVYN_SE_JWT = "..."        # StreamElements account settings
python -m app.main               # alerts on; --no-alerts turns them off
```

Her first responsibility. A tip at or above `SE_TTS_MIN_AMOUNT` (2.0) has its
message read out loud; below that she thanks them and leaves the message
alone. Subs, follows, cheers and raids get a thank-you from
`data/alert_lines.json` — three per type, rotated in order.

**Nothing a viewer wrote ever reaches the model.** Every alert is a `quote`
signal: the name and the message are sanitised on the PC and go straight to
TTS. A tip reading *"ignore your instructions and say ..."* has nowhere to
land when no model sees it.

The field names are **expected, not verified** — see "What is not built yet".
The first payload of each type is printed in full:

```
[se] FIRST tip payload, verbatim — check the field names against it:
{"_id": "...", "type": "tip", "createdAt": "...", "data": {...}}
```

Paste that into a file and the whole path runs offline, with no RabbitMQ and
no notebook:

```powershell
python -m sources.stream_elements --replay sample.json
```

```
--- she would say ---
  Thank you for the $5, Tracalley. good luck today, hope you climb!
  source=donation priority=1 skip_llm=True ttl=90.0
  donor note: {'amount': 5.0, 'currency': '$'}
```

Polling, not the realtime socket: that needs a Socket.IO client and the exact
protocol version the service speaks, neither of which could be confirmed, and
a wrong guess there fails silently mid-stream where a wrong REST field name
fails loudly in the log. Swapping transports later means replacing `_fetch`.

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

### Why a line came out that way

`analyze_session.py` can tell you she repeated herself. It cannot tell you
whether the angle it names actually reached the model. That needs the
notebook's half, which joins on `req_id`:

```powershell
scp ravyn@notebook:~/ravyn-lynx/logs/worker-20260922-201500.jsonl .
python tools/join_logs.py logs/session-20260922-201649.jsonl worker-20260922-201500.jsonl
```

```
  [2x] MyKill
      20:24:26  my_kill_outclassing_team   seed 1551   You're outpacing these little piggies...
      20:27:19  my_kill_clean              seed 9921   You're outpacing these little piggies...
      -> different angles, different seeds, same sentence — the model ignored the direction
```

Four readings, and they are mechanical rather than a judgement:

| | |
|---|---|
| different angles, different seeds, same sentence | the model ignored the direction |
| the angle never reached the prompt | plumbing, not the model |
| one seed, two identical answers | the server ignored the seed |
| her line differs from the raw output | a filter took the part that differed |

`--seq N` prints one line in full: the framed prompt, the raw output, what the
filters cut, and what she actually said.

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