# Graph Report - ravyn-lynx-p  (2026-11-11)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2048 nodes · 4997 edges · 97 communities (75 shown, 22 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 440 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- test_worker_log.py (NB)
- TwitchChatSource (PC)
- Temper (PC)
- test_alerts.py (PC)
- test_champion_notes.py (PC)
- test_voice_in.py (PC)
- test_youtube_web_chat.py (PC)
- idle.gd (Godot)
- test_promo.py (PC)
- pathlib (PC)
- test_stream_elements.py (PC)
- LolGameSource (PC) #11
- Dispatcher (PC) #12
- test_ghost.py (PC)
- Dispatcher (PC) #14
- test_game_variety.py (PC)
- MemoryManager (NB) #16
- audio_server.py (PC)
- rabbitmq.py (NB) #18
- test_event_registration.py (PC)
- test_repeats.py (NB)
- test_language.py (PC)
- Prompt Framing (NB) #50 (NB)
- clean (NB)
- SignalQueue (PC)
- GameState (PC) #25
- test_identity.py (PC)
- TTSEngine (PC)
- test_tone_and_theme.py (PC) #28
- ChatRoom (PC) #29
- main (PC)
- ChatRoom (PC) #31
- session_metrics.py (PC)
- analyze_session.py (PC)
- Ravyn-Lynx PC — Orchestrator (PC)
- join_logs.py (PC)
- response_listener.py (PC)
- LolGameSource (PC) #37
- 7. Character and reactions — the plan (PC) #38
- ChatRoom (PC) #39
- 4. Architecture Decisions (NB)
- test_per_user_memory.py (NB)
- test_join_logs.py (PC)
- 7. Orchestration System (Planned) (NB)
- Player (PC)
- SilenceFiller (PC)
- 7. Character and reactions — the plan (PC) #46
- test_persona_context.py (NB)
- Persona and Avatar Design (NB) #42 (NB)
- Persona and Avatar Design (NB) #64 (NB)
- start_response_listener (PC)
- rabbitmq.py (NB) #51
- test_game_memory.py (NB) #52
- Orchestration Design Notes (NB) (NB)
- sys (PC)
- rabbitmq.py (NB) #55
- record_main.gd (Godot)
- test_tone_and_theme.py (PC) #57
- STATUS Design Notes (PC) (PC) #58
- 5. Idle Behavior Design (NB)
- README Architecture Concepts (PC) (PC) #60
- STATUS Design Notes (PC) (PC) #61
- Ravyn — notebook state (NB)
- game_state.py (PC)
- README Architecture Concepts (PC) (PC) #64
- STATUS Design Notes (PC) (PC) #65
- MemoryManager (NB) #66
- README Architecture Concepts (PC) (PC) #67
- README Architecture Concepts (PC) (PC) #68
- log_receiver.py (PC) #68 (PC)
- Worker Report Tool (NB) (NB)
- 3. Ravyn's Live2D Face Parameter Map (NB)
- test_game_memory.py (NB) #72
- STATUS Design Notes (PC) (PC) #74
- test_session_log.py (PC)
- _FakeArray (PC)
- _App (PC)
- 6. Emotion System Design (NB)
- debug_promo_status (PC)
- debug_alert (PC)
- _Channel (PC)
- setup_venv.sh (NB)
- speech_server.gd (Godot)
- LolGameSource (PC) #85
- tts_player.gd (Godot)
- Logs (PC)
- TTS Setup on RTX 5080 (PC) (PC)
- ._deaf (PC)
- 7. Character and reactions — the plan (PC) #91
- start_llm.sh (NB)
- start_stack.sh (NB)
- stop_stack.sh (NB)
- Pydantic Dependency (NB) (NB)

## God Nodes (most connected - your core abstractions)
1. `SignalQueue` - 112 edges
2. `Signal` - 72 edges
3. `LolGameSource` - 69 edges
4. `GameState` - 58 edges
5. `Temper` - 50 edges
6. `get_settings()` - 36 edges
7. `main()` - 35 edges
8. `MemoryManager` - 34 edges
9. `ChatRoom` - 32 edges
10. `StreamElementsSource` - 31 edges

