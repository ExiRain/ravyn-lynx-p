"""
Live game state — the facts Ravyn is allowed to talk about.

The Live Client API was already being polled every two seconds and then thrown
away: `_push_event` sent the notebook her champion name and nothing else. So
every ally death in a game produced a byte-identical prompt, and no amount of
seed variety survives that. This module keeps the poll.

The governing rule from STATUS.md §7 applies to everything here:

    She may only assert things you told her, or things the API measured.
    Never anything she would have to know about League.

So this holds counts, scores and timings — arithmetic on measured values — and
nothing that requires an opinion about the game. "You are down two drakes at
twenty-four minutes" is measurement. "Their comp beats yours" is not, and has
no home here.

Anything unknown is *omitted* rather than guessed. `render()` only prints lines
it actually has, so a field the API did not give us cannot become something she
asserts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Minutes. Rough, and only ever used to change her register — nothing branches
# on the exact boundary, so they do not need to be defensible to a coach.
EARLY_UNTIL = 15
MID_UNTIL = 30

DRAGON_SOUL_AT = 4      # 4 drakes take soul; 3 is the point where it looms


@dataclass
class Player:
    """One player's scoreboard row, for the champion she is allowed to name."""
    champion: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0

    @property
    def kda(self) -> str:
        return f"{self.kills}/{self.deaths}/{self.assists}"

    def __str__(self) -> str:
        return f"{self.champion} {self.kda}"


@dataclass
class Side:
    """One team's objective tally."""
    dragons: list[str] = field(default_factory=list)
    # Champion names of whoever actually took each objective, in order. The
    # side tally answers "who is winning"; this answers "who is doing it",
    # which is the difference between "your team has three drakes" and "your
    # jungler has taken all three of those himself".
    objective_takers: list[str] = field(default_factory=list)
    barons: int = 0
    heralds: int = 0
    turrets: int = 0
    inhibitors: int = 0
    kills: int = 0


