# Graph Report - ravyn-lynx-p  (2026-11-07)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1717 nodes · 4307 edges · 73 communities (55 shown, 18 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 369 edges (avg confidence: 0.87)
- Token cost: 304,146 input · 0 output

## Community Hubs (Navigation)
- Session Analysis Tools (PC)
- Per-Person Memory (NB)
- Temper and Game Results (PC)
- StreamElements Alerts (PC)
- Promo Asks (PC)
- Dispatcher and Signals (PC)
- App Startup and Settings (PC)
- Worker Log (NB)
- Session Log (PC)
- League Event Handling (PC)
- STATUS Design Notes (PC)
- Tone and Game Theme (PC)
- Game State Facts (PC)
- YouTube API Chat (PC)
- Owner Identity and Twitch (PC)
- Champion Notes (PC)
- Output Filters (NB)
- Ghost Mode Tests (PC)
- Audio Server (PC)
- Angle Chooser (PC)
- Language Resolution (PC)
- Sanitizer and Blocklist (PC)
- Prompt Framing (NB)
- TTS Engines (PC)
- Live and Web Chat Tools (PC)
- Event Registration Tests (PC)
- Kill Attribution Tests (PC)
- Mock Sources and Wiring (PC)
- Chat Room and YouTube Web (PC) #28
- Voice Input Tests (PC)
- Chat Room and YouTube Web (PC) #30
- Persona and Avatar Design (NB) #31
- Worker and LLM Client (NB) #32
- Repeat Guard (NB)
- README Architecture Concepts (PC) #34
- Chat Room and YouTube Web (PC) #35
- Voice Gate and Hearing (PC) #36
- Response Listener and Debug (PC)
- Notebook Log Receiver (PC) #38
- Speech Language Detection (PC)
- Worker and LLM Client (NB) #40
- Orchestration Design Notes (NB) #42
- Game State Helpers (PC)
- Notebook Log Receiver (PC) #44
- Voice Gate and Hearing (PC) #45
- Worker and LLM Client (NB) #46
- README Architecture Concepts (PC) #47
- Utterance Lip Sync (PC)
- Chat Room and YouTube Web (PC) #49
- Number Check (NB)
- Speech Filtering (PC)
- Persona and Avatar Design (NB) #52
- Silence Filler (PC)
- Orchestration Design Notes (NB) #54
- Request IDs and Game Memory (NB)
- Logs Layout Docs (PC)
- README Architecture Concepts (PC) #57
- Ghost Test Fakes (PC)
- Persona and Avatar Design (NB) #59
- FastAPI Test Stub (PC)
- Debug Alert Endpoints (PC)
- Rabbit Channel Fake (PC)
- Voice Gate Tests (PC)
- Venv and Service Scripts (NB)
- Drake Count Phrasing (PC)
- TTS Setup on RTX 5080 (PC)
- LLM Start Script (NB)
- Stack Start Script (NB)
- Stack Stop Script (NB)
- Pydantic Dependency (NB)

## God Nodes (most connected - your core abstractions)
1. `SignalQueue` - 98 edges
2. `LolGameSource` - 67 edges
3. `Signal` - 64 edges
4. `GameState` - 57 edges
5. `Temper` - 46 edges
6. `main()` - 34 edges
7. `get_settings()` - 34 edges
8. `MemoryManager` - 33 edges
9. `PromoSource` - 29 edges
10. `StreamElementsSource` - 29 edges

## Surprising Connections (you probably didn't know these)
- `recent_game_lines / get_repetition_guard` --semantically_similar_to--> `Anti-repetition rule`  [INFERRED] [semantically similar]
  STATUS.md → persona/system_prompt.txt
- `Silence filler and stunts.json` --semantically_similar_to--> `Anti-repetition rule`  [INFERRED] [semantically similar]
  ravyn_knowledge_base.md → persona/system_prompt.txt
- `ChatRoom` --uses--> `Signal`  [INFERRED]
  sources/chat_room.py → orchestrator/models.py
- `ChatRoom` --uses--> `SignalQueue`  [INFERRED]
  sources/chat_room.py → orchestrator/priority_queue.py