## Surprising Connections (you probably didn't know these)
- `Measuring it instead of remembering it` --references--> `Signal`  [INFERRED]
  STATUS.md → orchestrator/models.py
- `A person's language sticks` --references--> `SpeakerMemory`  [INFERRED]
  STATUS.md → orchestrator/language.py
- `Bugs found and fixed, worth not reintroducing` --references--> `is_placeholder()`  [INFERRED]
  STATUS.md → orchestrator/champion_notes.py
- `What the model was asked, and what it answered` --references--> `run_llm()`  [INFERRED]
  STATUS.md → adapters/llm/llama_server_client.py
- `Tone — how hard she goes` --references--> `ToneLadder`  [INFERRED]
  STATUS.md → orchestrator/tone.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **PC <-> Godot avatar contract** — websocket::ws_audio, ravyn-lynx-p::services_audio_server_websocket_endpoint, ravyn-lynx-p::services_audio_server_send_text_to_godot, ravyn-lynx-p::services_audio_server_send_bytes_to_godot, ravyn-godot::scripts_main_handle_websocket [EXTRACTED 1.00]
- **PC <-> notebook message contract** — rabbitmq::ravyn_request, rabbitmq::ravyn_response, rabbitmq::ravyn_log, ravyn-lynx-p::orchestrator_dispatcher_dispatcher_dispatch, ravyn-nb::adapters_mq_rabbitmq_start_worker_callback, ravyn-lynx-p::services_response_listener_start_response_listener_handle [EXTRACTED 1.00]

## Communities (97 total, 22 thin omitted)

### Community 0 - "test_worker_log.py (NB)"
Cohesion: 0.06
Nodes (49): init(), _iso(), SessionLog, console_lines(), check(), game_signal(), last_line(), main() (+41 more)

### Community 1 - "TwitchChatSource (PC)"
Cohesion: 0.05
Nodes (25): Identity, normalise(), ScamWatch, signs_in(), theirs(), score_message(), split_tags(), TwitchChatSource (+17 more)

### Community 2 - "Temper (PC)"
Cohesion: 0.07
Nodes (28): LeagueClient, result(), GameResult, Temper, _step_down(), Temper — what kind of company she is tonight, block(), check() (+20 more)

### Community 3 - "test_alerts.py (PC)"
Cohesion: 0.07
Nodes (43): Blocklist, Clean, _collapse(), fold(), _is_sayable(), _load_lines(), Sanitizer, _speakable_name() (+35 more)

### Community 4 - "test_champion_notes.py (PC)"
Cohesion: 0.05
Nodes (30): ChampionNotes, ChampionRead, is_placeholder(), key(), normalise(), _real(), LogReceiver, callback() (+22 more)

### Community 5 - "test_voice_in.py (PC)"
Cohesion: 0.06
Nodes (30): addressed_to_her(), bare_name(), confident(), echoes_prompt(), looks_like_speech(), _normalise(), VoiceInput, _words() (+22 more)

### Community 6 - "test_youtube_web_chat.py (PC)"
Cohesion: 0.07
Nodes (26): _count(), _event(), from_api_item(), from_web_item(), parse_amount(), _simple(), embedded_client(), embedded_initial_data() (+18 more)

### Community 7 - "idle.gd (Godot)"
Cohesion: 0.07
Nodes (52): _on_init(), _on_process(), perk_up(), _ready(), do_wink(), _on_init(), _on_process(), prepare_surprised() (+44 more)

### Community 8 - "test_promo.py (PC)"
Cohesion: 0.09
Nodes (26): Settings, _load(), PromoSource, check(), FakeRandom, game(), main(), ready() (+18 more)

### Community 9 - "pathlib (PC)"
Cohesion: 0.09
Nodes (8): get_settings(), instruction(), read_kill(), read_objective_participation(), Verdict, _wording(), check(), main()

### Community 10 - "test_stream_elements.py (PC)"
Cohesion: 0.08
Nodes (3): Signal, MockEventSource, StreamElementsSource

