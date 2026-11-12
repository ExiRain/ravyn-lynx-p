# Logs

    logs/
      pc/          session-<date>-<time>.jsonl   what she SAID (this machine)
      nb/          worker-<date>-<time>.jsonl    what the model was ASKED
                                                 (sent from the notebook)
      godot/       godot-<date>-<time>.jsonl     what her face and body DID
                   review-<date>-<time>.txt      per game: lines where it was off
                                                 (sent from Godot)
      history.csv  the running table of every game

Both halves of a session land here on the PC: the notebook sends each line of
its worker log over RabbitMQ (`ravyn.log`) as it writes it, and
`services/log_receiver.py` files it under `nb/` with the notebook's own file
name. The notebook keeps its own copy as well.

    python tools/analyze_session.py      # newest session in pc/
    python tools/join_logs.py            # newest session joined with its nb/ and godot/ logs

The avatar's log is one record per action — blinks, looks, ear perks and
jiggles, expressions, micro expressions, the start and end of each line,
mood, visibility — sent by Godot down the WebSocket it already has open
(`ravyn-godot/scripts/action_log.gd`) and filed by `services/godot_log.py`.
It holds no viewer data.

At every game end the PC checks each line she spoke that game against what
her avatar did — focus on him, expression for the mood sent, eyes and head,
fade — and writes what was off to `godot/review-<date>-<time>.txt`
(`orchestrator/avatar_review.py`). Nothing to run.

## Why pc/ and nb/ are not committed

They contain viewer names, their chat messages, donation messages and the
notes she keeps on people. This repository is public, so `.gitignore` keeps
them out and only `history.csv` (numbers and her own phrasing) is tracked.

To keep the full logs in git for history, push them to a **private** repo
instead, for example:

    cd logs
    git init
    git remote add origin git@github.com:<you>/ravyn-logs.git   # private
    git add pc nb history.csv
    git commit -m "logs"
    git push -u origin main
