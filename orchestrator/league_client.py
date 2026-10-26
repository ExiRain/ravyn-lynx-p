"""
Who won — from the League CLIENT, for games the Live Client API never told us.

The Live Client API (the in-game one, `sources/lol_game.py`) reports the
result in its GameEnd event, and usually goes away before that event is read:
none of the three games on 2026-10-25 15:06 delivered one. A game with no
result scores no win or loss points, so temper — which is mostly results —
never left neutral all night.

The League client (the lobby, a different process) keeps an end-of-game stats
block for the post-game screen, after the game itself has closed. It is
authenticated with the lockfile the client writes into its install folder:

    name:pid:port:password:protocol

## The one uncertain thing in this file

The endpoint and field names are expected, not verified — the docs could not be
reached from where this was written. So: several spellings are tried, the first
block seen is logged in short so a wrong name is a one-line fix, and anything
that does not resolve leaves the result unknown. Never a guess (STATUS.md §7).
"""

from __future__ import annotations

from pathlib import Path

import requests

EOG_PATH = "/lol-end-of-game/v1/eog-stats-block"


class LeagueClient:
    def __init__(self, lockfile: Path | str):
        self.lockfile = Path(lockfile)
        self._logged = False
        self._warned_missing = False

    def _credentials(self) -> tuple[int, str] | None:
        try:
            parts = self.lockfile.read_text(encoding="utf-8").strip().split(":")
            return int(parts[2]), parts[3]
        except FileNotFoundError:
            if not self._warned_missing:
                self._warned_missing = True
                print(f"[client] No lockfile at {self.lockfile} — game results "
                      f"come from GameEnd only. Set RAVYN_LEAGUE_LOCKFILE if "
                      f"League is installed elsewhere.")
            return None
        except (OSError, IndexError, ValueError):
            return None     # client not running, or mid-write

    def eog(self) -> dict | None:
        """The end-of-game block, or None if there is none to read."""
        creds = self._credentials()
        if creds is None:
            return None
        port, password = creds
        try:
            resp = requests.get(f"https://127.0.0.1:{port}{EOG_PATH}",
                                auth=("riot", password), verify=False,
                                timeout=2)
        except Exception:
            return None
        if getattr(resp, "status_code", 0) != 200:
            return None
        try:
            block = resp.json()
        except Exception:
            return None
        if not isinstance(block, dict):
            return None
        if not self._logged:
            self._logged = True
            teams = [{k: t.get(k) for k in ("isPlayerTeam", "isWinningTeam")}
                     for t in block.get("teams") or [] if isinstance(t, dict)]
            stats = (block.get("localPlayer") or {}).get("stats") or {}
            print(f"[client] FIRST end-of-game block — check the field names: "
                  f"gameId={block.get('gameId')!r} teams={teams} "
                  f"WIN={stats.get('WIN')!r} LOSE={stats.get('LOSE')!r} "
                  f"keys={sorted(block)[:20]}")
        return block

    def game_id(self) -> object:
        block = self.eog()
        return block.get("gameId") if block else None


def result(block: dict | None) -> bool | None:
    """True for a win, False for a loss, None if the block does not say."""
    if not block:
        return None
    for team in block.get("teams") or []:
        if isinstance(team, dict) and team.get("isPlayerTeam") is True:
            won = team.get("isWinningTeam")
            if isinstance(won, bool):
                return won
    stats = (block.get("localPlayer") or {}).get("stats") or {}
    if stats.get("WIN") in (1, True):
        return True
    if stats.get("LOSE") in (1, True):
        return False
    return None