### Community 11 - "LolGameSource (PC) #11"
Cohesion: 0.11
Nodes (3): LolGameSource, ended_without_gameend(), words_for()

### Community 12 - "Dispatcher (PC) #12"
Cohesion: 0.06
Nodes (10): VoiceGate, check(), deliver(), main(), RecordingGate, StubGate, StubTTS, test_ghost_fade_waits_for_playback() (+2 more)

### Community 13 - "test_ghost.py (PC)"
Cohesion: 0.12
Nodes (21): check(), FakeGodot, fresh_ghost_state(), godot_sees(), _JSONResponse, _line(), main(), _run() (+13 more)

### Community 14 - "Dispatcher (PC) #14"
Cohesion: 0.09
Nodes (7): Dispatcher, 6. Voice gate, Deleted, How it works now, She finishes the sentence, then hands over the floor, Why the first version felt wrong, test_dispatch_policy()

### Community 15 - "test_game_variety.py (PC)"
Cohesion: 0.13
Nodes (15): _always(), Angle, AngleChooser, _safe(), check(), main(), snapshot(), test_angle_variety() (+7 more)

### Community 17 - "audio_server.py (PC)"
Cohesion: 0.10
Nodes (15): begin_utterance(), _cancel_fade(), _compute_envelope(), end_utterance(), _fade_after(), fade_out(), _get_phonemes(), _get_phonemizer() (+7 more)

### Community 18 - "rabbitmq.py (NB) #18"
Cohesion: 0.11
Nodes (16): _avoid_repeat(), _clean_for_tts(), _finish(), _gate_fufu(), _gate_tch(), _note_donation(), _seed_line(), start_worker() (+8 more)

### Community 19 - "test_event_registration.py (PC)"
Cohesion: 0.15
Nodes (20): activity(), check(), fake_api(), FakeClient, FakeResponse, in_game(), kinds(), main() (+12 more)

### Community 20 - "test_repeats.py (NB)"
Cohesion: 0.14
Nodes (17): _avoid_copying(), _grams(), _norm(), RepeatGuard, _runs(), similarity(), without_copies(), words() (+9 more)

### Community 21 - "test_language.py (PC)"
Cohesion: 0.15
Nodes (15): confident(), cyrillic_ratio(), detect_lang(), is_ambient(), resolve(), SpeakerMemory, check(), main() (+7 more)

### Community 22 - "Prompt Framing (NB) #50 (NB)"
Cohesion: 0.09
Nodes (23): _build_recent_chat_block(), _frame_signal(), angled(), framed(), _load_appearance(), _without_league(), fufu signature laugh rules, Hard rules (2-3 sentences, no emoji, never break character) (+15 more)

### Community 23 - "clean (NB)"
Cohesion: 0.18
Nodes (19): clean(), _norm(), Result, _sentences(), shorten(), _strip(), Tally, check() (+11 more)

### Community 24 - "SignalQueue (PC)"
Cohesion: 0.10
Nodes (9): _log_expired(), SignalQueue, _load_templates(), main(), replay(), Channel, check(), main() (+1 more)

### Community 25 - "GameState (PC) #25"
Cohesion: 0.15
Nodes (4): GameState, test_dragons_and_mood(), test_role_detection(), test_state()

### Community 26 - "test_identity.py (PC)"
Cohesion: 0.19
Nodes (17): _attribution_cases(), check(), main(), real_game(), row(), source(), test_every_game_is_counted(), play_and_vanish() (+9 more)

### Community 27 - "TTSEngine (PC)"
Cohesion: 0.13
Nodes (4): ChatterboxEngine, QwenTTSEngine, _to_wav_bytes(), TTSEngine

### Community 28 - "test_tone_and_theme.py (PC) #28"
Cohesion: 0.15
Nodes (14): resolve(), Theme, read_death(), _shift_tone(), check(), main(), tags_from(), test_rulebook() (+6 more)

### Community 29 - "ChatRoom (PC) #29"
Cohesion: 0.13
Nodes (3): BatchWindow, ChatRoom, ScoredMessage

