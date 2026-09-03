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
| What is true in the game right now | PC | `orchestrator/game_state.py` |
| What Exiled told her about his account | PC | `data/champions.json`, `orchestrator/champion_notes.py` |
| How this reaction differs from the last | PC | `orchestrator/game_angles.py` |
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

- **His chat messages were being thrown away.** Scoring picks one winner per
  batch and discards the rest, so any viewer message that scored higher than
  his silently replaced it
- **An ASCII-only name normaliser dropped his RU account.** `[^a-z0-9]`
  collapses Cyrillic to the empty string
- **A 404 from the Live Client API was logged as an error.** It is the normal
  answer when no game is running — the endpoint only exists inside one — and it
  printed `[lol] API error: 404 Client Error` on every startup
- **Shipped PLACEHOLDER text reached the model.** `data/champions.json` ships as
  a template, and its example strings went down the same path as real notes. She
  opened a game with *"That only when a friend duos comment? It sounds like
  you're just trying to explain away"* — gamely parsing the literal word
  PLACEHOLDER. Template markers are now inert (`champion_notes.is_placeholder`),
  and load logs how many are still waiting to be overwritten
- **Game events were conversation history.** `MAX_HISTORY = 5`, and she repeated
  herself 5-6 times in a row. See §7 "Why she repeated herself"
- **Game accepted from a loading-screen snapshot** → empty identity latched for
  the whole match, all ten champions read as the enemy team, every objective
  counted as his. See §7 "Identity"
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

Two committed suites, both standalone (no pytest, no network):

- `python tests/test_voice_gate.py` — 34 checks: the gate, the mute window, the
  dispatch policy
- `python tests/test_game_variety.py` — 56 checks: measured state, role
  detection, mood, angle variety, the unconditional floor, burst decay
- `python tests/test_champion_notes.py` — 42 checks: lookup, off-role, how
  confidently a lane is claimed, labelling, and that note angles stay silent
  when nothing is written
- `python tests/test_tone_and_theme.py` — 55 checks: the rulebook case by case,
  the ladder refusing consecutive roasts, and that a theme never becomes a
  prefix
- `python tests/test_game_variety.py` also covers the cheer and boo
- `python tests/test_owner.py` — 30 checks: name matching across scripts, that
  his message is never dropped, and that he outranks the queue
- `python tests/test_language.py` — 51 checks: detection, the asymmetric
  confidence rule, per-person stickiness, and unchanged precedence
- `python tests/test_identity.py` — 40 checks: the loading-screen gate, RU
  riotId matching, and that nothing guesses a side it does not know

On the notebook: `python tests/test_game_memory.py` — 14 checks that game events
are kept out of conversation history.

Eleven older suites are still in the scratchpad (not committed — worth moving
into the repos). They stub TTS, CUDA, RabbitMQ and Godot, so they verify logic,
not reality.

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
| `detect` | Cyrillic ratio on the message, decided *before* generating — **now the default** |

### A person's language sticks

Detection reads one message. Most of chat cannot be judged from one message, so
a Russian chatter got Russian for "как дела" and English for the "+" after it.
`SpeakerMemory` remembers the first confident read per name (session only, in
memory) and reuses it when the current message is too thin.

Judging is **asymmetric**, and that is the interesting part:

| Evidence | Rule | Why |
|---|---|---|
| Cyrillic | 2 letters is enough | Nobody types Cyrillic by accident |
| Latin | ≥4 letters **and** ≥2 words | Twitch chat is full of Latin tokens that mean nothing about the writer |

A length threshold cannot separate an emote from speech — `KEKW` is four
letters, "hey man" is six. A **word count** can: an emote is one token, a
sentence is not. Without this, `KEKW`, `LULW`, `Pog`, `monkaS`, `OMEGALUL`,
`gg`, `ez` and `xd` all read as English and would drag Russian chatters toward
English one emote at a time. Caught by a test, not by review.

