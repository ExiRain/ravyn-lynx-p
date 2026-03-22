"""
League of Legends Live Game source.

- Loads quotes from data/game_quotes.json
- Uses EventTime from game API for staleness (not wall clock)
- Kill coalescing with quote seeds from pools
- Death tracking per game with trade detection
- Completely disables silence filler during games
"""

from __future__ import annotations

import json
import random
import time
import requests
import urllib3
from pathlib import Path

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
        self._has_real_enemies = False

        # kill coalescing
        self._kill_buffer: list[str] = []
        self._kill_buffer_time = 0.0

        # death tracking per game
        self._death_count = 0
        self._kills_since_last_death = 0
        self._assists_since_last_death = 0

        # teamfight tracking
        self._recent_kills: list[dict] = []

        # load quotes
        self._quotes = self._load_quotes(data_dir / "game_quotes.json")

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
        data = self._fetch()
        if data is None:
            return

        self._game_active = True
        self._game_start_pushed = False
        self._last_event_index = 0
        self._recent_kills = []
        self._kill_buffer = []
        self._kill_buffer_time = 0.0
        self._death_count = 0
        self._kills_since_last_death = 0
        self._assists_since_last_death = 0

        active = data.get("activePlayer", {})
        self._player_riot_id = active.get("riotId", "")
        self._player_summoner = active.get("summonerName", "")
        if not self._player_summoner and "#" in self._player_riot_id:
            self._player_summoner = self._player_riot_id.split("#")[0]

        self._name_to_team = {}
        enemy_count = 0
        for p in data.get("allPlayers", []):
            team = p.get("team", "")
            summoner = p.get("summonerName", "")
            riot_id = p.get("riotId", "")
            champion = p.get("championName", "")
            for name in [summoner, riot_id, champion]:
                if name:
                    self._name_to_team[name] = team
                    self._name_to_team[name.lower()] = team
            if "#" in riot_id:
                short = riot_id.split("#")[0]
                self._name_to_team[short] = team
                self._name_to_team[short.lower()] = team
            is_me = (summoner == self._player_summoner
                     or riot_id == self._player_riot_id
                     or (self._player_summoner and summoner.lower() == self._player_summoner.lower()))
            if is_me:
                self._player_team = team
                self._player_champion = champion
            elif team and team != self._player_team:
                enemy_count += 1

        # recount enemies properly
        enemy_count = sum(1 for p in data.get("allPlayers", [])
                         if p.get("team", "") and p.get("team", "") != self._player_team)
        self._has_real_enemies = enemy_count > 0

        print(f"[lol] Game detected! {self._player_summoner} as {self._player_champion} ({self._player_team})")
        print(f"[lol]   Enemies: {self._has_real_enemies} | Names: {len(self._name_to_team)}")

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
            seed = self._pick_quote("objectives", "herald_dismiss")
            self._push_event("HeraldKill", seed or "Herald taken.", event, "HeraldKill")
            return

        if name == "TurretKilled":
            # turrets are very low priority — only react if I did it
            killer = event.get("KillerName", "")
            if self._is_me(killer):
                self._push_event("TurretKilled",
                    "You destroyed a turret.", event, "TurretKilled")
            # silently ignore all other turret events
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
            self._push_event("Ace", seed or "Ace!", event, "Ace")

    # ---------------------------------------------------------
    # kills — buffered
    # ---------------------------------------------------------

    def _handle_champion_kill(self, event: dict):
        killer = event.get("KillerName", "")
        victim = event.get("VictimName", "")
        assisters = event.get("Assisters", [])
        event_time = event.get("EventTime", self._current_game_time)

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
            side = self._classify_killer(killer)
            teammate_name = self._pick_teammate_name()
            if side == "mine":
                seed = self._pick_quote("teammates", "ally_kill")
                self._push_event("AllyKill",
                    f"One of {teammate_name} killed {victim}. {seed}",
                    event, "AllyKill")
            else:
                seed = self._pick_quote("teammates", "ally_death")
                self._push_event("AllyDeath",
                    f"Your {teammate_name.replace('your ', '')} {victim} died. {seed}",
                    event, "AllyDeath")

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
                extra_context={"death_count": self._death_count, "mood_spike": -0.6})
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

        self._push_event("MyDeath", seed or "You died.",
            event, "MyDeath",
            extra_context={"death_count": self._death_count, "was_trade": was_trade})

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

        self._push_event("BaronKill", seed or "Baron.", event, "BaronKill")

    # ---------------------------------------------------------
    # dragon
    # ---------------------------------------------------------

    def _handle_dragon(self, event: dict):
        dragon_type = event.get("DragonType", "Unknown")
        stolen = event.get("Stolen", False) and self._has_real_enemies
        seed = self._pick_quote("objectives", "dragon_dismiss")
        text = f"{dragon_type} dragon. {seed}" if seed else f"{dragon_type} dragon down."
        self._push_event("DragonKill", text, event, "DragonKill")

    # ---------------------------------------------------------
    # structures
    # ---------------------------------------------------------

    def _handle_structure(self, event: dict, struct_name: str, event_prefix: str):
        killer = event.get("KillerName", "")
        side = self._classify_killer(killer)
        i_did_it = self._is_me(killer)
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
        if team == self._player_team:
            return "mine"
        elif team:
            return "enemy"
        else:
            return "mine" if not self._has_real_enemies else "enemy"

    # ---------------------------------------------------------
    # push
    # ---------------------------------------------------------

    def _push_event(self, config_key: str, text: str, raw_event: dict,
                    event_type: str, extra_context: dict = None):
        config = EVENT_CONFIG.get(config_key, EVENT_CONFIG.get(event_type, {"priority": 5, "ttl": 15}))
        ctx = {
            "trigger": "game_event",
            "game": "league_of_legends",
            "event_type": event_type,
            "player_name": self._player_summoner,
        }
        if extra_context:
            ctx.update(extra_context)

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
        print(f"[lol] {config_key}: {text[:70]}")

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