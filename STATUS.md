# Ravyn — project state

Where the project is, why it is shaped this way, and what is next.
Read this first after a break; it holds the reasoning that is not in the code.

Companion file: `ravyn-nb/STATUS.md` (the notebook side).

---

## 1. Decisions, and why

| Decision | Reasoning |
|---|---|
| **TTS on the PC, permanently** | She runs standalone and in Discord, not just with League. The PC is idle in those modes, and the notebook's 8GB 4070 can only really hold the LLM. Correct in every mode, so it is settled. |
| **Notebook is LLM-only** | It writes her lines and nothing else. Nothing there loads a speech model or talks to Godot. |
| **Qwen3-TTS 1.7B** | Native Russian, Apache 2.0, 3-second cloning. |
| **`faster-qwen3-tts` is mandatory** | The official package runs the 1.7B at RTF ~1.3 — no faster than the Chatterbox it replaced. On a 4090 the same model reaches ~4.85x with CUDA graphs and a static KV cache. At batch size 1 the bottleneck is kernel launch overhead, not compute, which is also why 1.7B costs almost nothing over 0.6B. |
| **Chatterbox kept as fallback** | English only, and pinned to torch 2.6 whose CUDA kernels stop at sm_90. The 5080 is Blackwell (sm_120), so it runs *only* because setup overrides that pin. `TTS_BACKEND = "chatterbox"` reverts in one word. |
| **English ambient, RU on addressed replies** | Her own idle voice never flips language; a reply follows whoever spoke. See §5. |
| **STT will run on CPU** | int8, zero VRAM. openWakeWord gates it so Whisper fires a few times a minute, not continuously. |

### Hardware

| | GPU | Budget |
|---|---|---|
| PC (Windows) | RTX 5080, 16GB | TTS ~6GB, shared with League + OBS + Godot |
| Notebook (Fedora) | RTX 4070, **8188MiB, ~8.1GB free** | LLM only |

`nvidia-smi` showed 13MiB used at idle — earlier planning assumed 6.9GB and was too conservative.

### PyTorch on the 5080 — do not re-derive this

`chatterbox-tts` pins `torch==2.6.0`, whose wheels carry CUDA kernels only to sm_90. Blackwell is sm_120: satisfying that pin gives "no kernel image is available for execution on the device". sm_120 needs **torch 2.7+ from the cu128 index**, which necessarily violates the pin.

`setup_venv.ps1` installs requirements **first**, then force-reinstalls cu128 over the top. The reverse order lets chatterbox's pin silently downgrade torch back to CPU 2.6.0.

**Never run `pip install -r requirements.txt` alone afterwards** — it re-breaks CUDA.

---

## 2. What lives where

| Concern | Machine | File |
|---|---|---|
| What she reacts to, priority, TTL | PC | `orchestrator/`, `sources/` |
| Busy/idle state | PC | `dispatcher.py` + `services/response_listener.py` |
| Voice gate (VAD) | PC | `sources/voice_gate.py` |
| Language resolution | PC | `orchestrator/language.py` |
| Writing her lines | Notebook | `adapters/mq/rabbitmq.py` → llama-server |
| Persona, memory, output filters | Notebook | `persona/`, `adapters/mq/rabbitmq.py` |
| Her voice | PC | `services/tts_engine.py` |
| Audio + lip sync to Godot | PC | `services/audio_server.py` |

```
PC                                    Notebook
sources → queue → dispatcher ──ravyn.request──→ worker → LLM
                      ↑                                    │
              voice gate (VAD)         ←──ravyn.response───┘
                      ↓
        response_listener → TTS → audio_server → WebSocket → Godot
```

The notebook publishes **exactly one** `ravyn.response` per request, including on
empty output and failures. The PC clears its busy flag on that reply, so a
dropped one stalls the dispatcher until the 90s watchdog fires.

---

## 3. Running it

**Notebook first** (hosts RabbitMQ and the LLM):

