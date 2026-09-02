"""
League of Legends Live Game source.

- Loads quotes from data/game_quotes.json
- Uses EventTime from game API for staleness (not wall clock)
- Kill coalescing with quote seeds from pools
- Death tracking per game with trade detection
- Completely disables silence filler during games

Every event carries the measured game state (`orchestrator/game_state.py`) and
an angle chosen from it (`orchestrator/game_angles.py`). Before that, the poll
was thrown away and each event reached the notebook as champion name plus a
seed, so fifteen ally deaths a game produced fifteen near-identical prompts.
See STATUS.md §7.
"""

from __future__ import annotations

import json
import random
import time
import requests
import urllib3
from pathlib import Path

from orchestrator.champion_notes import ChampionNotes
from orchestrator.game_angles import AngleChooser
from orchestrator.game_state import GameState
from orchestrator.models import Signal
from orchestrator.priority_queue import SignalQueue
from app.settings import get_settings


settings = get_settings()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
POLL_INTERVAL = 2.0
IDLE_INTERVAL = 10.0

KILL_COALESCE_WINDOW = 5.0
STALE_THRESHOLD = 10.0       # seconds in game time — older events dropped at detection

TEAMFIGHT_WINDOW = 8.0
TEAMFIGHT_MIN_KILLS = 3

# Game seconds. Ally deaths inside this window count as one bleed rather than
# separate events — it is what lets her say "that is the third one" instead of
# saying "typical" three times.
ALLY_DEATH_BURST_WINDOW = 30.0

MULTIKILL_NAMES = {2: "double", 3: "triple", 4: "quadra", 5: "penta"}


EVENT_CONFIG = {
    "GameStart":         {"priority": 2, "ttl": None},
    "GameEnd":           {"priority": 2, "ttl": None},
    "MyKill":            {"priority": 3, "ttl": 15},
    "MyKillSpree":       {"priority": 3, "ttl": 15},
    "MyDeath":           {"priority": 3, "ttl": 15},
    "MyDeathRoast":      {"priority": 3, "ttl": 15},
    "MyMultikill":       {"priority": 2, "ttl": 15},
    "AllyKill":          {"priority": 6, "ttl": 10},
    "AllyDeath":         {"priority": 5, "ttl": 10},
    "BaronKill":         {"priority": 3, "ttl": 20},
    "DragonKill":        {"priority": 5, "ttl": 15},
    "HeraldKill":        {"priority": 5, "ttl": 15},
    "InhibKilled":       {"priority": 4, "ttl": 15},
    "TurretKilled":      {"priority": 6, "ttl": 10},
    "Ace":               {"priority": 3, "ttl": 15},
    "TeamfightMissed":   {"priority": 4, "ttl": 15},
}