@dataclass
class GameState:
    """
    Accumulated across a game. Reset by LolGameSource on game detection.

    Two inputs: `update()` from each poll of allgamedata, and `record_*()`
    from the events that carry a side.
    """

    game_time: float = 0.0

    # active player
    champion: str = ""
    position: str = ""          # "" when unknown — never guessed
    level: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0
    cs_rank: int = 0            # 1 = most CS of all ten players
    ward_score: float = 0.0

    ally_champions: list[str] = field(default_factory=list)
    enemy_champions: list[str] = field(default_factory=list)

    # Full scoreboard rows. The team totals answer "who is winning"; these
    # answer "who is doing it", which is the difference between "your team is
    # eight kills down" and "your bot lane is nine deaths between them".
    allies: list[Player] = field(default_factory=list)
    enemies: list[Player] = field(default_factory=list)

    ours: Side = field(default_factory=Side)
    theirs: Side = field(default_factory=Side)

    # set once per game, from the summoner spells, so it survives an empty
    # `position` field. See _absorb_role.
    _role_source: str = ""

    # one-shot so a broken identity does not print every two seconds
    _warned_no_team: bool = False

    # ---------------------------------------------------------
    # derived
    # ---------------------------------------------------------

    @property
    def minutes(self) -> float:
        return self.game_time / 60.0

    @property
    def phase(self) -> str:
        if self.minutes < EARLY_UNTIL:
            return "early"
        if self.minutes < MID_UNTIL:
            return "mid"
        return "late"

    @property
    def cs_per_min(self) -> float:
        return self.cs / self.minutes if self.minutes >= 1 else 0.0

    @property
    def kill_lead(self) -> int:
        """Positive when his team is ahead on kills."""
        return self.ours.kills - self.theirs.kills

    @property
    def dragon_lead(self) -> int:
        return len(self.ours.dragons) - len(self.theirs.dragons)

    @property
    def turret_lead(self) -> int:
        return self.ours.turrets - self.theirs.turrets

    @property
    def soul_point(self) -> str:
        """Who is one drake from soul: "ours", "theirs", "both" or ""."""
        we = len(self.ours.dragons) == DRAGON_SOUL_AT - 1
        they = len(self.theirs.dragons) == DRAGON_SOUL_AT - 1
        if we and they:
            return "both"
        if we:
            return "ours"
        if they:
            return "theirs"
        return ""

    @property
    def soul_taken(self) -> str:
        if len(self.ours.dragons) >= DRAGON_SOUL_AT:
            return "ours"
        if len(self.theirs.dragons) >= DRAGON_SOUL_AT:
            return "theirs"
        return ""

    @property
    def kda_line(self) -> str:
        return f"{self.kills}/{self.deaths}/{self.assists}"

    def worst_ally(self) -> Player | None:
        """The teammate having the worst game, by deaths against contribution."""
        if not self.allies:
            return None
        scored = [p for p in self.allies if p.deaths >= 3]
        if not scored:
            return None
        return max(scored, key=lambda p: p.deaths - (p.kills + p.assists / 2.0))

    def best_ally(self) -> Player | None:
        if not self.allies:
            return None
        return max(self.allies, key=lambda p: p.kills + p.assists / 2.0 - p.deaths)

    def biggest_threat(self) -> Player | None:
        """The enemy who is actually winning the game for them."""
        if not self.enemies:
            return None
        top = max(self.enemies, key=lambda p: p.kills - p.deaths)
        return top if top.kills >= 4 and top.kills > top.deaths else None

    def carrying(self) -> bool:
        """Is he outperforming everyone on his own team?"""
        if not self.allies:
            return False
        mine = self.kills + self.assists / 2.0 - self.deaths
        return all(mine > p.kills + p.assists / 2.0 - p.deaths
                   for p in self.allies)

    def mood(self) -> float:
        """
        How the game is going, as a number in [-1, 1].

        This drives her *face* in Godot, not her words — the worker uses it as
        `mood_spike`, which only applies when the LLM did not return a mood of
        its own (see adapters/mq/rabbitmq.py). Before this, the only game input
        to mood was the fixed -0.6 on a fifth death, so her expression was flat
        through an entire winning or losing game.

        Three measured components, weighted by how much each actually says
        about the state of a game. Nothing here is an opinion: it is the same
        arithmetic a scoreboard does.
        """
        if self.game_time <= 0:
            return 0.0

        # Kill lead, saturating around eight — past that the game is decided
        # and being further ahead does not change how she feels about it.
        kills = _clamp(self.kill_lead / 8.0)

        # Objectives move slower and matter more per unit.
        objectives = _clamp((self.dragon_lead + self.turret_lead / 3.0) / 4.0)

        # His own game, weighed against a rough par of one death per five
        # minutes. Deaths hurt more than kills help, which is both true and
        # in character.
        par_deaths = max(1.0, self.minutes / 5.0)
        personal = _clamp((self.kills + self.assists / 2.0 - self.deaths * 1.5)
                          / (par_deaths * 3.0))

        return round(_clamp(0.4 * kills + 0.35 * objectives + 0.25 * personal), 2)

    # ---------------------------------------------------------
    # ingest
    # ---------------------------------------------------------

    def update(self, data: dict, my_team: str, my_names: set[str]) -> None:
        """
        Refresh from one allgamedata poll. Cheap; called every 2s.

        Refuses to split the teams without knowing his. The caller is supposed
        to have resolved identity before ever calling this, but the cost of it
        being wrong is not a missing line — it is a confident wrong one. With
        an empty `my_team` the old code matched nobody as an ally and swept all
        ten champions into `enemy_champions`, so she opened a game commenting
        on the "chaotic mix" of a ten-man enemy team. Better to know the minute
        and nothing else.
        """
        self.game_time = data.get("gameData", {}).get("gameTime", 0.0) or 0.0

        players = data.get("allPlayers", []) or []

        if not my_team:
            if not self._warned_no_team:
                self._warned_no_team = True
                print("[state] No team resolved — holding team splits empty "
                      "rather than guessing sides")
            return
        cs_by_player: list[tuple[int, bool]] = []

        ally, enemy = [], []
        ally_rows: list[Player] = []
        enemy_rows: list[Player] = []
        our_kills = their_kills = 0

        for p in players:
            team = p.get("team", "")
            champ = p.get("championName", "") or ""
            scores = p.get("scores", {}) or {}
            cs = int(scores.get("creepScore", 0) or 0)
            kills = int(scores.get("kills", 0) or 0)

            mine = self._is_me(p, my_names)
            cs_by_player.append((cs, mine))

            row = Player(champion=champ, kills=kills,
                         deaths=int(scores.get("deaths", 0) or 0),
                         assists=int(scores.get("assists", 0) or 0), cs=cs)

            if team == my_team:
                our_kills += kills
                if not mine and champ:
                    ally.append(champ)
                    ally_rows.append(row)
            elif team:
                their_kills += kills
                if champ:
                    enemy.append(champ)
                    enemy_rows.append(row)

            if mine:
                self.champion = champ or self.champion
                self.level = int(p.get("level", 0) or 0)
                self.kills = kills
                self.deaths = int(scores.get("deaths", 0) or 0)
                self.assists = int(scores.get("assists", 0) or 0)
                self.cs = cs
                self.ward_score = float(scores.get("wardScore", 0.0) or 0.0)
                self._absorb_role(p)

        if ally or enemy:
            self.ally_champions = ally
            self.enemy_champions = enemy
            self.allies = ally_rows
            self.enemies = enemy_rows

        # Team kill totals come from the scoreboard, not from counting events:
        # events can be missed while the client is starting up, scores cannot.
        self.ours.kills = our_kills
        self.theirs.kills = their_kills

        mine_cs = [cs for cs, mine in cs_by_player if mine]
        if mine_cs:
            better = sum(1 for cs, mine in cs_by_player if not mine and cs > mine_cs[0])
            self.cs_rank = better + 1

    @staticmethod
    def _is_me(player: dict, my_names: set[str]) -> bool:
        for key in ("summonerName", "riotId", "championName"):
            value = (player.get(key) or "").lower()
            if value and value in my_names:
                return True
        return False

    def _absorb_role(self, player: dict) -> None:
        """
        Role, best effort, never guessed.

        `position` is authoritative when the API fills it in, which it often
        does not. Smite is the one summoner spell that identifies a role on its
        own — Ignite and Flash go on everybody.

        STATUS.md §7 warns against hardcoding item names from memory, and the
        same applies to spell strings: the RU client localises `displayName`,
        so this scans every string under summonerSpells instead of naming a
        field. The locale-independent raw key (…SummonerSmite…) matches even
        when the display name does not. Nothing else is inferred: any other
        role has to come from `position` or stay unknown.
        """
        position = (player.get("position") or "").strip()
        if position:
            self.position = position.lower()
            self._role_source = "position"
            return

        if self._role_source:
            return

        if _mentions_smite(player.get("summonerSpells", {})):
            self.position = "jungle"
            self._role_source = "smite"

    # ---------------------------------------------------------
    # objectives, from events
    # ---------------------------------------------------------

    def record_dragon(self, side: str, dragon_type: str,
                      taker: str = "") -> None:
        target = self._side(side)
        if target is None:
            return
        target.dragons.append(dragon_type or "Unknown")
        if taker:
            target.objective_takers.append(taker)

    def record_baron(self, side: str, taker: str = "") -> None:
        target = self._side(side)
        if target is None:
            return
        target.barons += 1
        if taker:
            target.objective_takers.append(taker)

    def record_herald(self, side: str, taker: str = "") -> None:
        target = self._side(side)
        if target is None:
            return
        target.heralds += 1
        if taker:
            target.objective_takers.append(taker)

    def record_turret(self, side: str) -> None:
        target = self._side(side)
        if target is not None:
            target.turrets += 1

    def record_inhibitor(self, side: str) -> None:
        target = self._side(side)
        if target is not None:
            target.inhibitors += 1

    def _side(self, side: str):
        """
        None when the side is unknown, and the caller then records nothing.

        A tally is only worth keeping if it is right. Filing an unattributed
        objective under either team produces a drake score she will state
        confidently and wrongly, which is worse than her not mentioning drakes.
        """
        if side == "mine":
            return self.ours
        if side == "enemy":
            return self.theirs
        return None

    # ---------------------------------------------------------
    # rendering
    # ---------------------------------------------------------

    def render(self) -> str:
        """
        A compact block of measured facts for the prompt.

        Every line is omitted when its value is unknown or zero-information, so
        she is never handed a placeholder to assert. Kept short deliberately:
        the notebook runs at 4096 context on the default quant.
        """
        lines: list[str] = []

        if self.game_time > 0:
            lines.append(f"{int(self.minutes)} minutes in ({self.phase} game).")

        if self.champion:
            who = f"Exiled: {self.champion}"
            if self.position:
                who += f" {self.position}"
            if self.level:
                who += f", level {self.level}"
            who += f", {self.kda_line}"
            if self.cs:
                who += f", {self.cs} CS"
                if self.minutes >= 3:
                    detail = f"{self.cs_per_min:.1f}/min"
                    if self.cs_rank:
                        detail += f", {_ordinal(self.cs_rank)} of ten"
                    who += f" ({detail})"
            lines.append(who + ".")

        if self.ours.kills or self.theirs.kills:
            lines.append(f"Kills: your team {self.ours.kills}, "
                         f"theirs {self.theirs.kills}.")

        drakes = self._dragon_line()
        if drakes:
            lines.append(drakes)

        objectives = self._objective_line()
        if objectives:
            lines.append(objectives)

        if self.allies:
            lines.append("His team: " + ", ".join(str(p) for p in self.allies) + ".")

        if self.enemies:
            lines.append("Enemy team: " + ", ".join(str(p) for p in self.enemies) + ".")
        elif self.enemy_champions:
            lines.append("Enemy team: " + ", ".join(self.enemy_champions) + ".")

        if not lines:
            return ""

        return ("SITUATION — measured from the game. You may use these facts. "
                "Do not state anything about the game beyond them.\n"
                + "\n".join(f"  {line}" for line in lines))

    def _dragon_line(self) -> str:
        ours, theirs = len(self.ours.dragons), len(self.theirs.dragons)
        if not ours and not theirs:
            return ""

        line = f"Drakes: yours {ours}, theirs {theirs}"

        # Who actually took them. One champion on every drake is a different
        # story from four different people, and only this says which.
        takers = self.ours.objective_takers
        if ours >= 2 and takers and len(set(takers)) == 1:
            line += f" (all of yours taken by {takers[0]})"

        taken = self.soul_taken
        if taken == "ours":
            line += " — you have soul"
        elif taken == "theirs":
            line += " — they have soul"
        else:
            point = self.soul_point
            if point == "both":
                line += " — whoever takes the next one gets soul"
            elif point == "ours":
                line += " — one more and you take soul"
            elif point == "theirs":
                line += " — one more and they take soul"

        return line + "."

    def _objective_line(self) -> str:
        parts = []
        if self.ours.barons or self.theirs.barons:
            parts.append(f"Baron: yours {self.ours.barons}, "
                         f"theirs {self.theirs.barons}")
        if self.ours.turrets or self.theirs.turrets:
            parts.append(f"towers: yours {self.ours.turrets}, "
                         f"theirs {self.theirs.turrets}")
        if self.ours.inhibitors or self.theirs.inhibitors:
            parts.append(f"inhibitors: yours {self.ours.inhibitors}, "
                         f"theirs {self.theirs.inhibitors}")
        return ("; ".join(parts) + ".") if parts else ""


def _mentions_smite(spells) -> bool:
    """True if 'smite' appears anywhere in the summoner spell subtree."""
    if isinstance(spells, dict):
        return any(_mentions_smite(v) for v in spells.values())
    if isinstance(spells, list):
        return any(_mentions_smite(v) for v in spells)
    return isinstance(spells, str) and "smite" in spells.lower()


def _ordinal(n: int) -> str:
    words = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
             6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
    return words.get(n, f"{n}th")


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
