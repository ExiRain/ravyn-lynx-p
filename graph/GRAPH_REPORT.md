# Graph Report - ravyn-lynx-p  (2026-11-07)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1758 nodes · 4434 edges · 89 communities (61 shown, 28 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 370 edges (avg confidence: 0.86)
- Token cost: 304,146 input · 0 output

## Community Hubs (Navigation)
- Session Log (PC) #0
- Per-Person Memory (NB)
- test_temper.py (PC)
- test_promo.py (PC)
- Dispatcher (PC)
- Chat Room and YouTube Web (PC)
- STATUS Design Notes (PC)
- pathlib (PC) #7
- README Architecture Concepts (PC)
- YouTube API Chat (PC)
- Event Registration Tests (PC)
- Owner Identity and Twitch (PC) #11
- Audio Server (PC) #12
- LolGameSource (PC)
- Champion Notes (PC)
- StreamElements Alerts (PC) #15
- Game State Facts (PC)
- Language Resolution (PC)
- Ghost Mode Tests (PC) #18
- analyze_session.py (PC) #19
- Live and Web Chat Tools (PC)
- TTS Engines (PC)
- Signal (PC)
- Kill Attribution Tests (PC)
- Angle Chooser (PC)
- Output Filters (NB)
- SignalQueue (PC) #26
- StreamElements Alerts (PC) #27
- join_logs.py (PC)
- Repeat Guard (NB)
- analyze_session.py (PC) #30
- App Startup and Settings (PC)
- test_contract.py (PC)
- Worker and LLM Client (NB) #33
- Response Listener and Debug (PC)
- main (PC)
- VoiceGate (PC)
- test_tone_and_theme.py (PC)
- log_receiver.py (PC) #39
- Sanitizer and Blocklist (PC) #40
- Log Join Tests (PC)
- Persona and Avatar Design (NB) #42
- SignalQueue (PC) #43
- Worker and LLM Client (NB) #44
- Prompt Framing (NB) #45
- Session Log (PC) #46
- response_listener.py (PC)
- SignalQueue (PC) #48
- Worker and LLM Client (NB) #49
- Prompt Framing (NB) #50
- tone.py (PC)
- Silence Filler (PC)
- Orchestration Design Notes (NB)
- Player Scoreboard Rows (PC)
- pathlib (NB) #55
- SignalQueue (PC) #56
- Persona and Avatar Design (NB) #57
- game_angles.py (PC)
- game_state.py (PC)
- League Client Results (PC)
- Sanitizer and Blocklist (PC) #61
- Owner Identity and Twitch (PC) #62
- pathlib (PC) #63
- Persona and Avatar Design (NB) #64
- Sanitizer and Blocklist (PC) #65
- ToneLadder (PC)
- Worker Report Tool (NB)
- log_receiver.py (PC) #68
- Sanitizer and Blocklist (PC) #69
- Ghost Mode Tests (PC) #70
- Ghost Mode Tests (PC) #71
- pathlib (NB) #72
- game_theme.py (PC)
- Audio Server (PC) #74
- Ghost Mode Tests (PC) #75
- Rabbit Channel Fake (PC)
- Venv and Service Scripts (NB)
- pathlib (PC) #79
- Persona and Avatar Design (NB) #80
- TTS Setup on RTX 5080 (PC)
- Ghost Mode Tests (PC) #82
- LLM Start Script (NB)
- Stack Start Script (NB)
- Stack Stop Script (NB)
- Pydantic Dependency (NB)

## God Nodes (most connected - your core abstractions)
1. `SignalQueue` - 103 edges
2. `LolGameSource` - 68 edges
3. `Signal` - 66 edges
4. `GameState` - 57 edges
5. `Temper` - 48 edges
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
- `ChatRoom` --uses--> `SignalQueue`  [INFERRED]
  sources/chat_room.py → orchestrator/priority_queue.py
- `godot_sees()` --uses--> `Settings`  [INFERRED]
  tests/test_ghost.py → app/settings.py
- `test_she_starts_hidden()` --uses--> `Settings`  [INFERRED]
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

## Communities (89 total, 28 thin omitted)

### Community 0 - "Session Log (PC) #0"
Cohesion: 0.06
Nodes (49): init(), _iso(), SessionLog, console_lines(), check(), game_signal(), last_line(), main() (+41 more)

### Community 1 - "Per-Person Memory (NB)"
Cohesion: 0.05
Nodes (32): build_messages(), MemoryManager, check(), fresh(), main(), test_game_lines_are_bounded_and_reset(), test_game_lines_are_kept_apart(), test_history_is_withheld_from_game_events() (+24 more)