### Community 30 - "main (PC)"
Cohesion: 0.12
Nodes (7): main(), register_alert_injector(), register_promo_injector(), register_sanitizer(), build_engine(), MockChatSource, MockGameSource

### Community 31 - "ChatRoom (PC) #31"
Cohesion: 0.21
Nodes (13): check(), error(), FakeYouTube, main(), message(), page(), Resp, source() (+5 more)

### Community 32 - "session_metrics.py (PC)"
Cohesion: 0.15
Nodes (11): analyse(), append_history(), cluster(), _contains(), _longest_streak(), normalise(), phrases(), read_history() (+3 more)

### Community 33 - "analyze_session.py (PC)"
Cohesion: 0.15
Nodes (12): logs/history.csv, orchestrator/session_metrics.py, bar(), _jsonable(), load(), main(), newest_log(), print_comparison() (+4 more)

### Community 34 - "Ravyn-Lynx PC — Orchestrator (PC)"
Cohesion: 0.10
Nodes (20): Alerts and donations, Architecture, Asking for a follow or a sub, Configuration, Language, Message Format, Project Structure, RabbitMQ Queues (+12 more)

### Community 35 - "join_logs.py (PC)"
Cohesion: 0.16
Nodes (11): knob(), said(), ravyn-nb/app/worker_log.py, _print_transcript(), diagnose(), load_worker(), main(), matching_worker() (+3 more)

### Community 36 - "response_listener.py (PC)"
Cohesion: 0.18
Nodes (10): _clean_for_tts(), _split_first_chunk(), split_sentences(), check(), main(), test_no_stubs(), test_opening_still_starts_quickly(), test_short_lines_stay_whole() (+2 more)

### Community 37 - "LolGameSource (PC) #37"
Cohesion: 0.12
Nodes (5): vanished_game(), check(), main(), snapshot(), start()

### Community 38 - "7. Character and reactions — the plan (PC) #38"
Cohesion: 0.11
Nodes (18): teammate_rank(), 7. Character and reactions — the plan, Asking for a follow or a sub, Attributes, not combinations — `data/champions.json`, Build order, Hearing him — `sources/voice_in.py`, Identity — multi-account and RU server, Measuring it instead of remembering it (+10 more)

### Community 40 - "4. Architecture Decisions (NB)"
Cohesion: 0.12
Nodes (17): 4. Architecture Decisions, Why espeak word-level phonemes (not individual), Why Faster-Whisper for STT (planned), Why GDCubismEffectCustom nodes instead of one big script, Why Kokoro over Qwen TTS, Why phonemes drive form but amplitude drives open, Why pyrubberband for pitch shift, Why RabbitMQ (+9 more)

### Community 41 - "test_per_user_memory.py (NB)"
Cohesion: 0.33
Nodes (14): check(), fresh(), main(), test_compression_clears_only_that_person(), test_donations_leave_a_small_note(), test_note_trigger_is_per_person(), test_notes_are_written_from_one_persons_words(), test_notes_persist_independently_of_buffers() (+6 more)

### Community 42 - "test_join_logs.py (PC)"
Cohesion: 0.37
Nodes (13): check(), main(), nb_line(), pc_line(), test_a_filter_took_the_difference(), test_it_runs_end_to_end(), test_loading_and_matching(), test_the_angle_never_arrived() (+5 more)

### Community 43 - "7. Orchestration System (Planned) (NB)"
Cohesion: 0.12
Nodes (17): 10. Known Problems & Their Solutions, 11. What Comes Next (Priority Order), 1. Project Vision, 2. Hardware & Infrastructure, 7. Orchestration System (Planned), 8. LLM Configuration (Planned), 9. Voice Configuration, Channel points design (+9 more)

### Community 44 - "Player (PC)"
Cohesion: 0.15
Nodes (3): Player, Role detection — `position` works, use it, Why she felt repetitive — and what was done about it

### Community 45 - "SilenceFiller (PC)"
Cohesion: 0.20
Nodes (4): SilenceFiller, check(), gaps(), main()

### Community 46 - "7. Character and reactions — the plan (PC) #46"
Cohesion: 0.12
Nodes (13): 1. Decisions, and why, 2. What lives where, 3. Running it, 5. Language, 8. Open, A person's language sticks, faster-qwen3-tts, Godot — the third machine, and the one with no git (+5 more)