- `godot_sees()` --uses--> `Settings`  [INFERRED]
  tests/test_ghost.py → app/settings.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **PC <-> notebook message contract** — rabbitmq::ravyn_request, rabbitmq::ravyn_response, rabbitmq::ravyn_log, ravyn-lynx-p::orchestrator_dispatcher_dispatcher_dispatch, ravyn-nb::adapters_mq_rabbitmq_start_worker_callback, ravyn-lynx-p::services_response_listener_start_response_listener_handle [EXTRACTED 1.00]
- **Verbatim quote signals that bypass the LLM** — ravyn-lynx-p::readme_skip_llm_quote_signal, ravyn-lynx-p::readme_streamelements_alerts, ravyn-lynx-p::readme_promo, ravyn-lynx-p::readme_silence_filler, ravyn-lynx-p::readme_sanitizing [EXTRACTED 1.00]
- **Request-to-speech pipeline** — ravyn-lynx-p::readme_dispatcher, ravyn-lynx-p::readme_ravyn_request_queue, ravyn-lynx-p::readme_ravyn_nb_notebook, ravyn-lynx-p::readme_ravyn_response_queue, ravyn-lynx-p::readme_response_listener, ravyn-lynx-p::readme_tts_engine, ravyn-lynx-p::readme_audio_server, ravyn-lynx-p::readme_godot_avatar [EXTRACTED 1.00]
- **PC voice output flow** — ravyn-lynx-p::status_dispatcher, ravyn-lynx-p::status_response_listener, ravyn-lynx-p::status_tts_engine, ravyn-lynx-p::status_audio_server, ravyn-lynx-p::status_godot_avatar [EXTRACTED 1.00]
- **Session measurement pipeline** — ravyn-lynx-p::status_session_log, ravyn-lynx-p::tools_analyze_session, ravyn-lynx-p::status_session_metrics, ravyn-lynx-p::status_worker_log, ravyn-lynx-p::tools_join_logs, ravyn-lynx-p::status_history_csv [EXTRACTED 1.00]
- **Game event prompt framing blocks (SITUATION, ANGLE, TONE, player_notes)** — ravyn-nb::status_situation_block, ravyn-nb::status_angle, ravyn-nb::status_tone_instruction, ravyn-nb::status_player_notes, ravyn-nb::persona_context_builder [EXTRACTED 1.00]
- **PC -> RabbitMQ -> worker -> llama-server -> response pipeline** — ravyn-nb::readme_rabbitmq, ravyn-nb::readme_worker, ravyn-nb::readme_llama_server, ravyn-nb::readme_request_response_contract [EXTRACTED 1.00]
- **Session measurement toolchain** — ravyn-lynx-p::readme_session_log, ravyn-lynx-p::readme_history_csv, ravyn-lynx-p::readme_analyze_session_tool, ravyn-lynx-p::readme_join_logs_tool, ravyn-lynx-p::logs_readme_worker_log, ravyn-lynx-p::readme_repeat_rate_knobs_heat [INFERRED 0.85]
- **Game reaction variety and heat controls** — ravyn-lynx-p::status_game_angles, ravyn-lynx-p::status_tone_ladder, ravyn-lynx-p::status_temper, ravyn-lynx-p::status_game_theme, ravyn-lynx-p::status_burst_decay, ravyn-lynx-p::status_game_min_gap [INFERRED 0.85]
- **Persona rules backed by output filters and gates** — ravyn-nb::status_output_filters, ravyn-nb::status_gate_tch, ravyn-nb::status_gate_fufu, ravyn-nb::persona_system_prompt_no_third_person, ravyn-nb::persona_system_prompt_tch_rationing, ravyn-nb::persona_system_prompt_fufu_rules [INFERRED 0.85]

## Communities (73 total, 18 thin omitted)

### Community 0 - "Session Analysis Tools (PC)"
Cohesion: 0.05
Nodes (49): analyse(), append_history(), cluster(), _contains(), knob(), _longest_streak(), normalise(), phrases() (+41 more)

### Community 1 - "Per-Person Memory (NB)"
Cohesion: 0.06
Nodes (25): build_messages(), MemoryManager, check(), fresh(), main(), test_compression_clears_only_that_person(), test_donations_leave_a_small_note(), test_note_trigger_is_per_person() (+17 more)