Detection still beats memory: someone who switches language mid-conversation is
followed, not corrected. Precedence is `Signal.lang` → `SPEAKER_LANG` → ambient
→ detected → remembered → policy.

`detect` ages better than `multilang`: it resolves before the LLM runs, so the
TTS can be told too. Threshold is **0.3**, deliberately low — the question is
"who is this person", not "what language is this string". Russian chatters mix
Latin slang constantly and Twitch emotes are Latin words.

Precedence: `Signal.lang` → `SPEAKER_LANG` → ambient → `LANG_REPLY`.

**Still untested, and now on by default:** whether the LLM can carry her in
Russian at all. `LANG_REPLY = "detect"` means a Russian chatter gets Russian
output the first time one appears — the plumbing is ready, the quality is not
measured. Qwen3-TTS speaks Russian natively so the voice will follow; what is
unknown is the 9B's writing. If it reads badly, `LANG_REPLY = "en"` reverts in
one word.

Her persona is written in English — banned openers, "fufu", the teammate
vocabulary. None of it survives translation, so Russian currently loses those
voice rules until a Russian addendum exists. **That addendum is your writing.**

---

## 6. Voice gate

Silero VAD decides when she may *start*. She is never interrupted mid-line.

- While you talk, ordinary signals wait
- `VOICE_HOLD_AFTER_SPEECH` (5s) of quiet after your last word
- Priority ≤ `VOICE_INTERRUPT_PRIORITY` (2) cuts through — subs, follows, donations

Hysteresis, not a bare threshold: ~96ms to believe speech started, ~800ms to
believe it stopped, so the pause between two words is not read as you finishing.

### Why the first version felt wrong

It held at the wrong moment and went deaf at the wrong moment. Two bugs, one
symptom — "the delay doesn't behave like a delay".

**The gate was asked once, at dispatch, and never again.** Between that check
and her first syllable sit an LLM round trip and a TTS pass — 3 to 6 seconds.
Start talking anywhere inside that window and the gate had already said yes.
She spoke straight over you, and the log showed a hold that had plainly done
nothing.

**The mic was deaf for that whole window.** `is_muted` was wired to
`dispatcher.is_busy`, and busy is set the instant a request is published. So
the VAD ignored every frame from publish until playback ended, silent seconds
included. It never saw you start; `_last_speech_at` never updated; when her
line ended the hold was measured against a word from before it and had long
since expired, so the next signal fired immediately — still over you.

### How it works now

**Two checks, and the second one decides.**

| | Where | What it buys |
|---|---|---|
| 1 | `dispatcher._gate_holds`, on the queue head | Not paying for an LLM round trip and a TTS pass for a line she will not be allowed to say. Advisory only. |
| 2 | `response_listener._wait_for_gate`, after the opening chunk is synthesised | The real decision. |

The order in check 2 matters: **synthesise first, then ask.** The audio is in
hand, so waiting is nearly free and she speaks the instant you stop, instead of
starting a cold pipeline and arriving three seconds into your next sentence. A
line waits up to `VOICE_MAX_DEFER` (8s) and is then **dropped**, not said late —
by then the game event is over and the chat message has scrolled. Her staying
quiet reads as her letting it go; her raising it eight seconds later reads as a
bug. Nothing reaches Godot until the check passes, so the avatar never visibly
gears up and then says nothing.

**Muted only while audible.** `VoiceGate.set_muted()` is driven by the response
listener around actual playback, plus `VOICE_MUTE_TAIL` (0.35s) for
speaker-to-mic latency. The mic is live through generation, which is precisely
when you are most likely to start talking. It is wrapped in `try/finally` and
backed by `MUTE_SAFETY_TIMEOUT` (120s) — a leaked mute means a deaf mic for the
rest of the stream, which looks exactly like a broken gate.

