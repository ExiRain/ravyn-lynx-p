"""
The notebook's log, written on the PC.

The notebook records what the model was ASKED (app/worker_log.py there); the
PC records what she SAID (orchestrator/session_log.py). They used to live on
two machines, and joining them meant an scp first. The notebook now sends
every line of its worker log on `ravyn.log`, and this files them here:

    logs/
      pc/   session-<date>-<time>.jsonl   this machine
      nb/   worker-<date>-<time>.jsonl    the notebook, line for line
      history.csv                          the running table of every game

Same file names as on the notebook, so a line can be found on either side.
The notebook keeps its own copy too; this is a mirror, not the only record.

Never raises into the rest of the app: a broken log is a missing file, not a
silent streamer. Runs on its own pika connection — BlockingConnection is not
thread-safe, so it cannot share the response listener's.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.settings import get_settings

settings = get_settings()

# The only names the notebook writes. Anything else in the "file" field is
# refused, so a message on the queue cannot write outside logs/nb/.
_SAFE_NAME = re.compile(r"^worker-[0-9]{8}-[0-9]{6}\.jsonl$")


def queue_arguments() -> dict:
    """Must match the notebook's declaration exactly, or RabbitMQ refuses."""
    return {"x-max-length": settings.LOG_QUEUE_MAX, "x-overflow": "drop-head"}


class LogReceiver:

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self._announced: set[str] = set()

    def write(self, body: bytes) -> bool:
        """One message from the notebook. True if it was filed."""
        try:
            msg = json.loads(body.decode("utf-8"))
            name = str(msg.get("file") or "")
            line = msg.get("line")
            if not _SAFE_NAME.match(name) or not isinstance(line, str):
                print(f"[nb-log] Refused a line for {name!r}")
                return False
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / name
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
            if name not in self._announced:
                self._announced.add(name)
                print(f"[nb-log] Notebook log -> {path}")
            return True
        except Exception as e:
            print(f"[nb-log] Could not write a notebook line: {e}")
            return False

    def run(self) -> None:
        """Blocking consumer, reconnecting. Run in a daemon thread."""
        import pika

        while True:
            try:
                credentials = pika.PlainCredentials(settings.RABBIT_USER,
                                                    settings.RABBIT_PASS)
                connection = pika.BlockingConnection(pika.ConnectionParameters(
                    host=settings.RABBIT_HOST, port=settings.RABBIT_PORT,
                    credentials=credentials, heartbeat=600))
                channel = connection.channel()
                channel.queue_declare(queue=settings.QUEUE_LOG,
                                      arguments=queue_arguments())

                def callback(ch, method, properties, body):
                    self.write(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(queue=settings.QUEUE_LOG,
                                      on_message_callback=callback)
                print(f"[nb-log] Receiving the notebook's log into "
                      f"{self.directory}")
                channel.start_consuming()
            except Exception as e:
                print(f"[nb-log] Connection lost ({e}) — retrying in 10s")
                time.sleep(10)