```bash
cd ~/ravyn-lynx
./scripts/start_stack.sh            # tmux: LLM | WORKER | RABBIT | MONITOR
./scripts/start_llm.sh              # Q5_K_M official, 4096 ctx (default)
./scripts/start_llm.sh q4           # Q4_K_M official, 8192 ctx
./scripts/start_llm.sh old          # abliterated Q4_K_S, for A/B
```

**PC:**

```powershell
.\scripts\setup_venv.ps1                        # first time — installs cu128 torch
.\scripts\start_client.ps1                      # real Twitch + LoL
.\scripts\start_client.ps1 --test --no-tts      # mocks, no audio
```

| Flag | Effect |
|---|---|
| `--test` | Mock chat/events/game instead of Twitch + LoL |
| `--no-twitch` / `--no-lol` | Skip that source |
| `--no-tts` | Silent mode — logs her lines, loads no model |
| `--no-voice` | Disable the voice gate |

Godot connects to `ws://localhost:9000/ws/audio` — **not** the notebook.

`--test` cannot exercise quote mode: mock sources keep resetting the silence
timer. To test it, lower `SILENCE_THRESHOLD` and run `--no-twitch --no-lol`.

---

## 4. Built so far

**PC** (branch `claude/ai-assistant-tts-options-7so8zi`, [PR #1](https://github.com/ExiRain/ravyn-lynx-p/pull/1))

| Commit | What |
|---|---|
| `804e1d9` | PC owns busy state; sentence streaming, PHONEME and envelope reset restored |
| `5145742` | PowerShell arg splatting so flags reach `app.main` |
| `ba4b99e` | Language resolver |
| `b035530` `dcce436` | cu128 torch in setup, correct install order |
| `69ad954` | Qwen3-TTS backend, warmup, first-chunk splitting |
| `6cfa278` | Champion names instead of summoner names |
| `7124ebd` | `REACTION_CHANCE` per event; identity diagnostics |
| `c469dd8` | Voice gate |

**Notebook** — `672f59f` LLM-only · `b9ece9a` narration filter · `dd61311`
`start_llm.sh` owns model choice · `4f7c9f1` game identity + tch rationing ·
`07534e5` tch variants · `c27d4aa` narration log accuracy

**Both must merge together.** Merging the PC alone brings back double-voice and
silent quote-mode.

### Bugs found and fixed, worth not reintroducing

- Notebook and PC both spoke → she said everything twice
- `skip_llm` quotes never reached the PC (publish was inside the `else:`)
- IDLE fired before the PC had synthesised → signals dispatched over her voice
- Mood/face pushed to the notebook's WebSocket, which Godot no longer uses
- Sentence streaming lost in the port to PC; PHONEME dropped entirely
- Lip sync envelope never reset — a loud line capped the next quiet one at 0.38 vs 1.00
- Sample rate hardcoded; now read from the model (24000, confirmed)
- `requirements.txt` had `kokoro soundfile` on one line — `pip install -r` failed outright
- **tch took three attempts**: the dismissive template *asked* for it, the prompt banned it, and the filter only stripped position 0. Then `\btch\b` missed "tchk" — no word boundary before the k. Now a rate limit (`TCH_COOLDOWN = 25`) matching every spelling.

### Tests

Eleven suites in the scratchpad (not committed — worth moving into the repos).
They stub TTS, CUDA, RabbitMQ and Godot, so they verify logic, not reality.

---

## 5. Language

Resolved once in the dispatcher immediately before publishing, so no source can
forget. Split on whether anyone actually spoke to her:

- **Ambient** — `silence_filler`, `promotion`, `game`. No addresser, so nothing to
  mirror. Always `LANG_AMBIENT`. This is what stops her idle voice flipping.
- **Addressed** — `chat`, `voice`. Follows `LANG_REPLY`.

| `LANG_REPLY` | Behaviour |
|---|---|
| `en` / `ru` | Forced. **`ru` is the Russian test harness.** |
| `multilang` | The LLM mirrors whoever wrote to her |
| `detect` | Cyrillic ratio on the message, decided *before* generating |

`detect` ages better than `multilang`: it resolves before the LLM runs, so the
TTS can be told too. Threshold is **0.3**, deliberately low — the question is
"who is this person", not "what language is this string". Russian chatters mix
Latin slang constantly and Twitch emotes are Latin words.

Precedence: `Signal.lang` → `SPEAKER_LANG` → ambient → `LANG_REPLY`.

**Still untested:** whether the LLM can carry her in Russian at all. Set
`LANG_REPLY = "ru"`, send chat, listen. Ten minutes, and it gates everything RU.

Her persona is written in English — banned openers, "fufu", the teammate
vocabulary. None of it survives translation, so Russian currently loses those
voice rules until a Russian addendum exists. **That addendum is your writing.**

---

## 6. Voice gate

Silero VAD decides when she may *start*. She is never interrupted mid-line.

- While you talk, ordinary signals wait
- `VOICE_HOLD_AFTER_SPEECH` (5s) of quiet after your last word
- Priority ≤ `VOICE_INTERRUPT_PRIORITY` (2) cuts through — subs, follows, donations

Held signals are checked with `peek()`, not popped, so they keep ageing: a game
reaction that waits out its TTL expires rather than arriving late.

Hysteresis, not a bare threshold: ~96ms to believe speech started, ~480ms to
believe it stopped, so the pause between two words is not read as you finishing.

The gate ignores the mic while she speaks — otherwise her voice returns through
the speakers, reads as you, and holds her off indefinitely.

---

## 7. Character and reactions — the plan

### The governing principle

An Opus 4.8 test got interesting League matchups **wrong**. Nothing running
locally will do better. So:

> **She may only assert things you told her, or things the API measured.
> Never anything she would have to know about League.**

| Claim | Source | Safe |
|---|---|---|
| "Jungle is his worst role" | you told her | ✅ |
| "Played Riven 200 times, never wins" | you told her | ✅ |
| "You're 40 CS down" | API measured | ✅ |
| "This matchup is unplayable" | she'd have to know | ❌ |
| "Their comp will lock you down" | she'd have to know | ❌ |

### Observe, don't predict

The comp-theme idea is prediction, and prediction needs knowledge nobody has.
But the API is a live feed of ground truth every 2 seconds, and observation
needs no knowledge at all:

> *"Forty CS down. On the champion you've played two hundred times."*
> *"Zero deaths, zero kills, twelve minutes. Are you playing or watching?"*
> *"Your jungler has more CS than you."*

Always correct, funnier than a matchup take, and it scales to every champion
without a single line of champion data — which was the original worry.

### Attributes, not combinations

5 roles × ~170 champions is 850 combinations. Do not enumerate them. Enumerate
*attributes* and let the LLM combine:

```yaml
roles:
  jungle:  { skill: worst, read: "not even trying to win" }
  top:     { skill: best,  read: "comfort zone, splitpush into oblivion" }
  support: { skill: n/a,   read: "passing time, zero effort" }
champions:
  Riven:   { history: "plays constantly, never wins", offmeta_in: [jungle, adc, support] }
```

Five role entries plus however many champions you feel like tagging. Untagged
champions fall back to role-only commentary. **The file is never finished and
never needs to be.**

### Identity — multi-account and RU server

Several accounts including the RU server, so events carry names she does not
recognise. Confirmed live: `Your creatures on team болтяра died`.

Known names to match (keep editable, expect typos):
`Серый Экран`, `Exiled Rain`, `Amsterdam Ghost`, `Rigid Body`, `Stazara`

`activePlayer` self-identifies, so the list is for matching **event** names
where formats differ. Matching by **champion** is more stable — always Latin,
never renamed.

If `_is_me()` fails, his own kills and deaths route as *ally* events — which
looks exactly like "she talks about me in third person and reacts to
everything". `7124ebd` logs identity resolution and the first kill event's raw
names so this is visible instead of guessed.

### Role detection

The `position` field is unreliable — frequently empty. Summoner spells only
distinguish jungle (Ignite goes on top/mid/adc/support alike).

**2026 gave all five roles a quest**, seven items across them — jungle pets,
World Atlas → Runic Compass for support, and quest items for top/mid/adc. Since
`items[]` is in `allPlayers`, **role becomes readable from inventory for every
role**.

**Do not hardcode item names from memory — that is the exact failure mode this
section exists to avoid.** Capture ground truth:

```powershell
curl.exe -k https://127.0.0.1:2999/liveclientdata/allgamedata > game.json
```

One mid-game capture gives the real item IDs on all ten players. It also
self-documents when a patch changes things.

### What the API can and cannot see

| Available | Not available |
|---|---|
| `items[]`, `position`, `level`, `team` | **champion coordinates — none, anywhere** |
| `scores`: kills/deaths/assists/**creepScore**/wardScore | dives, rotations, whether you were warded |
| `ChampionKill`: Killer, Victim, **Assisters[]** | |
| Your **full** runes; everyone else's keystone + trees | others' minor runes and shards |

Derivable: items vs items, lane matchup, CS differential, solo kill vs teamfight
(`len(Assisters)`), gank *inferred* (enemy jungler on a lane target).

### Why she felt repetitive

The quote pools are fine — **23 of 24 fire**. The bottleneck was that five event
types (DragonKill, HeraldKill, TurretKilled, AllyKill, AllyDeath — the most
frequent in any game) all collapsed into one "be dismissive" instruction. The
seeds varied; the instruction did not.

Real variation needs more *distinct situations*, not more lines per situation —
which is the same work as the observation list above.

Loose ends: `MyAssist` is routed but never emitted; `teammates.ally_death_multiple`
is written but never used.

### Champ select

The Live Client API does not exist during champ select — that is the LCU API
(random port, lockfile auth in the League install dir, `/lol-champ-select/v1/session`).

**Game start is the better target**: same API already being polled, zero new
integration, and all ten champions are visible. You lose reacting to the pick as
it happens and gain not building a second client.

### Build order

1. **Name list** — small, fixes a live bug
2. **Capture `game.json`** — 30 seconds, unblocks everything below
3. **Role detection from quest items** + game-start comment, role guidelines only
4. **Observational commentary** — CS, gold, deaths, item timings. The big win, no champion data
5. **Per-champion history lines** for the five or six he plays — flavour, added lazily
6. **Comp counting** — last, optional. Tag `heavy_cc` / `hard_engage` yourself so
   "five of them can stop you moving" is arithmetic on *your* data, never her opinion

Keep champion data **out of** `game_quotes.json`. Quotes are what she says;
champion tags are facts about the game. Different lifecycles.

---

## 8. Open

**Untested**
- Russian output quality from the LLM — gates the whole RU plan
- Official Qwen3.5-9B vs the abliterated build, A/B by ear
- Whether narration recurs on the official model (watch `Stripped narration ->`)

**Not built**
- Wake word + STT so she can *hear* you (the gate is the prerequisite, and it exists)
- Everything in §7
- `ravyn-nb` has no PR

**Small**
- Move the eleven test suites out of the scratchpad into the repos
- Stray submodule in `ravyn-nb` (gitlink at `ravyn-nb/`, no `.gitmodules`)
- `quote` signals round-trip to the notebook just to be handed back — they could
  short-circuit locally, which would let her speak with the notebook powered off
- Qwen `Base` cloning has no `exaggeration` equivalent, so mood no longer
  modulates her *voice*; it still drives her face
- `[voice] Stream status: input overflow` under heavy CPU load — benign at
  startup, worth buffering if it recurs mid-stream