**Ambient chatter is dropped, not deferred.** At or above
`VOICE_AMBIENT_PRIORITY` (8) a held signal is discarded at the queue head rather
than queued. `silence_filler` is priority 10: it exists to fill silence, and
while you are talking there is no silence to fill. Delivering it the moment you
stop is the worst outcome — she interrupts the pause after your thought with a
remark about nothing. The filler offers another on its own timer. Belt and
braces, those signals now also carry `SILENCE_SIGNAL_TTL` (60s) for the case
where she was merely busy speaking.

Everything below that line still waits with `peek()`, not `pop()`, so it keeps
ageing: a game reaction that waits out its TTL expires rather than arriving
late.

`FRAMES_TO_STOP` went 15 → 25 (~480ms → ~800ms). 480ms cleared on ordinary
pauses between phrases, so one sentence logged "you are talking / you stopped"
three or four times — visible in the screenshots — and the hold kept re-arming
from the middle of your thought. It also lengthens the effective hold by its own
duration, since the stop edge is what stamps `_last_speech_at`.

**Tune by ear, in this order:** `VOICE_HOLD_AFTER_SPEECH` if she cuts into your
pauses; `FRAMES_TO_STOP` if the log flip-flops mid-sentence; `VOICE_MAX_DEFER`
if she drops lines you wanted; `VOICE_AMBIENT_PRIORITY` if the wrong things are
being discarded.

`python tests/test_voice_gate.py` covers all of it with Silero, Rabbit, TTS and
Godot stubbed — it verifies decisions, not audio.

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

### Attributes, not combinations — `data/champions.json`

5 roles × ~170 champions is 850 combinations. Do not enumerate them. Enumerate
*attributes* and let the LLM combine. **Built** — `data/champions.json`, read by
`orchestrator/champion_notes.py`:

```json
"roles":     { "top": { "skill": "best", "read": "where I know what I'm doing" } },
"champions": { "Riven": { "main_role": "top",
                          "history":   "I play her constantly and still lose",
                          "offrole_read": "still learning her anywhere but top",
                          "matchups": { "Garen": "I never win this lane" } } }
```

Five role entries plus however many champions you feel like tagging. Untagged
champions fall back to role-only commentary; an unknown role falls back to
champion-only; a missing or malformed file disables the lines and nothing else.
**The file is never finished and never needs to be.**

**Write it in your voice, as claims about yourself.** "I never win this lane" is
yours to say; "Riven loses to Garen" is a claim about the game and does not
belong there. It reaches the prompt under its own heading — *"his words about
his own account, not facts the game gave you"* — kept separate from the measured
SITUATION block so she can never launder your opinion into something the game
told her. Without that label the situation block's "do not state anything beyond
these" would silently forbid these lines too.

The shipped file is **all placeholders**, marked as such. Overwrite them.

Champion keys match loosely — case, spaces and punctuation are ignored, so
`Lee Sin`, `leesin` and `LeeSin` are one key. Wukong is `MonkeyKing` in the API;
either spelling works.

**How confidently she claims a lane.** Enemy roles are not detectable yet, so a
matchup note is framed three ways:

| Framing | When |
|---|---|
| *"On laning against Garen"* | Both roles measured and equal, **or** you filed the note under a champion whose `main_role` is the role he is playing — writing Garen under Riven-top is *your* assertion that this is a top matchup, and §7 permits anything you told her |
| *"On Garen, who is on the enemy team"* | The champion is in the game but nothing establishes the lane. Still true, still fires |
| nothing | You wrote no note about anyone on that team |

Five angles read the file: `start_matchup_note`, `start_offrole`,
`start_champion_history`, `start_role_read` at game start, and
`my_death_told_you` when he dies to a champion he warned you about. All are
gated on a note actually existing, so an empty file leaves the generic openers
behaving exactly as before.

### Identity — multi-account and RU server

**`data/identity.json` is the one place he is defined**, loaded by
`orchestrator/identity.py` and shared by chat and the game source. It was three
places: this file, a hardcoded tuple in `twitch_chat` scoring, and another
tuple in the notebook's `context_builder` — the last of which could not be
edited without a deploy.