### Community 2 - "Temper and Game Results (PC)"
Cohesion: 0.07
Nodes (25): main(), LeagueClient, GameResult, Temper, block(), check(), FakeClient, main() (+17 more)

### Community 3 - "StreamElements Alerts (PC)"
Cohesion: 0.06
Nodes (26): Clean, Sanitizer, Tally, _load_templates(), main(), replay(), StreamElementsSource, _symbol() (+18 more)

### Community 4 - "Promo Asks (PC)"
Cohesion: 0.09
Nodes (26): Settings, _load(), PromoSource, check(), FakeRandom, game(), main(), ready() (+18 more)

### Community 5 - "Dispatcher and Signals (PC)"
Cohesion: 0.06
Nodes (12): Dispatcher, Signal, _log_expired(), check(), deliver(), main(), StubGate, StubTTS (+4 more)

### Community 6 - "App Startup and Settings (PC)"
Cohesion: 0.09
Nodes (3): get_settings(), result(), ScoredMessage

### Community 7 - "Worker Log (NB)"
Cohesion: 0.10
Nodes (27): get(), init(), _iso(), new_request_id(), WorkerLog, check(), context(), framed_prompt() (+19 more)

### Community 8 - "Session Log (PC)"
Cohesion: 0.12
Nodes (24): init(), _iso(), SessionLog, console_lines(), check(), game_signal(), last_line(), main() (+16 more)

### Community 9 - "League Event Handling (PC)"
Cohesion: 0.10
Nodes (4): read_objective_participation(), LolGameSource, ended_without_gameend(), words_for()

### Community 10 - "STATUS Design Notes (PC)"
Cohesion: 0.05
Nodes (39): audio_server (services/audio_server.py), Burst decay (REACTION_DECAY / REACTION_WINDOW), Champ select (LCU API) vs game start, champion_notes (data/champions.json, orchestrator/champion_notes.py), Cheer and boo quotes, Cubism export trap (non-resource file filters), Dispatcher (dispatcher.py), faster-qwen3-tts (+31 more)

### Community 11 - "Tone and Game Theme (PC)"
Cohesion: 0.08
Nodes (21): resolve(), Theme, instruction(), read_death(), read_kill(), _step_down(), teammate_rank(), ToneLadder (+13 more)

### Community 12 - "Game State Facts (PC)"
Cohesion: 0.09
Nodes (4): GameState, test_dragons_and_mood(), test_state(), test_who_did_what()

### Community 13 - "YouTube API Chat (PC)"
Cohesion: 0.12
Nodes (14): YouTubeChatSource, check(), error(), FakeYouTube, main(), message(), page(), Resp (+6 more)

### Community 14 - "Owner Identity and Twitch (PC)"
Cohesion: 0.10
Nodes (11): Identity, normalise(), score_message(), TwitchChatSource, check(), main(), test_chat_without_identity_is_unchanged(), test_his_message_is_never_dropped() (+3 more)

### Community 15 - "Champion Notes (PC)"
Cohesion: 0.13
Nodes (16): ChampionNotes, ChampionRead, is_placeholder(), key(), normalise(), _real(), check(), load() (+8 more)

### Community 16 - "Output Filters (NB)"
Cohesion: 0.14
Nodes (20): _collapse(), _is_sayable(), _speakable_name(), clean(), _norm(), Result, _sentences(), _strip() (+12 more)

### Community 17 - "Ghost Mode Tests (PC)"
Cohesion: 0.13
Nodes (16): check(), FakeGodot, fresh_ghost_state(), godot_sees(), _JSONResponse, main(), _run(), test_amplitude_still_drives_the_mouth() (+8 more)

### Community 18 - "Audio Server (PC)"
Cohesion: 0.09
Nodes (16): _cancel_fade(), _compute_envelope(), _fade_after(), fade_out(), _get_phonemes(), _get_phonemizer(), _ghost_show(), has_clients() (+8 more)