class LolGameSource:

    def __init__(self, queue: SignalQueue, data_dir: Path):
        self.queue = queue
        self._running = True
        self._last_event_index = 0
        self._game_active = False
        self._game_start_pushed = False
        self._current_game_time = 0.0

        # player identity
        self._player_summoner = ""
        self._player_riot_id = ""
        self._player_champion = ""
        self._player_team = ""
        self._name_to_team: dict[str, str] = {}
        # summoner/riot id -> champion. Ravyn says "Zed", not "xX_Slayer_69_Xx":
        # summoner names are unpronounceable and TTS reads them character soup.
        self._name_to_champion: dict[str, str] = {}
        self._my_names: set[str] = set()
        self._has_real_enemies = False
        self._waiting_logged = False

        # kill coalescing
        self._kill_buffer: list[str] = []
        self._kill_buffer_time = 0.0

        # death tracking per game
        self._death_count = 0
        self._kills_since_last_death = 0
        self._assists_since_last_death = 0
        self._logged_kill_sample = False

        # teamfight tracking
        self._recent_kills: list[dict] = []

        # measured state + the angle picked from it
        self.state = GameState()
        self.angles = AngleChooser()

        # deaths per ally champion, so "that one again" is a fact and not a
        # guess, and recent ally deaths for burst detection
        self._ally_deaths: dict[str, int] = {}
        self._recent_ally_deaths: list[float] = []

        # game-time stamps of each reaction, per event type, for burst decay
        self._reaction_log: dict[str, list[float]] = {}

        # load quotes
        self._quotes = self._load_quotes(data_dir / "game_quotes.json")

        # What he has told her about his own account — roles, champions,
        # matchups. Optional: an absent or broken file just disables those
        # lines. See orchestrator/champion_notes.py.
        self.notes = ChampionNotes(data_dir / "champions.json")
        self._read = None       # resolved once per game, at detection

    @property
    def is_game_active(self) -> bool:
        return self._game_active

    def _load_quotes(self, path: Path) -> dict:
        if not path.exists():
            print(f"[lol] WARNING: {path} not found — using empty pools")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[lol] Loaded game quotes from {path.name}")
        return data

    def _pick_quote(self, *keys) -> str:
        """Navigate nested keys in quotes dict, pick random from list."""
        obj = self._quotes
        for k in keys:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return ""
        if isinstance(obj, list) and obj:
            return random.choice(obj)
        return ""

    def _champ(self, name: str) -> str:
        """Summoner or riot name -> champion name. Falls back to the input."""
        if not name:
            return name
        return (self._name_to_champion.get(name)
                or self._name_to_champion.get(name.lower())
                or name)

    def _attribute(self, side: str, killer_name: str) -> tuple[str, str]:
        """
        (subject, taker champion) for an objective.

        "Your team took Baron" is the scoreline; "Lee Sin took Baron" is the
        thing worth saying, and the API gives KillerName on every objective
        event. Falls back to the side when the killer is a neutral or a name
        that resolves to nobody, and to nothing at all when the side is not
        known — she should not assert whose it was if identity failed.
        """
        taker = self._champ(killer_name) if killer_name else ""
        # A champion name is only useful if it IS a champion; objective kills
        # are sometimes credited to a minion or an unresolvable name.
        if taker and taker not in self._name_to_champion.values():
            taker = ""

        if self._is_me(killer_name):
            return "Exiled", taker
        if side == "mine":
            return ("Exiled's teammate " + taker) if taker else "Exiled's team", taker
        if side == "enemy":
            return ("The enemy " + taker) if taker else "The enemy", taker
        return "Someone", taker

    def _pick_teammate_name(self) -> str:
        return self._pick_quote("teammates", "names") or "creatures"

    # ---------------------------------------------------------
    # main loop
    # ---------------------------------------------------------

    def run(self):
        print("[lol] Game event listener active")
        while self._running:
            if self._game_active:
                self._poll_game()
                time.sleep(POLL_INTERVAL)
            else:
                self._check_for_game()
                time.sleep(IDLE_INTERVAL)

    # ---------------------------------------------------------
    # game detection
    # ---------------------------------------------------------

    def _check_for_game(self):
        """
        The API answering is NOT the same as a game being ready to read.

        On the loading screen the endpoint responds with an empty
        `activePlayer` and an empty `allPlayers`. Latching identity from that
        snapshot poisoned the entire game: with no team, `GameState.update`
        matched nobody as an ally and swept all ten champions into
        `enemy_champions`, every kill counted to the enemy, `_is_me` never
        fired so his own KDA and CS stayed at zero, and `_has_real_enemies`
        went False, which makes `_classify_killer` call every objective ours.

        That is what "she counts total kills and objectives without splitting
        who did what" was: with no team there is no split to make. So a game is
        only accepted once the player list is actually readable.
        """
        data = self._fetch()
        if data is None:
            return

        if not self._identity_resolves(data):
            # Loading screen, or a snapshot that arrived half-built. Say so
            # once and keep polling rather than starting a game we cannot read.
            if not self._waiting_logged:
                print("[lol] Game endpoint is up but the player list is not "
                      "ready yet — waiting before reading anything")
                self._waiting_logged = True
            return

        self._waiting_logged = False
        self._game_active = True
        self._game_start_pushed = False
        self._last_event_index = 0
        self._recent_kills = []
        self._kill_buffer = []
        self._kill_buffer_time = 0.0
        self._death_count = 0
        self._kills_since_last_death = 0
        self._assists_since_last_death = 0

        self.state = GameState()
        self.angles.reset()
        self._ally_deaths = {}
        self._recent_ally_deaths = []
        self._reaction_log = {}

        self._apply_identity(data)

        print(f"[lol] Game detected! {self._player_summoner} "
              f"as {self._player_champion} ({self._player_team})")
        print(f"[lol]   riotId={self._player_riot_id!r} "
              f"summonerName={data.get('activePlayer', {}).get('summonerName', '')!r}")

        # Seed the state from the detection snapshot so the capture below
        # reports the role it actually resolved, not an empty one.
        self.state.update(data, self._player_team, self._my_names)
        self._refresh_read()

        print(f"[lol]   Enemies: {self._has_real_enemies} | "
              f"Names: {len(self._name_to_team)}")
        self._log_role_ground_truth(data)
        self._logged_kill_sample = False

    # ---------------------------------------------------------
    # identity
    # ---------------------------------------------------------

    def _identity_resolves(self, data: dict) -> bool:
        """
        Can we tell which of these ten players is him, and whose side he is on?

        Everything downstream that splits ours from theirs depends on this, so
        it is checked up front rather than discovered as nonsense later. Being
        unable to answer is a reason to wait, never a reason to guess: a wrong
        team is worse than no game, because it produces confident, wrong
        commentary instead of silence.
        """
        players = data.get("allPlayers") or []
        if len(players) < 2:
            return False

        active = data.get("activePlayer") or {}
        riot_id = active.get("riotId", "") or ""
        summoner = active.get("summonerName", "") or ""
        if not riot_id and not summoner:
            return False

        return self._match_active_player(players, summoner, riot_id) is not None

    @staticmethod
    def _match_active_player(players: list, summoner: str, riot_id: str) -> dict | None:
        """
        Find his row in allPlayers. Kept in one place because the RU account
        makes this fragile: summonerName is often empty there and riotId is the
        only handle, so every comparison has to tolerate either being missing.
        """
        short = riot_id.split("#")[0] if "#" in riot_id else ""
        wanted = {n.lower() for n in (summoner, riot_id, short) if n}
        if not wanted:
            return None

        for p in players:
            candidates = {
                (p.get("summonerName") or "").lower(),
                (p.get("riotId") or "").lower(),
            }
            p_riot = p.get("riotId") or ""
            if "#" in p_riot:
                candidates.add(p_riot.split("#")[0].lower())
            candidates.discard("")
            if candidates & wanted and p.get("team"):
                return p
        return None

    def _apply_identity(self, data: dict) -> None:
        """Latch who he is. Only ever called on a snapshot that resolves."""
        active = data.get("activePlayer") or {}
        self._player_riot_id = active.get("riotId", "") or ""
        self._player_summoner = active.get("summonerName", "") or ""
        if not self._player_summoner and "#" in self._player_riot_id:
            self._player_summoner = self._player_riot_id.split("#")[0]

        players = data.get("allPlayers") or []

        me = self._match_active_player(players, self._player_summoner,
                                       self._player_riot_id)
        self._player_team = (me or {}).get("team", "") or ""
        self._player_champion = (me or {}).get("championName", "") or ""

        self._name_to_team = {}
        self._name_to_champion = {}

        for p in players:
            team = p.get("team", "")
            summoner = p.get("summonerName", "")
            riot_id = p.get("riotId", "")
            champion = p.get("championName", "")

            names = [summoner, riot_id, champion]
            if "#" in riot_id:
                names.append(riot_id.split("#")[0])

            for name in names:
                if not name:
                    continue
                self._name_to_team[name] = team
                self._name_to_team[name.lower()] = team
                if champion:
                    self._name_to_champion[name] = champion
                    self._name_to_champion[name.lower()] = champion

        self._has_real_enemies = any(
            p.get("team") and p.get("team") != self._player_team
            for p in players)

        self._my_names = {n.lower() for n in
                          (self._player_summoner, self._player_riot_id,
                           self._player_champion) if n}

    def _has_note_on(self, champion: str) -> bool:
        """Did he write a matchup note about this specific champion?"""
        if not self._read or not champion:
            return False
        return any(enemy == champion for enemy, _, _ in self._read.matchups)

    def _refresh_read(self) -> None:
        """Resolve his own notes for this game. Silent when there are none."""
        previous = self._read
        self._read = self.notes.read(
            champion=self.state.champion,
            role=self.state.position,
            enemy_champions=self.state.enemy_champions,
            # Enemy roles are not detectable yet — see champion_notes.read.
            enemy_roles={},
        )
        if self._read and previous is None:
            print(f"[notes] {self.state.champion or '?'} "
                  f"{self.state.position or '(role unknown)'}: "
                  f"{len(self._read.matchups)} matchup note(s), "
                  f"history={bool(self._read.champion_history)} "
                  f"offrole={self._read.offrole}")

    def _log_role_ground_truth(self, data: dict) -> None:
        """
        Print what the API actually says about roles, once per game.

        STATUS.md §7 wants role detection from the 2026 quest items and is
        emphatic that the item names must not be written from memory — that is
        precisely the mistake the section exists to prevent. So this captures
        the ground truth instead of guessing at it: one game of this in the log
        gives the real `position` values, the real summoner spell fields, and
        the real item names on all ten players, which is what unblocks writing
        the detector properly.

        Cheap, once per game, and it self-documents when a patch moves things.
        """
        try:
            for p in data.get("allPlayers", []) or []:
                champ = p.get("championName", "?")
                position = p.get("position", "")
                spells = p.get("summonerSpells", {}) or {}
                spell_names = [
                    v.get("displayName") or v.get("rawDisplayName") or "?"
                    for v in spells.values() if isinstance(v, dict)
                ]
                items = [i.get("displayName") or str(i.get("itemID", "?"))
                         for i in (p.get("items", []) or [])]
                print(f"[lol][roles] {champ:14} position={position!r:12} "
                      f"spells={spell_names} items={items}")
            print(f"[lol][roles] resolved role for Exiled: "
                  f"{self.state.position or 'unknown'!r}")
        except Exception as e:
            # Diagnostics must never take the game source down with them.
            print(f"[lol][roles] capture failed: {e}")

    # ---------------------------------------------------------
    # polling
    # ---------------------------------------------------------

    def _poll_game(self):
        data = self._fetch()
        if data is None:
            if self._game_active:
                print("[lol] Game no longer active")
                self._game_active = False
            return

        self._current_game_time = data.get("gameData", {}).get("gameTime", 0)
        self.state.update(data, self._player_team, self._my_names)

        # Cheap, and it re-resolves once role detection fills in mid-game —
        # `position` is often empty on the first poll and populated later.
        self._refresh_read()

        # delayed game start
        if not self._game_start_pushed and self._current_game_time > 3.0:
            seed = self._pick_quote("game_state", "game_start")
            self._push_event("GameStart", seed or "Game started.", {}, "GameStart")
            self._game_start_pushed = True

        events = data.get("events", {}).get("Events", [])
        new_events = events[self._last_event_index:]
        self._last_event_index = len(events)

        for event in new_events:
            # staleness check using game time
            event_time = event.get("EventTime", self._current_game_time)
            age = self._current_game_time - event_time
            if age > STALE_THRESHOLD:
                print(f"[lol] Dropping stale event: {event.get('EventName', '?')} (age={age:.1f}s)")
                continue
            self._handle_event(event, data)

        # flush kill buffer
        if self._kill_buffer and (time.time() - self._kill_buffer_time) >= KILL_COALESCE_WINDOW:
            self._flush_kills()

        self._check_teamfight()

    # ---------------------------------------------------------
    # event handling
    # ---------------------------------------------------------

    def _handle_event(self, event: dict, game_data: dict):
        name = event.get("EventName", "")

        if name == "GameEnd":
            if self._kill_buffer:
                self._flush_kills()
            result = event.get("Result", "")
            if result == "Win":
                seed = self._pick_quote("game_state", "game_win")
            else:
                seed = self._pick_quote("game_state", "game_loss")
            self._push_event("GameEnd", seed or "Game over.", event, "GameEnd")
            self._game_active = False
            return

        if name == "ChampionKill":
            self._handle_champion_kill(event)
            return

        if name == "Multikill":
            self._handle_multikill(event)
            return

        if name == "BaronKill":
            self._handle_baron(event)
            return

        if name == "DragonKill":
            self._handle_dragon(event)
            return

        if name == "HeraldKill":
            side = self._classify_killer(event.get("KillerName", ""))
            subject, taker = self._attribute(side, event.get("KillerName", ""))
            self.state.record_herald(side, taker)
            seed = self._pick_quote("objectives", "herald_dismiss")
            self._push_event("HeraldKill",
                             f"{subject} took Rift Herald. {seed}".strip(),
                             event, "HeraldKill",
                             extra_context={"side": side, "taker": taker})
            return

        if name == "TurretKilled":
            # Every turret is COUNTED — the map state is what makes her later
            # lines specific. She still only speaks about the ones he took;
            # ten "a tower fell" reactions a game is the noise we are removing.
            killer = event.get("KillerName", "")
            side = self._classify_killer(killer)
            self.state.record_turret(side)
            if self._is_me(killer):
                self._push_event("TurretKilled",
                    "You destroyed a turret.", event, "TurretKilled",
                    extra_context={"side": side})
            return

        if name == "InhibKilled":
            self._handle_structure(event, "inhibitor", "InhibKilled")
            return

        if name == "Ace":
            acer = event.get("AcingTeam", "")
            if acer == self._player_team:
                seed = self._pick_quote("ace", "our_ace")
            else:
                seed = self._pick_quote("ace", "their_ace")
            self._push_event("Ace", seed or "Ace!", event, "Ace",
                             extra_context={"side": "mine" if acer == self._player_team
                                                    else "enemy"})

    # ---------------------------------------------------------
    # kills — buffered
    # ---------------------------------------------------------

    def _handle_champion_kill(self, event: dict):
        killer = event.get("KillerName", "")
        victim = event.get("VictimName", "")
        assisters = event.get("Assisters", [])
        event_time = event.get("EventTime", self._current_game_time)

        if not getattr(self, "_logged_kill_sample", False):
            print(f"[lol] First kill event — KillerName={killer!r} VictimName={victim!r}")
            print(f"[lol]   me: summoner={self._player_summoner!r} "
                  f"riot={self._player_riot_id!r} champ={self._player_champion!r}")
            self._logged_kill_sample = True

        i_killed = self._is_me(killer)
        i_died = self._is_me(victim)
        i_assisted = any(self._is_me(a) for a in assisters)

        self._recent_kills.append({
            "time": event_time,
            "involved_me": i_killed or i_died or i_assisted,
        })

        if i_killed:
            self._kill_buffer.append(victim)
            self._kill_buffer_time = time.time()
            self._kills_since_last_death += 1

        elif i_died:
            if self._kill_buffer:
                self._flush_kills()
            self._handle_death(event)

        elif i_assisted:
            self._assists_since_last_death += 1

        else:
            # The collective slang ("creatures", "these apes") is HER
            # vocabulary and comes from the persona, not from the event text.
            # Splicing the names pool into a possessive sentence produced
            # "Your those things on team LeeSin died" — broken English handed
            # straight to the model, which then had to repair it before it
            # could be funny.
            side = self._classify_killer(killer)
            if side == "mine":
                seed = self._pick_quote("teammates", "ally_kill")
                killer_champ = self._champ(killer)
                who = (f"Exiled's teammate {killer_champ}" if killer_champ
                       else "One of Exiled's teammates")
                self._push_event("AllyKill",
                    f"{who} killed {self._champ(victim)}. {seed}",
                    event, "AllyKill",
                    extra_context={"victim_champion": self._champ(victim),
                                   "killer_champion": killer_champ})
            else:
                champ = self._champ(victim)
                self._ally_deaths[champ] = self._ally_deaths.get(champ, 0) + 1
                self._recent_ally_deaths.append(self._current_game_time)
                self._recent_ally_deaths = [
                    t for t in self._recent_ally_deaths
                    if self._current_game_time - t <= ALLY_DEATH_BURST_WINDOW
                ]

                seed = self._pick_quote("teammates", "ally_death")
                slayer = self._champ(killer)
                died = (f"Exiled's teammate {champ} died to {slayer}."
                        if slayer else f"Exiled's teammate {champ} died.")
                self._push_event("AllyDeath",
                    f"{died} {seed}",
                    event, "AllyDeath",
                    extra_context={
                        "victim_champion": champ,
                        "killer_champion": self._champ(killer),
                        # how many times THIS champion has died, and how many
                        # allies have died in the last half minute — the two
                        # facts that make "again" and "bleeding" honest
                        "victim_deaths": self._ally_deaths[champ],
                        "recent_ally_deaths": len(self._recent_ally_deaths),
                    })

    def _flush_kills(self):
        count = len(self._kill_buffer)
        self._kill_buffer.clear()
        if count == 0:
            return

        if count == 1:
            seed = self._pick_quote("kills", "single")
            self._push_event("MyKill", seed or "Kill.", {}, "MyKill")
        else:
            seed = self._pick_quote("kills", "spree")
            self._push_event("MyKillSpree",
                f"You killed {count} enemies. {seed}",
                {}, "MyKill")

    # ---------------------------------------------------------
    # deaths
    # ---------------------------------------------------------

    def _handle_death(self, event: dict):
        killer = event.get("KillerName", "")
        killer_champion = self._champ(killer)
        self._death_count += 1
        was_trade = self._kills_since_last_death > 0 or self._assists_since_last_death > 0
        self._kills_since_last_death = 0
        self._assists_since_last_death = 0

        print(f"[lol] Death #{self._death_count} (trade={was_trade}) by {killer}")

        # 5+ deaths — always react, roast
        if self._death_count >= 5:
            seed = self._pick_quote("deaths", "roast_5plus")
            self._push_event("MyDeathRoast",
                f"Death #{self._death_count}. {seed}",
                event, "MyDeath",
                extra_context={"death_count": self._death_count,
                               "killer_champion": killer_champion,
                               "mood_spike": -0.6})
            return

        # 1-4 deaths — 50/50
        if random.random() < 0.5:
            print(f"[lol] Ignoring death #{self._death_count} (coin flip)")
            return

        if was_trade:
            seed = self._pick_quote("deaths", "soft")
        elif self._death_count >= 3:
            seed = self._pick_quote("deaths", "mild")
        else:
            seed = self._pick_quote("deaths", "harsh")

        self._push_event("MyDeath",
            f"{seed or 'You died.'} Killed by {killer_champion}."
            if killer_champion else (seed or "You died."),
            event, "MyDeath",
            extra_context={"death_count": self._death_count,
                           "was_trade": was_trade,
                           "killer_champion": killer_champion,
                           # True only when he actually wrote something about
                           # this champion — never "she knows the matchup".
                           "killer_has_note": self._has_note_on(killer_champion)})

    # ---------------------------------------------------------
    # multikills — immediate
    # ---------------------------------------------------------

    def _handle_multikill(self, event: dict):
        killer = event.get("KillerName", "")
        streak = event.get("KillStreak", 2)
        if not self._is_me(killer):
            return
        streak_name = MULTIKILL_NAMES.get(streak, f"{streak}x")
        seed = self._pick_quote("kills", "multikill")
        self._push_event("MyMultikill",
            f"{streak_name} kill! {seed}", event, "MyMultikill")

    # ---------------------------------------------------------
    # baron
    # ---------------------------------------------------------

    def _handle_baron(self, event: dict):
        killer = event.get("KillerName", "")
        stolen = event.get("Stolen", False) and self._has_real_enemies
        assisters = event.get("Assisters", [])
        side = self._classify_killer(killer)
        i_was_involved = self._is_me(killer) or any(self._is_me(a) for a in assisters)
        subject, taker = self._attribute(side, killer)
        self.state.record_baron(side, taker)

        if stolen:
            if side == "mine":
                seed = self._pick_quote("objectives", "baron_stolen_by_us")
            else:
                seed = self._pick_quote("objectives", "baron_stolen_by_enemy")
        elif side == "mine" or not self._has_real_enemies:
            if i_was_involved:
                seed = self._pick_quote("objectives", "baron_mine")
            else:
                seed = self._pick_quote("objectives", "baron_mine_without_me")
        else:
            seed = self._pick_quote("objectives", "baron_enemy")

        self._push_event("BaronKill", f"{subject} took Baron. {seed}".strip(),
                         event, "BaronKill",
                         extra_context={"side": side, "stolen": stolen,
                                        "taker": taker})

    # ---------------------------------------------------------
    # dragon
    # ---------------------------------------------------------

    def _handle_dragon(self, event: dict):
        dragon_type = event.get("DragonType", "Unknown")
        side = self._classify_killer(event.get("KillerName", ""))

        # Counted before the reaction chance is rolled: the tally is state, not
        # commentary. Skipping the count when she happens not to speak would
        # leave her asserting a drake score that never happened.
        subject, taker = self._attribute(side, event.get("KillerName", ""))
        self.state.record_dragon(side, dragon_type, taker)

        seed = self._pick_quote("objectives", "dragon_dismiss")
        text = f"{subject} took the {dragon_type} dragon. {seed}".strip()
        self._push_event("DragonKill", text, event, "DragonKill",
                         extra_context={"side": side, "taker": taker})

    # ---------------------------------------------------------
    # structures
    # ---------------------------------------------------------

    def _handle_structure(self, event: dict, struct_name: str, event_prefix: str):
        killer = event.get("KillerName", "")
        side = self._classify_killer(killer)
        i_did_it = self._is_me(killer)
        if struct_name == "inhibitor":
            self.state.record_inhibitor(side)
        teammate_name = self._pick_teammate_name()

        if side == "mine" or not self._has_real_enemies:
            if i_did_it:
                self._push_event(event_prefix,
                    f"You destroyed an enemy {struct_name}.", event, event_prefix)
            elif self._has_real_enemies:
                self._push_event(event_prefix,
                    f"{teammate_name.capitalize()} knocked down a {struct_name}.",
                    event, event_prefix)
            else:
                self._push_event(event_prefix,
                    f"Enemy {struct_name} destroyed.", event, event_prefix)
        else:
            self._push_event(event_prefix,
                f"The enemy destroyed one of your {struct_name}s.", event, event_prefix)

    # ---------------------------------------------------------
    # teamfight
    # ---------------------------------------------------------

    def _check_teamfight(self):
        if not self._has_real_enemies:
            return
        now = self._current_game_time
        self._recent_kills = [k for k in self._recent_kills if now - k["time"] < TEAMFIGHT_WINDOW * 2]
        if len(self._recent_kills) < TEAMFIGHT_MIN_KILLS:
            return
        window_start = now - TEAMFIGHT_WINDOW
        recent = [k for k in self._recent_kills if k["time"] >= window_start]
        if len(recent) < TEAMFIGHT_MIN_KILLS:
            return
        if not any(k["involved_me"] for k in recent):
            seed = self._pick_quote("teamfight_missed")
            if isinstance(seed, str) and seed:
                pass
            else:
                seed = "A fight happened without you."
            self._push_event("TeamfightMissed", seed, {}, "TeamfightMissed")
            self._recent_kills = [k for k in self._recent_kills if k["time"] < window_start]

    # ---------------------------------------------------------
    # name matching
    # ---------------------------------------------------------

    def _is_me(self, name: str) -> bool:
        if not name:
            return False
        lower = name.lower()
        return (name == self._player_summoner or name == self._player_riot_id
                or name == self._player_champion
                or lower == self._player_summoner.lower()
                or lower == self._player_riot_id.lower()
                or lower == self._player_champion.lower())

    def _classify_killer(self, killer_name: str) -> str:
        if not killer_name:
            return "enemy"
        if self._is_me(killer_name):
            return "mine"
        team = self._name_to_team.get(killer_name, "") or self._name_to_team.get(killer_name.lower(), "")
        if not team:
            lower = killer_name.lower()
            if "t100" in lower or "order" in lower:
                team = "ORDER"
            elif "t200" in lower or "chaos" in lower:
                team = "CHAOS"
        if not self._player_team:
            # No identity, no sides. "mine" here is what made every objective
            # count as ours; "enemy" would be the same mistake mirrored.
            return "unknown"

        if team == self._player_team:
            return "mine"
        elif team:
            return "enemy"
        else:
            return "mine" if not self._has_real_enemies else "enemy"

    # ---------------------------------------------------------
    # push
    # ---------------------------------------------------------

    def _reaction_chance(self, config_key: str, event_type: str) -> float:
        """
        Base chance, decayed by how often she has just reacted to this kind of
        thing.

        The base rates were never the problem on their own — five ally deaths
        in one teamfight were five independent rolls at 0.6, so she commented
        on the same thirty seconds three times. Each recent reaction of the
        same kind multiplies the next one's chance, and the counter decays, so
        an isolated event later in the game still lands at full rate.
        """
        base = settings.REACTION_CHANCE.get(
            config_key, settings.REACTION_CHANCE.get(event_type, 1.0))

        now = self._current_game_time
        recent = [t for t in self._reaction_log.get(config_key, [])
                  if now - t <= settings.REACTION_WINDOW]
        self._reaction_log[config_key] = recent

        return base * (settings.REACTION_DECAY ** len(recent))

    def _push_event(self, config_key: str, text: str, raw_event: dict,
                    event_type: str, extra_context: dict = None):
        chance = self._reaction_chance(config_key, event_type)
        if chance < 1.0 and random.random() > chance:
            print(f"[lol] {config_key}: skipped (chance {chance:.2f})")
            return

        self._reaction_log.setdefault(config_key, []).append(self._current_game_time)

        config = EVENT_CONFIG.get(config_key, EVENT_CONFIG.get(event_type, {"priority": 5, "ttl": 15}))
        ctx = {
            "trigger": "game_event",
            "game": "league_of_legends",
            "event_type": event_type,
            "player_name": self._player_summoner,
            "player_champion": self._player_champion,
        }
        if extra_context:
            ctx.update(extra_context)

        # The two fields that make one ally death different from the last:
        # what is actually true in the game right now, and a direction chosen
        # from it that she has not just been given. See STATUS.md §7.
        situation = self.state.render()
        if situation:
            ctx["situation"] = situation

        # His own notes travel separately from the measured facts, and are
        # labelled as his in the prompt. §7: she may repeat what he told her,
        # never extend it into a read of her own.
        if self._read:
            ctx["player_notes"] = self._read.render()
            ctx["has_matchup_note"] = bool(self._read.matchups)
            ctx["has_champion_history"] = bool(self._read.champion_history)
            ctx["has_role_note"] = bool(self._read.role_read)
            ctx["is_offrole"] = self._read.offrole
            ctx["role_skill"] = self._read.role_skill

        angle = self.angles.choose(event_type, self.state, ctx)
        if angle is not None:
            ctx["angle"] = angle.instruction
            ctx["angle_id"] = angle.id

        # Her face should reflect how the game is going, not sit flat until a
        # fifth death. The worker only applies mood_spike when the LLM did not
        # return a mood of its own, so an explicit one (the death roast) still
        # wins — this fills the silence in between.
        ctx.setdefault("mood_spike", self.state.mood())

        signal = Signal(
            source="game",
            priority=config["priority"],
            text=text,
            mode="improv",
            skip_llm=False,
            ttl=config.get("ttl"),
            context=ctx,
        )
        self.queue.push(signal)
        angle_note = f"  [{ctx['angle_id']}]" if "angle_id" in ctx else ""
        print(f"[lol] {config_key}: {text[:70]}{angle_note}")

    def _fetch(self) -> dict | None:
        try:
            resp = requests.get(API_URL, timeout=2, verify=False)
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout):
            return None
        except Exception as e:
            print(f"[lol] API error: {e}")
            return None

    def stop(self):
        self._running = False