| List | Used for | Matched |
|---|---|---|
| `names` | League accounts. The active player resolves from the API; this is the fallback for *event* names, whose format differs and which have been seen non-Latin | **Loose** — case, spaces and punctuation ignored, `#TAG` optional |
| `chat_names` | Twitch login, and voice when it lands. **This is what makes her treat a message as coming from him** | **Exact**, case-insensitive only |

**The asymmetry is deliberate.** League event text arrives on his own machine
and nobody else chooses what it says, so forgiving a spacing typo there costs
nothing. A Twitch login is the opposite: it is a claim anyone can register, and
owner standing is not small — her loyal framing, priority over every game event,
and a bypass of the voice gate.

He logs in as **one** name. `exiled` and `exiledr` were in the list and should
not have been; they are handles somebody else could take. Worse, the loose
normaliser stripped punctuation, and **Twitch logins may contain underscores** —
so `exiled_ra1n` and `exiledra1n_` both resolved to him, and either is
registerable. Chat matching is exact now. Caught by a test.

Mods are deliberately not modelled. If they ever get standing it should be a
third list with its own framing — "trusted" and "is the streamer" are different
things.

**It also has to be Unicode-aware, and was not.** The first normaliser used
`[^a-z0-9]`, which collapses `Серый Экран` to the empty string — so his RU
account was never in the set at all. The startup line read *"4 known account
name(s)"* for a five-name file, which is exactly the sort of off-by-one nobody
reads. `str.isalnum()` now, which knows about other scripts.

### When it is him talking

He does not compete with chat. Scoring is a contest with **one winner per batch
and the losers discarded**, not delayed: a viewer's *"hey ravyn, what do you
think?"* scores 20, his *"gg"* scored 7 even with the owner bonus, so his
message was silently dropped. He now skips the contest and the batch window
entirely and goes straight to the queue at `OWNER_PRIORITY` (2), which beats
every game event and all ordinary chat.

The signal carries `is_owner: True`, and the notebook keys her "this is your
person" framing off **that flag** rather than pattern-matching his name. The old
name check survives there only as a fallback for a client that sends no flag.

**One side effect worth knowing:** at priority 2 he also clears
`VOICE_INTERRUPT_PRIORITY`, so she answers him inside the post-speech hold. That
is the intent — he typed at her deliberately — but if he types and then
immediately starts talking, she will speak over him. `OWNER_PRIORITY = 3` keeps
the hold and still beats ordinary chat.

Voice will need nothing new: set `context["user"]` and `context["is_owner"]`
exactly as chat does, and it gets the same framing, the same priority and the
same per-person memory buffer. `source="voice"` is already routed alongside
`"chat"` in the notebook.


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

**The endpoint answering is not the same as a game being readable.** This bit
live, first run:

```
[lol] Game detected!  as ()
[lol]   riotId='' summonerName=''      Enemies: False | Names: 0
```

On the loading screen the API responds with an empty `activePlayer` and an
empty `allPlayers`, and `_game_active` used to be set unconditionally on any
response. The empty identity then latched for the whole match, and every split
between "ours" and "theirs" broke at once — silently, and confidently:

| Because | She then |
|---|---|
| `_player_team` empty, so `team == my_team` matched nobody | swept **all ten** champions into `enemy_champions` and opened on the "chaotic mix these apes have assembled" |
| every player fell through to `elif team:` | counted every kill in the game to the enemy |
| `_my_names` empty, so `_is_me` never fired | reported his own line as 0/0/0 |
| `_has_real_enemies` False → `_classify_killer` returns `"mine"` | counted **every objective in the game** as his team's |

That last row is what "she counts total kills and objectives without splitting
who did what" was: with no team there is no split to make.

A game is now accepted only once `_identity_resolves()` says the player list is
readable — two or more players, an `activePlayer` with a name, and that name
matching a row that has a team. Until then it logs once and keeps polling.
Defence in depth behind that: `GameState.update` returns early rather than
classify sides without a team, `_classify_killer` returns `"unknown"` instead of
falling back to `"mine"`, and `record_*` files an unknown side **nowhere**.