### Community 19 - "Angle Chooser (PC)"
Cohesion: 0.14
Nodes (14): _always(), Angle, AngleChooser, _safe(), check(), main(), snapshot(), test_angle_variety() (+6 more)

### Community 20 - "Language Resolution (PC)"
Cohesion: 0.15
Nodes (15): confident(), cyrillic_ratio(), detect_lang(), is_ambient(), resolve(), SpeakerMemory, check(), main() (+7 more)

### Community 21 - "Sanitizer and Blocklist (PC)"
Cohesion: 0.17
Nodes (17): Blocklist, fold(), _load_lines(), check(), dispatcher_with(), main(), sanitizer(), test_blocklist_matching() (+9 more)

### Community 22 - "Prompt Framing (NB)"
Cohesion: 0.09
Nodes (23): _build_recent_chat_block(), _frame_signal(), angled(), framed(), _load_appearance(), _without_league(), fufu signature laugh rules, Hard rules (2-3 sentences, no emoji, never break character) (+15 more)

### Community 23 - "TTS Engines (PC)"
Cohesion: 0.12
Nodes (5): build_engine(), ChatterboxEngine, QwenTTSEngine, _to_wav_bytes(), TTSEngine

### Community 24 - "Live and Web Chat Tools (PC)"
Cohesion: 0.12
Nodes (8): embedded_client(), main(), _activity(), _get(), main(), _post(), interactive(), send_signal()

### Community 25 - "Event Registration Tests (PC)"
Cohesion: 0.19
Nodes (18): activity(), check(), FakeClient, in_game(), kinds(), main(), se(), test_a_game_that_vanished_still_gets_its_ending() (+10 more)

### Community 26 - "Kill Attribution Tests (PC)"
Cohesion: 0.20
Nodes (16): _attribution_cases(), check(), main(), real_game(), row(), source(), test_every_game_is_counted(), play_and_vanish() (+8 more)

### Community 27 - "Mock Sources and Wiring (PC)"
Cohesion: 0.12
Nodes (4): SignalQueue, MockChatSource, MockEventSource, MockGameSource

### Community 28 - "Chat Room and YouTube Web (PC) #28"
Cohesion: 0.20
Nodes (15): chat_answer(), check(), FakeSession, live_watch_page(), main(), page(), reader(), Resp (+7 more)

### Community 29 - "Voice Input Tests (PC)"
Cohesion: 0.16
Nodes (12): check(), main(), test_an_echo_never_reaches_the_queue(), test_cyrillic_overrides_whisper(), test_degrades_to_silence(), test_gate_capture_contract(), test_hallucination_filter(), test_prompt_echo() (+4 more)

### Community 30 - "Chat Room and YouTube Web (PC) #30"
Cohesion: 0.16
Nodes (3): embedded_initial_data(), next_continuation(), YouTubeWebChat

### Community 31 - "Persona and Avatar Design (NB) #31"
Cohesion: 0.11
Nodes (14): Mood and tired inline tags, Ravyn Project Knowledge Base & Decision Document, Emotion system (mood/tired scales, cascade), Idle two-group system (User Focus / Wandering), Known problems and solutions table, Kokoro TTS (af_bella, +3 semitones, speed 0.95), Live2D face parameter map, Micro expressions and asymmetric brows (+6 more)

### Community 32 - "Worker and LLM Client (NB) #32"
Cohesion: 0.14
Nodes (9): _env(), start_worker(), main(), _env(), _env_bool(), _env_float(), _env_int(), get_settings() (+1 more)

### Community 33 - "Repeat Guard (NB)"
Cohesion: 0.18
Nodes (10): _grams(), RepeatGuard, similarity(), words(), check(), main(), test_the_detector(), test_the_worker_policy() (+2 more)

### Community 34 - "README Architecture Concepts (PC) #34"
Cohesion: 0.15
Nodes (20): app/settings.py Configuration, Audio Server (WebSocket to Godot), Chatterbox TTS Fallback, faster-qwen3-tts Wrapper, Ghost Mode (--ghost, SHOW protocol), Godot Avatar (ravyn-lynx-godot), Language Resolution (LANG_AMBIENT / LANG_REPLY), Qwen3-TTS Voice Cloning (+12 more)

