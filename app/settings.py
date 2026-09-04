from dataclasses import dataclass


@dataclass
class Settings:

    NOTEBOOK_IP = "192.168.1.154"

    API_PORT = 9000

    RABBIT_HOST = NOTEBOOK_IP
    RABBIT_PORT = 5672

    RABBIT_USER = "ravyn"
    RABBIT_PASS = "103595"

    QUEUE_REQUEST = "ravyn.request"
    QUEUE_RESPONSE = "ravyn.response"

    # --- Dispatcher ---
    DISPATCH_POLL_INTERVAL = 0.1
    IDLE_POLL_INTERVAL = 0.5
    BUSY_TIMEOUT = 90.0                     # watchdog: force-idle if no response

    # --- Silence Filler ---
    SILENCE_THRESHOLD = 600.0
    SILENCE_MIN_INTERVAL = 120.0
    IMPROV_ENABLED = True
    QUOTE_ENABLED = True
    IMPROV_WEIGHT = 0.6

    # An idle thought that could not be said within a minute of being thought
    # is answering a silence that is over. Expire it rather than deliver it
    # once she is free — the gate already drops these outright while you are
    # talking, this covers the case where she was simply busy speaking.
    SILENCE_SIGNAL_TTL = 60.0

    # --- Voice gate (VAD) ---
    # Holds her back while you are talking. She never gets interrupted
    # mid-line; this only decides when she is allowed to START.
    VOICE_GATE_ENABLED = True
    VOICE_HOLD_AFTER_SPEECH = 5.0    # seconds of quiet before she may speak
    VOICE_VAD_THRESHOLD = 0.5        # Silero speech probability, 0-1
    VOICE_INPUT_DEVICE = None        # None = system default; int or name otherwise

    # Signals at or below this priority ignore the gate. Subs, follows and
    # donations are priority 1-2 — a viewer paid for that moment and it should
    # land promptly. Game chatter is 3+ and waits its turn.
    VOICE_INTERRUPT_PRIORITY = 2

    # At or above this priority a held signal is DISCARDED rather than queued.
    # Ambient chatter (silence_filler, priority 10) exists to fill silence; if
    # you are talking there is no silence to fill, and saying it once you stop
    # is saying it out of context. The filler will offer another one later.
    VOICE_AMBIENT_PRIORITY = 8

    # The gate is asked twice: once at the queue head before dispatch, and
    # again once her line is synthesised but before any of it plays. The
    # second check is the one that matters — the first decision is several
    # seconds stale by the time she opens her mouth (LLM round trip + TTS).
    # A ready line waits at the mouth this long; past it, it is dropped
    # rather than said late. Waiting here is cheap: the audio is already in
    # hand, so she starts the instant you stop.
    VOICE_MAX_DEFER = 8.0

    # The mic stays deaf this long after her audio ends. Speaker-to-mic
    # latency means her last syllable is still in the air; without the tail
    # it comes back, reads as you, and arms a fresh hold against nothing.
    VOICE_MUTE_TAIL = 0.35

    # --- Hearing him (sources/voice_in.py) ---
    # Whisper on the CPU at int8: zero VRAM, which is what lets it sit beside
    # the TTS on the 5080. The voice gate feeds it, so it runs once per
    # sentence rather than continuously — that is the job openWakeWord was
    # going to do, and the gate already does it.
    VOICE_INPUT_ENABLED = True
    # MUST be a multilingual model. The ".en" variants (tiny.en, base.en,
    # small.en) are English-only and will transcribe Russian as nonsense
    # English — do not "optimise" to one of those.
    #
    # Size matters far more for Russian than for English: tiny and base are
    # noticeably poor at it, so "small" is the sensible floor here even though
    # "base" would do for English alone.
    VOICE_STT_MODEL = "small"       # tiny / base / small / medium
    VOICE_STT_LANGUAGE = ""         # "" = auto-detect per utterance

    # Biases the decoder toward words it should expect. Two jobs: it stops
    # "Ravyn" coming back as "Raven" or "Равин", and it makes English champion
    # names inside a Russian sentence ("этот Garen меня убил") survive instead
    # of being transliterated — which is the realistic failure for a Russian
    # speaker playing an English client.
    #
    # Kept short deliberately. A long prompt makes Whisper hallucinate its own
    # vocabulary back at you on quiet audio.
    VOICE_STT_PROMPT = "Ravyn. League of Legends: Riven, Garen, jungle, mid, ADC, support, gank, drake, baron."
    VOICE_MIN_CHARS = 4             # shorter than this is not a sentence
    VOICE_TTL = 45.0                # an answer this late answers nothing

    # The microphone is his, so what it hears is attributed to him. There is
    # no speaker identification here — anyone else in the room is a guest on
    # his mic and will be treated as him.
    VOICE_SPEAKER = "exiledra1n"

    # --- Game reaction rate ---
    # Chance she says anything at all about an event. Frequent, low-stakes
    # things get filtered here so she is not commentating every second.
    # Anything absent defaults to 1.0 (always). MyDeath is deliberately absent:
    # lol_game._handle_death already coin-flips deaths 1-4, so a second roll
    # here would silence her twice over.
    REACTION_CHANCE = {
        # Ally deaths were the single loudest thing she did: 0.6 over roughly
        # twenty-five deaths in a losing game is fifteen comments about other
        # people dying. Halved, and then burst-decayed below.
        "AllyDeath":     0.3,
        "AllyKill":      0.25,
        "TurretKilled":  0.3,
        "HeraldKill":    0.5,
        "DragonKill":    0.7,
        "MyKill":        0.8,
        "InhibKilled":   0.9,
    }

    # Bursts are the real repetition problem, not the base rate. Five ally
    # deaths in one teamfight used to be five rolls at 0.6 — three comments
    # about the same thirty seconds. Each reaction of the SAME kind inside
    # REACTION_WINDOW (game seconds) multiplies the next one's chance by
    # REACTION_DECAY, so she reacts to the first, maybe the second, and lets
    # the rest go. The counter is per event type and decays on its own, so an
    # isolated ally death ten minutes later still lands at the full rate.
    #
    # At 0.6 base: 0.60, 0.33, 0.18, 0.10 ...
    REACTION_DECAY = 0.55
    REACTION_WINDOW = 90.0

    # A floor under the gap between ANY two game comments, in game seconds.
    # The per-type decay above stops her saying the same kind of thing twice,
    # but five different event types firing back to back still reads as
    # non-stop commentary — she finishes a line, the next queued event goes
    # straight out, and she talks continuously for a whole teamfight. Only
    # priority <= VOICE_INTERRUPT_PRIORITY skips this.
    GAME_MIN_GAP = 20.0

    # --- Twitch ---
    TWITCH_CHANNEL = "exiledra1n"

    # When Exiled himself types (or, later, speaks), his message does not
    # compete with chat. It skips the batch contest entirely — otherwise a
    # viewer's "hey ravyn, what do you think?" (score 20) beats his "gg"
    # (score 7) and HIS MESSAGE IS DISCARDED, not merely delayed.
    #
    # At 2 this also clears VOICE_INTERRUPT_PRIORITY, so she answers him even
    # inside the post-speech hold. That is the intent — he typed at her
    # deliberately — but it is the one side effect worth knowing about: if you
    # type and then immediately start talking, she will speak over you. Raise
    # to 3 to keep the hold and still beat ordinary chat.
    OWNER_PRIORITY = 2

    # The cheer on a win and the boo on a loss. Priority 1 is the highest
    # anything uses, so this beats even a sub landing in the same second, and
    # it is under VOICE_INTERRUPT_PRIORITY so the voice gate does not hold it —
    # if the game just ended you are probably mid-sentence about it, and that
    # is exactly when the noise belongs.
    #
    # These are `quote` signals: no LLM, straight to TTS, so the sound lands
    # while the screen is still grey rather than three seconds later. Her
    # actual line about the game follows behind it as a normal GameEnd.
    CHEER_PRIORITY = 1
    CHEER_TTL = 25.0

    # --- Language ---
    # Ambient: her own idle voice — silence filler, game reactions, promos.
    # Nobody addressed her, so there is nothing to mirror. Keep this fixed;
    # it is what stops her flipping language mid-stream.
    LANG_AMBIENT = "en"

    # Chance that a GAME gets her Russian voice instead. 0.0 disables it, 1.0
    # forces Russian; 0.5 is a coin flip.
    #
    # Rolled ONCE PER GAME, not per line. Per line would have her switching
    # language between a drake and the death that follows it, which is not a
    # bilingual streamer, it is a broken one. Per game gives a coherent sample
    # to judge her Russian by, which is the point of turning it on.
    #
    # Only her AMBIENT voice — game reactions, idle thoughts. Replies still
    # follow whoever spoke to her via LANG_REPLY, so a Russian chatter gets
    # Russian in an English game and vice versa.
    #
    # What is NOT translated: the angles, tones and themes stay English. They
    # are instructions to the model, not text she says, and a 201-language
    # model takes English direction to Russian output without help. Her
    # PERSONA is the real gap — banned openers, "fufu", the teammate ladder are
    # all English and none of them survive translation, so expect a Russian
    # game to sound flatter than an English one until that addendum exists.
    LANG_AMBIENT_RU_CHANCE = 0.5

    # Reply: how she answers someone who spoke to her.
    #   "en"        — always English
    #   "ru"        — always Russian (use this to test her Russian)
    #   "multilang" — the LLM mirrors whoever wrote to her
    #   "detect"    — decide from the message text before generating
    #
    # "detect" is the one that also works for TTS: it resolves the language
    # BEFORE the LLM runs, so the voice can be told too. With "multilang"
    # you only learn the language from her output.
    #
    # Under "detect" a person's language STICKS for the session: the first
    # message long enough to judge is remembered, and reused for the ones that
    # are not. Without that a Russian chatter gets Russian for "как дела" and
    # English for the "+" after it. A later real sentence in the other
    # language still switches her — someone changing language should be
    # followed, not corrected.
    #
    # Qwen3-TTS speaks Russian natively, so the voice follows. What is NOT
    # settled is whether the 9B writes her well in Russian, and her persona is
    # English throughout — banned openers, "fufu", the teammate vocabulary.
    # None of that survives translation. See §5.
    LANG_REPLY = "detect"

    # Known speakers, lowercase -> language. Overrides LANG_REPLY.
    # e.g. a Russian duo partner in Discord: {"someguy": "ru"}
    SPEAKER_LANG = {}

    # --- PC TTS ---
    TTS_ENABLED = True                      # False (or --no-tts) = silent mode
    TTS_DEVICE = "cuda"                     # "cuda" or "cpu"
    TTS_VOICE_REF = "data/ravyn_voice_ref.wav"   # reference wav for voice cloning

    # "qwen"       — Qwen3-TTS. Russian + English, better quality.
    # "chatterbox" — Chatterbox Turbo. English only. Fallback if qwen misbehaves.
    TTS_BACKEND = "qwen"

    TTS_QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

    # REQUIRED for cloning: exactly what is said in TTS_VOICE_REF, word for
    # word. Qwen aligns the reference audio against this transcript; a wrong
    # or empty one degrades the clone badly, so load() refuses to start
    # without it.
    TTS_QWEN_REF_TEXT = "Hello... I'm Ravyn, a fox spirit who watches over this stream. Do not test my patience."

    # "sdpa" works everywhere torch does. "flash_attention_2" is faster but
    # flash-attn is painful to build on Windows — only set it if you have it.
    TTS_QWEN_ATTN = "sdpa"
    AUDIO_SERVER_HOST = "0.0.0.0"
    AUDIO_SERVER_PORT = 9000                # Godot connects to ws://localhost:9000/ws/audio


def get_settings():
    return Settings()