The rule, and it is the same one as §7's opening: **being unable to answer is a
reason to wait, never a reason to guess.** A wrong team does not produce a
missing line, it produces a confident wrong one.

### Role detection — `position` works, use it

**Earlier planning here was wrong and cost the matchup feature a whole round.**
`position` was written off as "unreliable — frequently empty". Live capture says
otherwise:

```
[lol][roles] Smolder    position='BOTTOM'   [lol][roles] Darius   position='TOP'
[lol][roles] Shen       position='TOP'      [lol][roles] Sejuani  position='JUNGLE'
[lol][roles] Hecarim    position='JUNGLE'   [lol][roles] Lissandra position='MIDDLE'
[lol][roles] Viktor     position='MIDDLE'   [lol][roles] Zyra     position='UTILITY'
[lol][roles] Yunara     position='BOTTOM'   [lol][roles] Milio    position='UTILITY'
```

All ten, both teams. So **enemy roles are known**, which means:

- Matchup notes claim the lane on measurement, not on his file having scoped it
- `lane_opponent()` is a real fact — *"His lane opponent is Yunara bot 6/0/2
  (144 CS to his 118)"*
- Every scoreboard row carries its role: *"Lissandra mid 3/1/5"*. Without it she
  had no way to tell a mid laner from the person in his lane, and produced
  cross-lane nonsense like comparing his farm to what the enemy mid was doing

The quest-item work in the next paragraph is now **optional**, a fallback for
when `position` is empty. Do not start it before checking the `[lol][roles]` log
of a real game — that is what this capture is for.

Summoner spells only distinguish jungle (Ignite goes on top/mid/adc/support
alike), and remain the fallback when `position` is blank.

**2026 gave all five roles a quest**, seven items across them — jungle pets,
World Atlas → Runic Compass for support, and quest items for top/mid/adc. Since
`items[]` is in `allPlayers`, **role becomes readable from inventory for every
role**.

**Do not hardcode item names from memory — that is the exact failure mode this
section exists to avoid.**

Role detection currently does only what it can prove: `position` when the API
fills it in, otherwise Smite → jungle, otherwise **unknown, and omitted from the
prompt entirely**. The Smite check scans every string under `summonerSpells`
rather than naming a field, because the RU client localises `displayName` and
the locale-independent raw key (`…SummonerSmite…`) still carries the name.

Ground truth now captures itself: `_log_role_ground_truth` prints `position`,
summoner spells and items for all ten players once per game, under
`[lol][roles]`. One game in the log gives the real item names to write the quest
detector against — no curl needed, and it self-documents when a patch changes
things. (The manual route still works:
`curl.exe -k https://127.0.0.1:2999/liveclientdata/allgamedata > game.json`.)

### What the API can and cannot see

| Available | Not available |
|---|---|
| `items[]`, `position`, `level`, `team` | **champion coordinates — none, anywhere** |
| `scores`: kills/deaths/assists/**creepScore**/wardScore | dives, rotations, whether you were warded |
| `ChampionKill`: Killer, Victim, **Assisters[]** | |
| Your **full** runes; everyone else's keystone + trees | others' minor runes and shards |

Derivable: items vs items, lane matchup, CS differential, solo kill vs teamfight
(`len(Assisters)`), gank *inferred* (enemy jungler on a lane target).

### Why she felt repetitive — and what was done about it

The quote pools were never the problem; **23 of 24 fire**. Three things were:

1. **One instruction for five event types.** DragonKill, HeraldKill,
   TurretKilled, AllyKill and AllyDeath — the most frequent events in any game
   — all collapsed into a single "be dismissive" line. The seeds varied; the
   instruction did not, so the model converged.