### Community 36 - "Voice Gate and Hearing (PC) #36"
Cohesion: 0.12
Nodes (5): VoiceGate, on_audio(), listen(), on_utterance(), summarise()

### Community 37 - "Response Listener and Debug (PC)"
Cohesion: 0.19
Nodes (13): get(), debug_promo_status(), debug_sanitizer_check(), _clean_for_tts(), _run_async(), start_response_listener(), callback(), _handle() (+5 more)

### Community 38 - "Notebook Log Receiver (PC) #38"
Cohesion: 0.17
Nodes (7): LogReceiver, callback(), queue_arguments(), check(), main(), msg(), _ship()

### Community 40 - "Worker and LLM Client (NB) #40"
Cohesion: 0.24
Nodes (8): _avoid_repeat(), _check_numbers(), _clean_for_tts(), _finish(), _gate_fufu(), _gate_tch(), callback(), _ts()

### Community 42 - "Orchestration Design Notes (NB) #42"
Cohesion: 0.13
Nodes (10): Anti-repetition rule, Faster-Whisper STT (planned), Orchestration system (signal sources, priority, TTL), Silence filler and stunts.json, ANGLE (per-event instruction, replaces fixed template), GAME_EVENT_RULES bans restating the direction, data/memory.json (gitignored runtime state), Memory (get_history, add_exchange, user_notes, general_memory, donors) (+2 more)

### Community 43 - "Game State Helpers (PC)"
Cohesion: 0.16
Nodes (5): _clamp(), _mentions_smite(), _ordinal(), Player, Side

### Community 44 - "Notebook Log Receiver (PC) #44"
Cohesion: 0.30
Nodes (9): _split_first_chunk(), split_sentences(), check(), main(), test_no_stubs(), test_opening_still_starts_quickly(), test_short_lines_stay_whole(), test_the_cap_counts_sentences_not_chunks() (+1 more)

### Community 45 - "Voice Gate and Hearing (PC) #45"
Cohesion: 0.23
Nodes (7): addressed_to_her(), confident(), describe(), level(), main(), selftest(), verdict()

### Community 46 - "Worker and LLM Client (NB) #46"
Cohesion: 0.25
Nodes (9): _extract_value(), _handle_think_tags(), _post(), run_llm(), run_llm_simple(), _strip_tags(), _ts(), _compress_memory_async() (+1 more)

### Community 47 - "README Architecture Concepts (PC) #47"
Cohesion: 0.21
Nodes (13): StreamElements --replay Offline Path, Busy Watchdog (BUSY_TIMEOUT), Dispatcher (owns busy state), League Live Client Game Source, League Mode (--league), Priority Queue with TTL, Promos (follow/sub asks), Sanitizing with Blocklist (+5 more)

### Community 48 - "Utterance Lip Sync (PC)"
Cohesion: 0.19
Nodes (9): begin_utterance(), end_utterance(), send_face(), send_text_to_godot(), _line(), test_back_to_back_lines_do_not_flicker(), not_yet(), two_lines_apart() (+1 more)

### Community 49 - "Chat Room and YouTube Web (PC) #49"
Cohesion: 0.24
Nodes (7): _count(), _event(), from_api_item(), from_web_item(), parse_amount(), _simple(), message_text()

### Community 50 - "Number Check (NB)"
Cohesion: 0.23
Nodes (5): numbers_in(), unsupported(), without_sentences_naming(), check(), main()

### Community 51 - "Speech Filtering (PC)"
Cohesion: 0.24
Nodes (5): bare_name(), echoes_prompt(), looks_like_speech(), _normalise(), _words()

### Community 52 - "Persona and Avatar Design (NB) #52"
Cohesion: 0.24
Nodes (9): ravyn.request Queue, pika, llama-server (llama.cpp), RabbitMQ, tmux stack (start_stack.sh: LLM | WORKER | RABBIT | MONITOR), Notebook Worker, requests, run_llm (seed + temperature jitter) (+1 more)