### Community 47 - "test_persona_context.py (NB)"
Cohesion: 0.34
Nodes (12): build_messages(), check(), main(), test_a_first_message_tonight_is_greeted(), test_a_likely_scam_is_not_welcomed(), test_a_stream_that_is_not_league(), test_appearance(), test_chat_does_not_tunnel_into_the_game() (+4 more)

### Community 48 - "Persona and Avatar Design (NB) #42 (NB)"
Cohesion: 0.15
Nodes (10): Ravyn Project Knowledge Base & Decision Document, Known problems and solutions table, Kokoro TTS (af_bella, +3 semitones, speed 0.95), Live2D face parameter map, Physics-driven params and ParamEarJigL/R workaround, Planned upgrade to Qwen 3.5-9B, RTX 4070 8GB VRAM budget, fastapi (+2 more)

### Community 49 - "Persona and Avatar Design (NB) #64 (NB)"
Cohesion: 0.13
Nodes (12): Ravyn-Lynx Notebook — LLM service, Ravyn Mascot Job Priorities (alerts, chat, League co-commentary), Running the stack, What is not built yet, What Ravyn is, What this repo is responsible for, What works, Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py) (+4 more)

### Community 50 - "start_response_listener (PC)"
Cohesion: 0.25
Nodes (11): get(), has_clients(), _run_async(), start_response_listener(), callback(), _handle(), _play(), _speak() (+3 more)

### Community 51 - "rabbitmq.py (NB) #51"
Cohesion: 0.24
Nodes (10): _extract_value(), _handle_think_tags(), _post(), run_llm(), run_llm_simple(), _strip_tags(), _ts(), _compress_memory_async() (+2 more)

### Community 52 - "test_game_memory.py (NB) #52"
Cohesion: 0.22
Nodes (7): _check_numbers(), numbers_in(), unsupported(), without_sentences_naming(), check(), main(), test_compound_with_one_reads_whole()

### Community 53 - "Orchestration Design Notes (NB) (NB)"
Cohesion: 0.15
Nodes (9): Anti-repetition rule, Faster-Whisper STT (planned), Orchestration system (signal sources, priority, TTL), Silence filler and stunts.json, ANGLE (per-event instruction, replaces fixed template), GAME_EVENT_RULES bans restating the direction, Memory (get_history, add_exchange, user_notes, general_memory, donors), recent_game_lines / get_repetition_guard (+1 more)

### Community 54 - "sys (PC)"
Cohesion: 0.33
Nodes (5): bridges(), edge(), find_line(), main(), run()

### Community 55 - "rabbitmq.py (NB) #55"
Cohesion: 0.23
Nodes (6): _env(), _env(), _env_bool(), _env_float(), _env_int(), Settings

### Community 56 - "record_main.gd (Godot)"
Cohesion: 0.32
Nodes (9): _apply_pose(), breathe(), _face(), _mouth(), _process(), _pset(), _sample(), _spline() (+1 more)

### Community 57 - "test_tone_and_theme.py (PC) #57"
Cohesion: 0.23
Nodes (3): ToneLadder, Tone — how hard she goes, test_ladder_refuses_to_repeat()

### Community 58 - "STATUS Design Notes (PC) (PC) #58"
Cohesion: 0.20
Nodes (10): Dispatcher (dispatcher.py), LANG_REPLY = detect, Language resolution (orchestrator/language.py), OWNER_PRIORITY and is_owner flag, PC/Notebook split architecture (ravyn.request / ravyn.response over RabbitMQ), Sentence-boundary preemption (more_important_waiting), RabbitMQ, SpeakerMemory (sticky per-person language) (+2 more)

### Community 59 - "5. Idle Behavior Design (NB)"
Cohesion: 0.17
Nodes (11): Mood and tired inline tags, 5. Idle Behavior Design, Asymmetric brows, Emotion system (mood/tired scales, cascade), Hold phase, Idle two-group system (User Focus / Wandering), Micro expressions, Tiredness effect on idle (+3 more)