2. **The game state was thrown away.** The Live Client API was polled every two
   seconds and `_push_event` forwarded her champion name and nothing else. She
   had no idea what minute it was, what the score was, or how many drakes were
   gone, so every ally death was the same prompt.
3. **Volume.** `AllyDeath` at 0.6 over roughly twenty-five deaths in a losing
   game is fifteen comments about other people dying, all drawn from five seeds.

Now:

| Piece | File | What it does |
|---|---|---|
| **Measured state** | `orchestrator/game_state.py` | Keeps the poll: minute and phase, his champion/role/level/KDA/CS (and CS rank across all ten), team kill totals, drake–baron–herald–tower–inhibitor counts per side, soul point, **and every player's scoreboard row** |
| **Angles** | `orchestrator/game_angles.py` | ~93 instructions across 15 event types. Each fires only when its facts are true, and the least recently used one wins |
| **Burst decay** | `REACTION_DECAY`, `REACTION_WINDOW` | Each reaction of the same kind inside 90 game-seconds multiplies the next one's chance by 0.55, so one teamfight is one comment |
| **Mood** | `GameState.mood()` | Kill lead, objective lead and his own line → [-1, 1], fed as `mood_spike`. Her face used to be flat until a fifth death |

The angle is what actually creates variety: the same ally death reads
differently at 4 minutes and 34, eight kills up versus eight down, first of the
game versus fourth in ninety seconds. Those are real differences in the game, so
they are honest differences in what she says — and they cost nothing, because
the state was already being fetched.

**The floor rule.** Situational angles are the good ones, but they go quiet in a
flat game — an even scoreline at twelve minutes makes almost none of them true.
A list whose floor is one always-eligible angle then repeats that one back to
back, which is the original bug in miniature. So every event type carries at
least `MIN_UNCONDITIONAL` (3) angles that are *registers* rather than reads —
the same fact deadpan, clipped, or with a sigh is honest whatever the score.
`tests/test_game_variety.py` enforces this.

**Who did what, not just which side.** Team totals answer "who is winning";
they cannot answer "who is doing it", and that was the second half of the same
complaint. The situation block now carries every player's line —

```
  His team:   LeeSin 3/4/8, Orianna 2/5/4, Jinx 1/9/2, Thresh 0/7/11.
  Enemy team: Darius 11/2/4, Elise 5/3/9, Syndra 4/4/6, Caitlyn 6/3/5, ...
```

