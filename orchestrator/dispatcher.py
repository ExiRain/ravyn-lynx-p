from __future__ import annotations

import json
import time
import threading

import pika

from orchestrator import language
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


class Dispatcher:
    """
    Core dispatch loop.

    Pulls the highest-priority signal from the queue when Ravyn is idle,
    serializes it, and publishes to ravyn.request over RabbitMQ.

    Busy state is owned locally: set here on dispatch, cleared by
    services/response_listener.py once her audio has finished playing.
    """

    def __init__(self, queue: SignalQueue, voice_gate=None):
        self.queue = queue
        self.voice_gate = voice_gate
        self.settings = get_settings()
        self._last_hold_log = 0.0
        self.busy = False
        self._busy_since = 0.0
        self._inflight: Signal | None = None
        # Which language each chatter writes in, for this session. Detection
        # sees one message at a time, and half of chat is too short to judge.
        self.speakers = language.SpeakerMemory()
        self._busy_lock = threading.Lock()
        self._on_dispatch_callbacks: list = []
        self._running = True

    # ---------------------------------------------------------
    # busy state
    # ---------------------------------------------------------

    def set_busy(self, state: bool) -> None:
        with self._busy_lock:
            self.busy = state
            self._busy_since = time.time() if state else 0.0
            if not state:
                self._inflight = None

    def set_inflight(self, signal: Signal | None) -> None:
        with self._busy_lock:
            self._inflight = signal

    def inflight_priority(self) -> int:
        """
        Priority of the signal currently being generated, for the second gate
        check in the response listener. Exactly one signal is in flight at a
        time — the busy flag guarantees it — so this needs no request-protocol
        change to carry the priority to the notebook and back.

        Defaults to "ordinary, gate applies" if nothing is recorded.
        """
        with self._busy_lock:
            return self._inflight.priority if self._inflight else 5

    def is_busy(self) -> bool:
        """
        Busy with a watchdog. If the notebook dies mid-request, or a response
        never makes it back, nothing would ever clear the flag and Ravyn would
        go permanently silent. Time it out instead.
        """
        with self._busy_lock:
            if not self.busy:
                return False

            elapsed = time.time() - self._busy_since
            if elapsed > self.settings.BUSY_TIMEOUT:
                print(f"[dispatcher] Busy for {elapsed:.0f}s with no response — "
                      f"clearing (lost message?)")
                self.busy = False
                self._busy_since = 0.0
                self._inflight = None
                return False

            return True

    # ---------------------------------------------------------
    # callbacks — silence filler hooks into this to reset timer
    # ---------------------------------------------------------

    def on_dispatch(self, callback) -> None:
        """Register a callback invoked after every successful dispatch."""
        self._on_dispatch_callbacks.append(callback)

    def _notify_dispatch(self, signal: Signal) -> None:
        for cb in self._on_dispatch_callbacks:
            try:
                cb(signal)
            except Exception as e:
                print(f"[dispatcher] Callback error: {e}")

    # ---------------------------------------------------------
    # rabbit connection (publish side)
    # ---------------------------------------------------------

    def _connect_rabbit(self) -> tuple:
        s = self.settings

        credentials = pika.PlainCredentials(s.RABBIT_USER, s.RABBIT_PASS)

        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=s.RABBIT_HOST,
                port=s.RABBIT_PORT,
                credentials=credentials,
                heartbeat=60,
                blocked_connection_timeout=30,
            )
        )

        channel = connection.channel()
        channel.queue_declare(queue=s.QUEUE_REQUEST)

        return connection, channel

    # ---------------------------------------------------------
    # dispatch a single signal
    # ---------------------------------------------------------

    def _gate_holds(self, signal: Signal) -> bool:
        """
        True if this signal must wait because the streamer is talking.

        This is the *first* of two gate checks and the weaker one. All it buys
        is not paying an LLM round trip and a TTS pass for a line she will not
        be allowed to say. By the time that line exists, seconds have gone by
        and this answer is stale, so the decision that actually keeps her off
        your voice is the one in services/response_listener.py, taken with the
        audio already in hand.

        Checked against the queue head before popping, so a held signal keeps
        its place and its TTL keeps running — a game reaction that waits out
        its window expires instead of arriving late and out of context.
        """
        if self.voice_gate is None:
            return False

        # subs, follows, donations cut through
        if signal.priority <= self.settings.VOICE_INTERRUPT_PRIORITY:
            return False

        if not self.voice_gate.should_hold():
            return False

        # Ambient gets its own "dropping" line from the caller — logging a
        # hold for something that is about to be discarded reads as a bug.
        if signal.priority < self.settings.VOICE_AMBIENT_PRIORITY:
            now = time.time()
            if now - self._last_hold_log > 3.0:
                self._last_hold_log = now
                print(f"[dispatcher] Holding {signal.source} — you are talking")

        return True

    def _resolve_lang(self, signal: Signal) -> None:
        """
        Stamp the language on a signal just before it goes out.

        Done here rather than in each source so no source can forget: every
        request that reaches the notebook carries a resolved language. A
        source that genuinely knows better sets signal.lang itself and this
        leaves it alone.
        """
        s = self.settings
        signal.lang = language.resolve(
            source=signal.source,
            text=signal.text,
            context=signal.context,
            explicit=signal.lang,
            ambient=s.LANG_AMBIENT,
            reply_policy=s.LANG_REPLY,
            speaker_langs=s.SPEAKER_LANG,
            remembered=self.speakers,
        )

    def _dispatch(self, signal: Signal, channel) -> None:
        self._resolve_lang(signal)
        payload = json.dumps(signal.to_request())

        channel.basic_publish(
            exchange="",
            routing_key=self.settings.QUEUE_REQUEST,
            body=payload,
        )

        print(f"[dispatch] source={signal.source}  mode={signal.mode}  "
              f"lang={signal.lang}  skip_llm={signal.skip_llm}  "
              f"text={signal.text[:60]}...")

    # ---------------------------------------------------------
    # main loop
    # ---------------------------------------------------------

    def run(self) -> None:
        """Blocking main loop. Run in main thread or dedicated thread."""

        s = self.settings

        print("[dispatcher] Connecting to RabbitMQ...")
        connection, channel = self._connect_rabbit()
        print("[dispatcher] Ready — entering dispatch loop")

        try:
            while self._running:

                # wait while busy — use connection.sleep to keep heartbeat alive
                if self.is_busy():
                    try:
                        connection.sleep(s.DISPATCH_POLL_INTERVAL)
                    except Exception:
                        pass
                    continue

                # peek before popping: if the gate holds this one it keeps
                # its place in the queue and carries on ageing out
                head = self.queue.peek()
                if head is not None and self._gate_holds(head):

                    # Ambient chatter is discarded, not deferred. It exists to
                    # fill silence; while you are talking there is no silence
                    # to fill, and delivering it the moment you stop is the
                    # worst of both — she interrupts the pause after your
                    # thought with a remark about nothing. The filler offers
                    # another one on its own timer soon enough.
                    if head.priority >= s.VOICE_AMBIENT_PRIORITY:
                        dropped = self.queue.pop_head_if(head)
                        if dropped is not None:
                            print(f"[dispatcher] Dropping {dropped.source} "
                                  f"(ambient) — you are talking")
                            continue    # look at the new head straight away

                    try:
                        connection.sleep(s.DISPATCH_POLL_INTERVAL)
                    except Exception:
                        pass
                    continue

                # try to get next signal
                signal = self.queue.pop()

                if signal is None:
                    try:
                        connection.sleep(s.IDLE_POLL_INTERVAL)
                    except Exception:
                        pass
                    continue

                # set busy before publishing to prevent double-dispatch
                self.set_busy(True)
                self.set_inflight(signal)

                try:
                    self._dispatch(signal, channel)
                    self._notify_dispatch(signal)
                except pika.exceptions.AMQPError as e:
                    print(f"[dispatcher] Rabbit error: {e} — reconnecting")
                    self.set_busy(False)
                    try:
                        connection.close()
                    except Exception:
                        pass
                    time.sleep(1)
                    connection, channel = self._connect_rabbit()

        except KeyboardInterrupt:
            print("[dispatcher] Shutting down")
        finally:
            self._running = False
            try:
                connection.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False