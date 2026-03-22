from __future__ import annotations

import json
import time
import threading

import pika

from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


class Dispatcher:
    """
    Core dispatch loop.

    Pulls the highest-priority signal from the queue when Ravyn is idle,
    serializes it, and publishes to ravyn.request over RabbitMQ.
    Tracks busy/idle state via the ravyn.status queue.
    """

    def __init__(self, queue: SignalQueue):
        self.queue = queue
        self.settings = get_settings()
        self.busy = False
        self._busy_lock = threading.Lock()
        self._on_dispatch_callbacks: list = []
        self._running = True

    # ---------------------------------------------------------
    # busy state
    # ---------------------------------------------------------

    def set_busy(self, state: bool) -> None:
        with self._busy_lock:
            self.busy = state

    def is_busy(self) -> bool:
        with self._busy_lock:
            return self.busy

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

    def _dispatch(self, signal: Signal, channel) -> None:
        payload = json.dumps(signal.to_request())

        channel.basic_publish(
            exchange="",
            routing_key=self.settings.QUEUE_REQUEST,
            body=payload,
        )

        print(f"[dispatch] source={signal.source}  mode={signal.mode}  "
              f"skip_llm={signal.skip_llm}  text={signal.text[:60]}...")

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