### Community 2 - "test_temper.py (PC)"
Cohesion: 0.09
Nodes (25): GameResult, Temper, _step_down(), block(), check(), ended_without_gameend(), FakeClient, main() (+17 more)

### Community 3 - "test_promo.py (PC)"
Cohesion: 0.09
Nodes (26): Settings, _load(), PromoSource, check(), FakeRandom, game(), main(), ready() (+18 more)

### Community 4 - "Dispatcher (PC)"
Cohesion: 0.06
Nodes (11): Dispatcher, check(), deliver(), main(), RecordingGate, StubGate, StubTTS, test_dispatch_policy() (+3 more)

### Community 5 - "Chat Room and YouTube Web (PC)"
Cohesion: 0.09
Nodes (18): embedded_initial_data(), next_continuation(), YouTubeWebChat, chat_answer(), check(), FakeSession, live_watch_page(), main() (+10 more)

### Community 6 - "STATUS Design Notes (PC)"
Cohesion: 0.05
Nodes (39): audio_server (services/audio_server.py), Burst decay (REACTION_DECAY / REACTION_WINDOW), Champ select (LCU API) vs game start, champion_notes (data/champions.json, orchestrator/champion_notes.py), Cheer and boo quotes, Cubism export trap (non-resource file filters), Dispatcher (dispatcher.py), faster-qwen3-tts (+31 more)

### Community 7 - "pathlib (PC) #7"
Cohesion: 0.08
Nodes (6): get_settings(), normalise(), result(), _collapse(), _is_sayable(), _speakable_name()

### Community 8 - "README Architecture Concepts (PC)"
Cohesion: 0.07
Nodes (40): ravyn.log Queue, StreamElements --replay Offline Path, app/settings.py Configuration, Audio Server (WebSocket to Godot), Busy Watchdog (BUSY_TIMEOUT), Chatterbox TTS Fallback, Dispatcher (owns busy state), faster-qwen3-tts Wrapper (+32 more)

### Community 9 - "YouTube API Chat (PC)"
Cohesion: 0.12
Nodes (14): YouTubeChatSource, check(), error(), FakeYouTube, main(), message(), page(), Resp (+6 more)

### Community 10 - "Event Registration Tests (PC)"
Cohesion: 0.12
Nodes (24): _count(), _event(), from_api_item(), from_web_item(), parse_amount(), _simple(), message_text(), activity() (+16 more)

### Community 11 - "Owner Identity and Twitch (PC) #11"
Cohesion: 0.10
Nodes (11): Identity, normalise(), score_message(), TwitchChatSource, check(), main(), test_chat_without_identity_is_unchanged(), test_his_message_is_never_dropped() (+3 more)

### Community 12 - "Audio Server (PC) #12"
Cohesion: 0.09
Nodes (17): begin_utterance(), _cancel_fade(), _compute_envelope(), end_utterance(), _fade_after(), fade_out(), _get_phonemes(), _get_phonemizer() (+9 more)

### Community 13 - "LolGameSource (PC)"
Cohesion: 0.09
Nodes (3): LolGameSource, vanished_game(), words_for()

### Community 14 - "Champion Notes (PC)"
Cohesion: 0.14
Nodes (15): ChampionNotes, ChampionRead, is_placeholder(), key(), _real(), check(), load(), main() (+7 more)

### Community 15 - "StreamElements Alerts (PC) #15"
Cohesion: 0.11
Nodes (3): main(), replay(), StreamElementsSource

### Community 17 - "Language Resolution (PC)"
Cohesion: 0.15
Nodes (15): confident(), cyrillic_ratio(), detect_lang(), is_ambient(), resolve(), SpeakerMemory, check(), main() (+7 more)

### Community 18 - "Ghost Mode Tests (PC) #18"
Cohesion: 0.14
Nodes (15): check(), FakeGodot, fresh_ghost_state(), godot_sees(), main(), _run(), test_amplitude_still_drives_the_mouth(), test_it_is_only_about_her_avatar() (+7 more)

### Community 19 - "analyze_session.py (PC) #19"
Cohesion: 0.10
Nodes (15): logs/history.csv, Session log (orchestrator/session_log.py), orchestrator/session_metrics.py, bar(), _jsonable(), load(), main(), print_comparison() (+7 more)