### Community 60 - "README Architecture Concepts (PC) (PC) #60"
Cohesion: 0.25
Nodes (11): Audio Server (WebSocket to Godot), Ghost Mode (--ghost, SHOW protocol), Godot Avatar (ravyn-lynx-godot), Voice gate, Voice Input (Whisper STT), Python Dependencies, fastapi / uvicorn, faster-whisper (+3 more)

### Community 61 - "STATUS Design Notes (PC) (PC) #61"
Cohesion: 0.20
Nodes (10): Burst decay (REACTION_DECAY / REACTION_WINDOW), champion_notes (data/champions.json, orchestrator/champion_notes.py), Game angles (orchestrator/game_angles.py), GAME_MIN_GAP, Game theme (orchestrator/game_theme.py), --league flag, Promo asks (sources/promo.py, data/promo.json), Teammate vocabulary ranks (TEAMMATE_RANKS) (+2 more)

### Community 62 - "Ravyn — notebook state (NB)"
Cohesion: 0.18
Nodes (10): Deleted, and why, Game events are not conversation, Hardware, Model choice, Open here, Ravyn — notebook state, Role, Running (+2 more)

### Community 63 - "game_state.py (PC)"
Cohesion: 0.20
Nodes (4): _clamp(), _mentions_smite(), _ordinal(), Side

### Community 64 - "README Architecture Concepts (PC) (PC) #64"
Cohesion: 0.27
Nodes (10): StreamElements --replay Offline Path, League Live Client Game Source, League Mode (--league), Promos (follow/sub asks), Sanitizing with Blocklist, Signal Sources, Silence Filler, skip_llm Quote Signal (+2 more)

### Community 65 - "STATUS Design Notes (PC) (PC) #65"
Cohesion: 0.20
Nodes (9): Champ select, Cheer and boo quotes, GameState (orchestrator/game_state.py), Identity (data/identity.json, orchestrator/identity.py), Loading-screen identity gate (_identity_resolves), Observe, don't predict, Role detection via position field, Alert sanitizer (orchestrator/sanitize.py) (+1 more)

### Community 66 - "MemoryManager (NB) #66"
Cohesion: 0.22
Nodes (4): `data/memory.json` is runtime state, not source, Every run she is a new person — except about people, Persona (`persona/`), What she remembers, and what she never does

### Community 67 - "README Architecture Concepts (PC) (PC) #67"
Cohesion: 0.25
Nodes (9): ravyn.log Queue, Busy Watchdog (BUSY_TIMEOUT), Dispatcher (owns busy state), Priority Queue with TTL, ravyn-nb Notebook LLM Service, ravyn.request Queue, ravyn.response Queue, Response Listener (+1 more)

### Community 68 - "README Architecture Concepts (PC) (PC) #68"
Cohesion: 0.25
Nodes (9): app/settings.py Configuration, Chatterbox TTS Fallback, faster-qwen3-tts Wrapper, Language Resolution (LANG_AMBIENT / LANG_REPLY), Qwen3-TTS Voice Cloning, TTS Engine, chatterbox-tts, faster-qwen3-tts (+1 more)

### Community 69 - "log_receiver.py (PC) #68 (PC)"
Cohesion: 0.43
Nodes (7): Logs Directory Layout (pc/ nb/ history.csv), Notebook Worker Log (nb/), analyze_session.py Report, history.csv Running Table, join_logs.py Line-to-Prompt Join, Session log, Why a line came out that way

### Community 70 - "Worker Report Tool (NB) (NB)"
Cohesion: 0.25
Nodes (7): LEAGUE OF LEGENDS section, Non-League mode flag, Not built yet: Russian character, non-League mode, official vs abliterated A/B, joined log view, ravyn-lynx-p/orchestrator/session_log.py, req_id joins PC session log and worker log, Test suites (test_game_memory, test_persona_context, test_per_user_memory, test_worker_log), app/worker_log.py JSONL worker log