### Community 54 - "Orchestration Design Notes (NB) #54"
Cohesion: 0.29
Nodes (6): Ravyn-Lynx Notebook LLM Service, Ravyn Mascot Job Priorities (alerts, chat, League co-commentary), Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py), Donors count note (counted, not appended), Ravyn notebook state (STATUS.md), ravyn-lynx-p/STATUS.md (full project document)

### Community 55 - "Request IDs and Game Memory (NB)"
Cohesion: 0.57
Nodes (6): check(), fresh(), main(), test_game_lines_are_bounded_and_reset(), test_game_lines_are_kept_apart(), test_history_is_withheld_from_game_events()

### Community 56 - "Logs Layout Docs (PC)"
Cohesion: 0.52
Nodes (6): Logs Directory Layout (pc/ nb/ history.csv), Notebook Worker Log (nb/), analyze_session.py Report, history.csv Running Table, join_logs.py Line-to-Prompt Join, Session Log (JSONL)

### Community 57 - "README Architecture Concepts (PC) #57"
Cohesion: 0.29
Nodes (7): ravyn.log Queue, Ravyn-Lynx PC Orchestrator, Ravyn Stream Mascot, ravyn-nb Notebook LLM Service, ravyn.response Queue, Response Listener, Temper (supportive/neutral/negative)

### Community 59 - "Persona and Avatar Design (NB) #59"
Cohesion: 0.29
Nodes (7): LEAGUE OF LEGENDS section, Non-League mode flag, Not built yet: Russian character, non-League mode, official vs abliterated A/B, joined log view, ravyn-lynx-p/orchestrator/session_log.py, req_id joins PC session log and worker log, Test suites (test_game_memory, test_persona_context, test_per_user_memory, test_worker_log), app/worker_log.py JSONL worker log

## Ambiguous Edges - Review These
- `Kokoro TTS (af_bella, +3 semitones, speed 0.95)` → `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)`  [AMBIGUOUS]
  ravyn_knowledge_base.md · relation: conceptually_related_to

## Knowledge Gaps
- **32 isolated node(s):** `ravyn-nb/app/worker_log.py`, `logs/history.csv`, `Chatterbox TTS fallback`, `StreamElements source (sources/stream_elements.py)`, `Champ select (LCU API) vs game start` (+27 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 564 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LolGameSource` connect `League Event Handling (PC)` to `Temper and Game Results (PC)`, `League Client Results (PC)`, `Dispatcher and Signals (PC)`, `App Startup and Settings (PC)`, `Session Log (PC)`, `Player Identity Resolution (PC)`, `Game State Facts (PC)`, `Owner Identity and Twitch (PC)`, `Champion Notes (PC)`, `Angle Chooser (PC)`, `Event Registration Tests (PC)`, `Kill Attribution Tests (PC)`, `Mock Sources and Wiring (PC)`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `SignalQueue` (e.g. with `Dispatcher` and `Signal`) actually correct?**
  _`SignalQueue` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ravyn-nb/app/worker_log.py`, `logs/history.csv`, `Chatterbox TTS fallback` to the rest of the system?**
  _32 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Session Analysis Tools (PC)` be split into smaller, more focused modules?**
  _Cohesion score 0.05322128851540616 - nodes in this community are weakly interconnected._
- **Why does `SignalQueue` connect `Mock Sources and Wiring (PC)` to `Temper and Game Results (PC)`, `StreamElements Alerts (PC)`, `Promo Asks (PC)`, `Dispatcher and Signals (PC)`, `App Startup and Settings (PC)`, `League Event Handling (PC)`, `YouTube API Chat (PC)`, `Owner Identity and Twitch (PC)`, `Angle Chooser (PC)`, `Sanitizer and Blocklist (PC)`, `Event Registration Tests (PC)`, `Kill Attribution Tests (PC)`, `Chat Room and YouTube Web (PC) #28`, `Voice Input Tests (PC)`, `Chat Room and YouTube Web (PC) #35`, `Speech Language Detection (PC)`, `Speech Filtering (PC)`, `Silence Filler (PC)`, `League Client Results (PC)`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `LolGameSource` (e.g. with `ChampionNotes` and `AngleChooser`) actually correct?**
  _`LolGameSource` has 9 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Kokoro TTS (af_bella, +3 semitones, speed 0.95)` and `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._