### Community 20 - "Live and Web Chat Tools (PC)"
Cohesion: 0.13
Nodes (9): _clean_for_tts(), embedded_client(), main(), _activity(), _get(), main(), _post(), interactive() (+1 more)

### Community 21 - "TTS Engines (PC)"
Cohesion: 0.12
Nodes (5): build_engine(), ChatterboxEngine, QwenTTSEngine, _to_wav_bytes(), TTSEngine

### Community 22 - "Signal (PC)"
Cohesion: 0.12
Nodes (3): Signal, ChatRoom, MockEventSource

### Community 23 - "Kill Attribution Tests (PC)"
Cohesion: 0.19
Nodes (17): start(), _attribution_cases(), check(), main(), real_game(), row(), source(), test_every_game_is_counted() (+9 more)

### Community 24 - "Angle Chooser (PC)"
Cohesion: 0.19
Nodes (13): AngleChooser, check(), main(), snapshot(), test_angle_variety(), test_angles_only_fire_on_true_facts(), test_burst_decay(), test_cheer_and_boo() (+5 more)

### Community 25 - "Output Filters (NB)"
Cohesion: 0.20
Nodes (17): clean(), _norm(), Result, _sentences(), _strip(), Tally, check(), main() (+9 more)

### Community 26 - "SignalQueue (PC) #26"
Cohesion: 0.16
Nodes (12): check(), main(), test_an_echo_never_reaches_the_queue(), test_cyrillic_overrides_whisper(), test_degrades_to_silence(), test_gate_capture_contract(), test_hallucination_filter(), test_prompt_echo() (+4 more)

### Community 27 - "StreamElements Alerts (PC) #27"
Cohesion: 0.31
Nodes (19): _symbol(), check(), main(), source(), test_a_blocked_name_or_message(), test_a_small_tip_does_not(), test_a_tip_reads_its_message(), test_alert_types() (+11 more)

### Community 28 - "join_logs.py (PC)"
Cohesion: 0.15
Nodes (12): knob(), said(), ravyn-nb/app/worker_log.py, newest_log(), _print_transcript(), diagnose(), load_worker(), main() (+4 more)

### Community 29 - "Repeat Guard (NB)"
Cohesion: 0.18
Nodes (10): _grams(), RepeatGuard, similarity(), words(), check(), main(), test_the_detector(), test_the_worker_policy() (+2 more)

### Community 30 - "analyze_session.py (PC) #30"
Cohesion: 0.16
Nodes (11): analyse(), append_history(), cluster(), _contains(), _longest_streak(), normalise(), phrases(), read_history() (+3 more)

### Community 32 - "test_contract.py (PC)"
Cohesion: 0.13
Nodes (6): _log_expired(), SignalQueue, Channel, check(), main(), sent()

### Community 33 - "Worker and LLM Client (NB) #33"
Cohesion: 0.15
Nodes (9): _env(), start_worker(), main(), _env(), _env_bool(), _env_float(), _env_int(), get_settings() (+1 more)

### Community 34 - "Response Listener and Debug (PC)"
Cohesion: 0.18
Nodes (13): get(), debug_promo_status(), debug_sanitizer_check(), has_clients(), _run_async(), start_response_listener(), callback(), _handle() (+5 more)

### Community 35 - "main (PC)"
Cohesion: 0.13
Nodes (5): main(), register_promo_injector(), register_sanitizer(), MockChatSource, MockGameSource

### Community 37 - "VoiceGate (PC)"
Cohesion: 0.12
Nodes (5): VoiceGate, on_audio(), listen(), on_utterance(), summarise()

### Community 38 - "test_tone_and_theme.py (PC)"
Cohesion: 0.22
Nodes (12): read_death(), _shift_tone(), check(), main(), tags_from(), test_rulebook(), test_russian_mixing(), test_teammate_ladder() (+4 more)

### Community 39 - "log_receiver.py (PC) #39"
Cohesion: 0.17
Nodes (7): LogReceiver, callback(), queue_arguments(), check(), main(), msg(), _ship()

### Community 40 - "Sanitizer and Blocklist (PC) #40"
Cohesion: 0.31
Nodes (14): check(), dispatcher_with(), main(), sanitizer(), test_blocklist_matching(), test_both_blocked_and_the_tally(), test_folding(), test_messages() (+6 more)

### Community 41 - "Log Join Tests (PC)"
Cohesion: 0.37
Nodes (13): check(), main(), nb_line(), pc_line(), test_a_filter_took_the_difference(), test_it_runs_end_to_end(), test_loading_and_matching(), test_the_angle_never_arrived() (+5 more)