— so "Jinx is one and nine" and "Darius is eleven and two" are available where
only "your team is behind" was before. `worst_ally()`, `best_ally()`,
`biggest_threat()` and `carrying()` derive from those rows and drive angles that
name one player rather than the team. Objectives record **who took them**, so
`dragon_one_man_band` can say all three drakes were the same jungler, and every
objective event names its taker ("Exiled's teammate LeeSin took the Infernal
dragon") instead of "Your team took".

Measured on a simulated 34-minute losing game: **13 distinct angles across 14
signals**, ally-death comments down from ~15 to ~7.

**Event text is now a plain fact.** `Your those things on team LeeSin died` was
being handed to the model — the collective-noun pool has mixed grammatical forms
and splicing it into a possessive sentence broke the English. The slang is *her*
vocabulary and comes from the persona; the event text just says what happened.

### Why she repeated herself

Second live session, terminated by the streamer: *"she was saying Liss was doing
something while I farm measly CS, she said it 5-6 times in a row"*. Three causes,
compounding.

**1. Every game event was a conversation turn.** The notebook passed
`memory.get_history()` for every signal and appended every game reaction with
`add_exchange`. `MAX_HISTORY` is 5, and she repeated herself 5-6 times — not a
coincidence. Each event reached the LLM with her last five game reactions
replayed as a dialogue, where each "user turn" was the whole framed prompt,
SITUATION block and all. She was shown five near-identical setups plus her own
five answers, and asked for a sixth. Opener-based anti-repetition could not
touch it: she varied the first four words and repeated the substance.

Game events now carry **no** history — a game reaction is not a turn in a
conversation, nobody said anything to her, and her continuity comes from the
SITUATION block, which is current and accurate where a transcript of five stale
prompts is neither. What she *said* is kept separately, capped at
`MAX_GAME_LINES` and cleared on GameStart, purely to tell her not to say it
again ("do not repeat any of them, and do not rephrase them"). Game lines also
stay out of the compression budget: a game produces dozens and they would crowd
out the chat they sit alongside.

**2. No floor under how often she spoke.** Per-type decay stops her repeating a
*kind* of remark, but five different event types inside one teamfight still had
her narrating continuously — she finishes a line, the next queued event goes
straight out. `GAME_MIN_GAP` (20 game-seconds) is a floor between any two game
comments; only priority ≤ `VOICE_INTERRUPT_PRIORITY` cuts through. Five events
in one fight now produce one comment.

**3. No roles, so lanes were guesswork.** Fixed by `position` — see §7 "Role
detection".

### Tone — how hard she goes

The streamer's rulebook, in `orchestrator/tone.py`:

| Situation | Tone | She comments |
|---|---|---|
| 1st death, traded for a kill | warm | 50% — saying nothing *is* the reaction |
| deaths 2–5, traded something | light / dry | ~70% |
| dying for free (no kills, no assists) | **roast** | 90% |
| death 6 onward | roast / sharp + lecture | always |
| …unless it bought **2+ kills** (not assists) | warm, surprised | always |
| an objective he was in on, 0 kills of his own | light or dry, genuinely split | 75% |

**A verdict owns its reaction chance.** The generic burst decay used to
multiply it as well, so a sixth death the rulebook says always lands was
arriving at 55%. Caught in simulation.

**The top of the ladder cannot repeat.** From the session: *"FULL ROAST only
makes her repeat herself on the 2nd message."* A tone is a narrow instruction,
and asking a 9B model for two maximum-heat roasts back to back gets the same
roast twice. `ToneLadder` steps down after a roast and never issues the same
harsh tone consecutively — the heat returns on the death after next, which also
makes it land harder. Warm is exempt: two pleased reactions do not grate, and
pulling her off warm would read as withdrawing approval for no reason.

Tone is deliberately **separate from the angle**. The angle says *what to talk
about*, the tone says *how warm to be about it*, and multiplying them is where
the variety lives — five tones across ~119 angles, rather than one fixed
instruction per event type.

### Theme — a disposition, never a sentence

From the meta notes: a game where he is Riven mid into a CC-heavy comp should
have a *theme* — "how can I play, how can I move" — colouring everything.

From the session after: *"the theme sentence 'he's not even trying' was like an
entry message that never changed within one game, and such a prefix became
annoying quite fast."*

Both are right, and the second is why `orchestrator/game_theme.py` emits **no
text after its opening line**. A theme is derived from facts that do not change
during a game, so anything textual it produces is the same words forty times.
Instead it does three things:

1. One opening instruction, used at GameStart and never again
2. Shifts the tone ladder a step (jungle `+1` harsher, bot `-1` softer, immobile
   `-1` — that one is not his fault)
3. Unlocks extra angles, which the chooser rotates like any others

The third is the trick. *"He is immobile into a team that can chain him"* is not
a line she says; it is a reason certain observations become available, and the
anti-repetition machinery still decides which she reaches for. `theme_cannot_move`,
`theme_cc_chain` and `theme_walked_at_them` are three different remarks about
one underlying fact.

The comp theme needs **his** tags — `melee` on his champions, `heavy_cc` on
theirs, in `data/champions.json`. Three tagged enemies is the threshold.
Untagged champions count for nothing, so an unwritten file produces no comp
theme rather than a guessed one (§7).

**Tuning, in order:** `GAME_MIN_GAP` if she still talks too continuously;
`REACTION_CHANCE` per event if she talks too much;
`REACTION_DECAY` if bursts still cluster; add angles to the lists in
`game_angles.py` if a particular event feels stale. Adding an angle is a
three-line change and needs no other edits.

### The cheer and the boo

A game ends and she reacts to it **before** she has anything thoughtful to say:

```
[lol] CHEER: Hah! Yes. That is how it is done.     prio 1, quote
[lol] GameEnd: We won. Obviously.  [end_plain]     prio 2, LLM
```

Two signals, in that order, and the busy flag guarantees the ordering without
any coordination. The first is a **quote** — `skip_llm`, straight to TTS — so
the noise lands while the screen is still grey rather than after an LLM round
trip and a synthesis. Her actual line follows behind it.

`CHEER_PRIORITY = 1` is the highest anything uses: above a sub, above his own
chat, and under `VOICE_INTERRUPT_PRIORITY` so **the voice gate does not hold
it**. If the game just ended you are probably already talking about it, and
that is exactly when the noise belongs. It also bypasses `REACTION_CHANCE`, the
burst decay and `GAME_MIN_GAP` — a game ends once, so there is nothing for it
to be repetitive against.

Pools are `game_state.cheer` and `game_state.boo` in `data/game_quotes.json`.
They are spoken **verbatim**, so they have to sound like her as written — no
model is going to rephrase them.

One gap this exposed on the notebook side: quote signals never went near the
LLM, so nothing set a mood and her face sat neutral through them. The quote
path applies `mood_spike` now, which is what makes the cheer land as a
reaction rather than a noise.

### Deleted

Verified unreachable before removal, not assumed:

| Removed | Why |
|---|---|
| `TwitchChatSource.add_known_user` | Never called; `known_users` is passed at construction |
| `GameState.best_ally` | Added alongside `worst_ally` and never used |
| `SignalQueue.is_empty` | Superseded by `peek()` |
| `language.letter_count` | Orphaned when `confident()` became asymmetric |
| `_pick_teammate_name` and the `teammates.names` pool | The collective slang lives in the persona prompt, which carries the identical list. Its last caller was rephrased |
| `teammates.ally_death_multiple` | Written, never read |
| unused `numpy` / `get_settings` imports | — |

Loose end: `MyAssist` is routed but never emitted.

### Champ select

The Live Client API does not exist during champ select — that is the LCU API
(random port, lockfile auth in the League install dir, `/lol-champ-select/v1/session`).

**Game start is the better target**: same API already being polled, zero new
integration, and all ten champions are visible. You lose reacting to the pick as
it happens and gain not building a second client.

### Build order

1. ~~**Name list**~~ — still open, small, fixes a live bug
2. ~~**Capture `game.json`**~~ — **done differently**: `[lol][roles]` logs it
   every game, so one played game gives the ground truth
3. **Role detection from quest items** — the plumbing exists (`GameState.position`,
   used by the situation block when known). It needs the real item names from
   the `[lol][roles]` log, and nothing else
4. ~~**Observational commentary**~~ — **done**. CS, CS/min, CS rank, KDA, kill
   lead, drake and tower counts, minute and phase all reach the prompt
5. ~~**Per-champion history lines**~~ — **plumbing done**, `data/champions.json`.
   What remains is writing your actual notes over the placeholders
6. **Comp counting** — last, optional. Tag `heavy_cc` / `hard_engage` yourself so
   "five of them can stop you moving" is arithmetic on *your* data, never her
   opinion. The enemy champion list is already in the situation block

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
- Move the eleven older test suites out of the scratchpad into the repos
- Stray submodule in `ravyn-nb` (gitlink at `ravyn-nb/`, no `.gitmodules`)
- `quote` signals round-trip to the notebook just to be handed back — they could
  short-circuit locally, which would let her speak with the notebook powered off
- Qwen `Base` cloning has no `exaggeration` equivalent, so mood no longer
  modulates her *voice*; it still drives her face
- `[voice] Stream status: input overflow` under heavy CPU load — benign at
  startup, worth buffering if it recurs mid-stream