### Community 71 - "3. Ravyn's Live2D Face Parameter Map (NB)"
Cohesion: 0.25
Nodes (8): 3. Ravyn's Live2D Face Parameter Map, Brows, Eye Direction Constraints (from testing), Eyes, Head, Mouth, Physics-Driven Parameters (cannot be set directly), Special Parameters

### Community 72 - "test_game_memory.py (NB) #72"
Cohesion: 0.57
Nodes (6): check(), fresh(), main(), test_game_lines_are_bounded_and_reset(), test_game_lines_are_kept_apart(), test_history_is_withheld_from_game_events()

### Community 74 - "STATUS Design Notes (PC) (PC) #74"
Cohesion: 0.33
Nodes (7): audio_server (services/audio_server.py), Cubism export trap (non-resource file filters), --ghost flag (ghost mode), Godot avatar (ravyn-lynx-godot main.gd), Godot WebSocket text protocol (MOOD/TIRED/SHOW/START/END/RATE/MOUTH/PHONEME), response_listener (services/response_listener.py), TTSEngine (services/tts_engine.py)

### Community 75 - "test_session_log.py (PC)"
Cohesion: 0.29
Nodes (4): Session log (orchestrator/session_log.py), _finalise(), close(), parse_file()

### Community 79 - "6. Emotion System Design (NB)"
Cohesion: 0.33
Nodes (6): 6. Emotion System Design, Design rule: emotions come from LLM text, How mood reaches Godot (planned), Mood cascade effects, Mood scale, Tired scale

### Community 91 - "7. Character and reactions — the plan (PC) #91"
Cohesion: 0.67
Nodes (3): 4. Built so far, Bugs found and fixed, worth not reintroducing, Tests

## Ambiguous Edges - Review These
- `Kokoro TTS (af_bella, +3 semitones, speed 0.95)` → `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)`  [AMBIGUOUS]
  ravyn_knowledge_base.md · relation: conceptually_related_to

## Knowledge Gaps
- **30 isolated node(s):** `logs/history.csv`, `ravyn-nb/app/worker_log.py`, `Physics-driven params and ParamEarJigL/R workaround`, `is_owner flag from data/identity.json`, `player_notes (Exiled's claims from champions.json)` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 701 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LolGameSource` connect `LolGameSource (PC) #11` to `TwitchChatSource (PC)`, `Temper (PC)`, `test_champion_notes.py (PC)`, `LolGameSource (PC) #37`, `pathlib (PC)`, `test_stream_elements.py (PC)`, `LolGameSource (PC) #73`, `test_game_variety.py (PC)`, `test_event_registration.py (PC)`, `SignalQueue (PC)`, `GameState (PC) #25`, `test_identity.py (PC)`, `main (PC)`, `test_tone_and_theme.py (PC) #57`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `SignalQueue` (e.g. with `Dispatcher` and `Signal`) actually correct?**
  _`SignalQueue` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `logs/history.csv`, `ravyn-nb/app/worker_log.py`, `Physics-driven params and ParamEarJigL/R workaround` to the rest of the system?**
  _30 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_worker_log.py (NB)` be split into smaller, more focused modules?**
  _Cohesion score 0.05960007765482431 - nodes in this community are weakly interconnected._
- **Why does `SignalQueue` connect `SignalQueue (PC)` to `TwitchChatSource (PC)`, `Temper (PC)`, `test_alerts.py (PC)`, `test_voice_in.py (PC)`, `test_youtube_web_chat.py (PC)`, `test_promo.py (PC)`, `pathlib (PC)`, `test_stream_elements.py (PC)`, `LolGameSource (PC) #11`, `Dispatcher (PC) #12`, `Dispatcher (PC) #14`, `test_game_variety.py (PC)`, `test_event_registration.py (PC)`, `test_identity.py (PC)`, `ChatRoom (PC) #29`, `main (PC)`, `ChatRoom (PC) #31`, `LolGameSource (PC) #37`, `SilenceFiller (PC)`, `test_tone_and_theme.py (PC) #57`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Signal` (e.g. with `Dispatcher` and `_log_expired()`) actually correct?**
  _`Signal` has 13 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Kokoro TTS (af_bella, +3 semitones, speed 0.95)` and `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._