### Community 42 - "Persona and Avatar Design (NB) #42"
Cohesion: 0.15
Nodes (12): Mood and tired inline tags, Ravyn Project Knowledge Base & Decision Document, Emotion system (mood/tired scales, cascade), Idle two-group system (User Focus / Wandering), Known problems and solutions table, Kokoro TTS (af_bella, +3 semitones, speed 0.95), Live2D face parameter map, Micro expressions and asymmetric brows (+4 more)

### Community 44 - "Worker and LLM Client (NB) #44"
Cohesion: 0.23
Nodes (9): _avoid_repeat(), _check_numbers(), _clean_for_tts(), _finish(), _gate_fufu(), _gate_tch(), _note_donation(), callback() (+1 more)

### Community 45 - "Prompt Framing (NB) #45"
Cohesion: 0.15
Nodes (10): _build_recent_chat_block(), _frame_signal(), angled(), framed(), _load_appearance(), _without_league(), is_owner flag from data/identity.json, player_notes (Exiled's claims from champions.json) (+2 more)

### Community 46 - "Session Log (PC) #46"
Cohesion: 0.27
Nodes (5): bridges(), edge(), find_line(), main(), run()

### Community 47 - "response_listener.py (PC)"
Cohesion: 0.30
Nodes (9): _split_first_chunk(), split_sentences(), check(), main(), test_no_stubs(), test_opening_still_starts_quickly(), test_short_lines_stay_whole(), test_the_cap_counts_sentences_not_chunks() (+1 more)

### Community 48 - "SignalQueue (PC) #48"
Cohesion: 0.23
Nodes (7): addressed_to_her(), confident(), describe(), level(), main(), selftest(), verdict()

### Community 49 - "Worker and LLM Client (NB) #49"
Cohesion: 0.25
Nodes (9): _extract_value(), _handle_think_tags(), _post(), run_llm(), run_llm_simple(), _strip_tags(), _ts(), _compress_memory_async() (+1 more)

### Community 50 - "Prompt Framing (NB) #50"
Cohesion: 0.16
Nodes (13): fufu signature laugh rules, Hard rules (2-3 sentences, no emoji, never break character), Never write in third person / no stage directions, Ravyn system prompt (persona), tch is rationed, Teammate words injected by game events, Temper-driven loyalty to Exiled, _gate_fufu (one per eight responses, never on game events) (+5 more)

### Community 51 - "tone.py (PC)"
Cohesion: 0.22
Nodes (5): instruction(), read_kill(), read_objective_participation(), teammate_rank(), Verdict

### Community 52 - "Silence Filler (PC)"
Cohesion: 0.24
Nodes (4): SilenceFiller, check(), gaps(), main()

### Community 53 - "Orchestration Design Notes (NB)"
Cohesion: 0.15
Nodes (9): Anti-repetition rule, Faster-Whisper STT (planned), Orchestration system (signal sources, priority, TTL), Silence filler and stunts.json, ANGLE (per-event instruction, replaces fixed template), GAME_EVENT_RULES bans restating the direction, Memory (get_history, add_exchange, user_notes, general_memory, donors), recent_game_lines / get_repetition_guard (+1 more)

### Community 55 - "pathlib (NB) #55"
Cohesion: 0.26
Nodes (5): numbers_in(), unsupported(), without_sentences_naming(), check(), main()

### Community 56 - "SignalQueue (PC) #56"
Cohesion: 0.24
Nodes (5): bare_name(), echoes_prompt(), looks_like_speech(), _normalise(), _words()

### Community 57 - "Persona and Avatar Design (NB) #57"
Cohesion: 0.24
Nodes (9): ravyn.request Queue, pika, llama-server (llama.cpp), RabbitMQ, tmux stack (start_stack.sh: LLM | WORKER | RABBIT | MONITOR), Notebook Worker, requests, run_llm (seed + temperature jitter) (+1 more)

### Community 58 - "game_angles.py (PC)"
Cohesion: 0.24
Nodes (3): _always(), Angle, _safe()

### Community 59 - "game_state.py (PC)"
Cohesion: 0.20
Nodes (4): _clamp(), _mentions_smite(), _ordinal(), Side

### Community 61 - "Sanitizer and Blocklist (PC) #61"
Cohesion: 0.27
Nodes (3): Blocklist, fold(), _load_lines()

### Community 64 - "Persona and Avatar Design (NB) #64"
Cohesion: 0.22
Nodes (7): Ravyn-Lynx Notebook LLM Service, Ravyn Mascot Job Priorities (alerts, chat, League co-commentary), Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py), Donors count note (counted, not appended), data/memory.json (gitignored runtime state), Ravyn notebook state (STATUS.md), ravyn-lynx-p/STATUS.md (full project document)

### Community 67 - "Worker Report Tool (NB)"
Cohesion: 0.25
Nodes (7): LEAGUE OF LEGENDS section, Non-League mode flag, Not built yet: Russian character, non-League mode, official vs abliterated A/B, joined log view, ravyn-lynx-p/orchestrator/session_log.py, req_id joins PC session log and worker log, Test suites (test_game_memory, test_persona_context, test_per_user_memory, test_worker_log), app/worker_log.py JSONL worker log

### Community 68 - "log_receiver.py (PC) #68"
Cohesion: 0.52
Nodes (6): Logs Directory Layout (pc/ nb/ history.csv), Notebook Worker Log (nb/), analyze_session.py Report, history.csv Running Table, join_logs.py Line-to-Prompt Join, Session Log (JSONL)

### Community 75 - "Ghost Mode Tests (PC) #75"
Cohesion: 0.60
Nodes (5): _line(), test_back_to_back_lines_do_not_flicker(), not_yet(), two_lines_apart(), two_lines_close()

### Community 79 - "pathlib (PC) #79"
Cohesion: 0.50
Nodes (3): check(), main(), snapshot()

## Ambiguous Edges - Review These
- `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)` → `Kokoro TTS (af_bella, +3 semitones, speed 0.95)`  [AMBIGUOUS]
  ravyn_knowledge_base.md · relation: conceptually_related_to

## Knowledge Gaps
- **32 isolated node(s):** `logs/history.csv`, `ravyn-nb/app/worker_log.py`, `Chatterbox TTS fallback`, `StreamElements source (sources/stream_elements.py)`, `Champ select (LCU API) vs game start` (+27 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 576 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **28 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SignalQueue` connect `test_contract.py (PC)` to `test_temper.py (PC)`, `test_promo.py (PC)`, `Dispatcher (PC)`, `Chat Room and YouTube Web (PC)`, `pathlib (PC) #7`, `YouTube API Chat (PC)`, `Event Registration Tests (PC)`, `Owner Identity and Twitch (PC) #11`, `LolGameSource (PC)`, `StreamElements Alerts (PC) #15`, `Live and Web Chat Tools (PC)`, `Signal (PC)`, `Kill Attribution Tests (PC)`, `Angle Chooser (PC)`, `SignalQueue (PC) #26`, `StreamElements Alerts (PC) #27`, `App Startup and Settings (PC)`, `main (PC)`, `Sanitizer and Blocklist (PC) #40`, `SignalQueue (PC) #43`, `Session Log (PC) #46`, `Silence Filler (PC)`, `SignalQueue (PC) #56`, `League Client Results (PC)`, `Owner Identity and Twitch (PC) #62`, `Sanitizer and Blocklist (PC) #69`, `pathlib (PC) #79`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `SignalQueue` (e.g. with `Signal` and `ChatRoom`) actually correct?**
  _`SignalQueue` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `logs/history.csv`, `ravyn-nb/app/worker_log.py`, `Chatterbox TTS fallback` to the rest of the system?**
  _32 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Session Log (PC) #0` be split into smaller, more focused modules?**
  _Cohesion score 0.05960007765482431 - nodes in this community are weakly interconnected._
- **Why does `LolGameSource` connect `LolGameSource (PC)` to `test_contract.py (PC)`, `test_temper.py (PC)`, `main (PC)`, `League Event Handling (PC) #36`, `pathlib (PC) #7`, `Event Registration Tests (PC)`, `Owner Identity and Twitch (PC) #11`, `Champion Notes (PC)`, `League Event Handling (PC) #78`, `Game State Facts (PC)`, `pathlib (PC) #79`, `tone.py (PC)`, `Signal (PC)`, `Kill Attribution Tests (PC)`, `Angle Chooser (PC)`, `League Client Results (PC)`, `pathlib (PC) #63`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `LolGameSource` (e.g. with `ChampionNotes` and `AngleChooser`) actually correct?**
  _`LolGameSource` has 9 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Removed TTS/audio adapters (qwen_tts.py, stream_api.py, audio_stream_server.py)` and `Kokoro TTS (af_bella, +3 semitones, speed 0.95)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._