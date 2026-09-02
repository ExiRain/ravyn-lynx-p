"""
Angles — what makes two reactions to the same event different.

STATUS.md §7 already found the bottleneck and it was not the quote pools:

    Real variation needs more *distinct situations*, not more lines per
    situation.

Five event types (DragonKill, HeraldKill, TurretKilled, AllyKill, AllyDeath —
the most frequent in any game) all collapsed into one "be dismissive"
instruction. Fifteen ally deaths a game meant fifteen byte-identical prompts
differing only in a seed drawn from five strings, so the model converged on the
same joke by game two. That is the "apes died again, x30" problem, and adding a
sixth seed would not have touched it.

An angle is a *different instruction*, chosen from the measured state. The same
ally death reads differently at 4 minutes and at 34, when you are eight kills up
versus eight down, when it is the first of the game versus the fourth in ninety
seconds. Those are real differences in the game, so they are honest differences
in what she says — and they arrive for free, because the state is already there.

Two rules hold everywhere:

  * An angle only fires when its facts are true. Nothing here invents a read on
    the game; predicates are arithmetic on what the API measured, per §7.
  * A recently used angle loses to one that has not been used. Anti-repetition
    is the whole point, and randomness alone does not deliver it — a uniform
    pick over eight angles still repeats about one time in eight.

Every list needs at least MIN_UNCONDITIONAL angles that are always eligible.
The situational ones are the good ones, but they go quiet in a flat game — an
even scoreline at twelve minutes makes almost none of them true — and a list
whose floor is one angle repeats that one angle back to back. The unconditional
entries are therefore *registers* rather than reads: the same fact delivered
deadpan, clipped, or with a sigh is honest whatever the score, so they can
always fire. tests/test_game_variety.py enforces the floor.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from orchestrator.game_state import GameState

# How many recent angle ids to remember. Roughly "she will not reuse an angle
# inside the same skirmish", which is the window a viewer actually notices.
RECENT_MEMORY = 10

# Minimum always-eligible angles per event type. Three is what it takes to
# never repeat back to back once the deque holds the two most recent.
MIN_UNCONDITIONAL = 3


@dataclass(frozen=True)
class Angle:
    id: str
    instruction: str
    when: Callable[[GameState, dict], bool] = lambda s, e: True


def _always(s: GameState, e: dict) -> bool:
    return True


# =============================================================
# Ally deaths — the worst offender, so it gets the most angles
# =============================================================

ALLY_DEATH = [
    Angle("ally_death_bleeding",
          "This is not the first one. Your team is bleeding members faster "
          "than it is trading for anything. Say so — count it, do not just "
          "sigh at it.",
          lambda s, e: e.get("recent_ally_deaths", 0) >= 2),

    Angle("ally_death_while_ahead",
          "Your team is ahead and still handing kills over. Be exasperated "
          "that a won position is being donated back, not bored.",
          lambda s, e: s.kill_lead >= 4),

    Angle("ally_death_while_behind",
          "You are already behind and that just made it worse. Flat, tired, "
          "no energy left for outrage — this is the tone of someone watching "
          "a result they saw coming.",
          lambda s, e: s.kill_lead <= -4),

    Angle("ally_death_late_stakes",
          "It is late enough that respawns are long and this one actually "
          "costs something. Drop the boredom; treat it as a real problem.",
          lambda s, e: s.phase == "late"),

    Angle("ally_death_early_shrug",
          "It is barely into the game. Genuinely too early to care — be "
          "briefly, almost affectionately dismissive.",
          lambda s, e: s.phase == "early" and e.get("recent_ally_deaths", 0) < 2),

    Angle("ally_death_repeat_victim",
          "This same champion has died before and has not learned anything. "
          "Aim it at them specifically, by champion name.",
          lambda s, e: e.get("victim_deaths", 0) >= 2),

    Angle("ally_death_soul_pressure",
          "Losing bodies right now, with a soul drake on the line, is worse "
          "than usual. Connect the two.",
          lambda s, e: bool(s.soul_point)),

    Angle("ally_death_compare_to_exiled",
          "Compare it to how Exiled's own game is going — you are keeping "
          "score, and right now his line reads better than theirs.",
          lambda s, e: s.deaths + 2 <= e.get("victim_deaths", 99)),

    # These name a specific player. The team totals say who is winning; only
    # the scoreboard rows say who is doing it, and "Jinx is one and nine" lands
    # where "your team is behind" does not.
    Angle("ally_death_worst_offender",
          "One teammate is having a visibly worse game than the rest, and the "
          "scoreboard says who. Name that champion and their line. Do not "
          "generalise it to the whole team — this is about one player.",
          lambda s, e: (s.worst_ally() is not None
                        and e.get("victim_champion") == s.worst_ally().champion)),

    Angle("ally_death_to_their_carry",
          "The enemy who killed them is the one running away with this game. "
          "Name them and what they are on. Keep it to the fact.",
          lambda s, e: (s.biggest_threat() is not None
                        and e.get("killer_champion") == s.biggest_threat().champion)),

    Angle("ally_death_exiled_carrying",
          "He is outperforming everyone on his own team and this is one more "
          "of them dying while he does it. Say it as a comparison, using both "
          "lines from the scoreboard.",
          lambda s, e: s.carrying()),

    Angle("ally_death_bored",
          "You barely care. A bored, offhand one-liner — the verbal "
          "equivalent of not looking up.",
          _always),

    Angle("ally_death_not_his_fault",
          "This one is not Exiled's to answer for. Say so — he is doing his "
          "job and this happened anyway.",
          _always),

    Angle("ally_death_barely_there",
          "Half a sentence. Acknowledge it and drop it, like you have "
          "something better to look at.",
          _always),

    Angle("ally_death_deadpan",
          "Completely deadpan. State what happened with no colour at all and "
          "let the flatness be the joke.",
          _always),
]

# =============================================================
# Ally kills
# =============================================================

ALLY_KILL = [
    Angle("ally_kill_surprised",
          "Your team has been losing this game, so a kill from them is a "
          "genuine surprise. Be surprised, and let it be a little insulting.",
          lambda s, e: s.kill_lead <= -3),

    Angle("ally_kill_snowball",
          "Your team is well ahead. Do not congratulate anyone — note that "
          "the game is being decided and it is nearly over.",
          lambda s, e: s.kill_lead >= 5),

    Angle("ally_kill_grudging",
          "Grudging credit. You will admit it was fine, and immediately "
          "undercut yourself for admitting it.",
          _always),

    Angle("ally_kill_late",
          "This late, one pick can open the map. Treat it as leverage rather "
          "than a highlight.",
          lambda s, e: s.phase == "late"),

    Angle("ally_kill_bored",
          "Offhand. One line, barely looking up.",
          _always),

    Angle("ally_kill_suspicious",
          "Treat it as an accident that worked. You are not convinced anyone "
          "meant for that to happen.",
          _always),
]

# =============================================================
# Dragons — the user asked for these specifically
# =============================================================

DRAGON = [
    Angle("dragon_soul_ours",
          "That took soul FOR your team. This is the biggest objective swing "
          "in the game so far — say it plainly, and let yourself be pleased.",
          lambda s, e: s.soul_taken == "ours" and e.get("side") == "mine"),

    Angle("dragon_soul_theirs",
          "They just took soul. This is bad and you are not going to soften "
          "it. Short, cold, no joke at the end.",
          lambda s, e: s.soul_taken == "theirs" and e.get("side") == "enemy"),

    Angle("dragon_soul_point_theirs",
          "They are now one drake from soul. Say what that means for the "
          "next one — the stakes changed, not the scoreline.",
          lambda s, e: s.soul_point in ("theirs", "both")),

    Angle("dragon_soul_point_ours",
          "One more and soul is yours. Point at the next one, not this one.",
          lambda s, e: s.soul_point in ("ours", "both")),

    Angle("dragon_stack_lead",
          "Your team is stacking drakes and it is becoming a pattern. Note "
          "the count out loud.",
          lambda s, e: s.dragon_lead >= 2),

    Angle("dragon_stack_behind",
          "They keep taking these uncontested. Be pointed about the fact "
          "that nobody is showing up for them.",
          lambda s, e: s.dragon_lead <= -2),

    Angle("dragon_traded_badly",
          "Objectives are going one way while kills go the other. Point out "
          "the mismatch — it is the actual story of this game.",
          lambda s, e: (s.dragon_lead <= -1 and s.kill_lead >= 3)
                       or (s.dragon_lead >= 1 and s.kill_lead <= -3)),

    Angle("dragon_first_shrug",
          "First drake of the game and worth almost nothing. Be honestly "
          "unimpressed that this is being announced at all.",
          lambda s, e: len(s.ours.dragons) + len(s.theirs.dragons) <= 1),

    Angle("dragon_one_man_band",
          "Every drake your team has was taken by the same person. Name them. "
          "That is not a team stacking objectives, it is one player doing it.",
          lambda s, e: (len(s.ours.dragons) >= 2
                        and len(set(s.ours.objective_takers)) == 1)),

    Angle("dragon_he_took_it",
          "He took this one himself. Credit him specifically, briefly, and do "
          "not extend it to the team.",
          lambda s, e: e.get("taker") and e.get("taker") == s.champion),

    Angle("dragon_bored",
          "A drake. Thrilling. Offhand, one line, do not look up.",
          _always),

    Angle("dragon_count_only",
          "Just say where the drake count stands now. No opinion, no joke — "
          "a scoreboard read, delivered flat.",
          _always),

    Angle("dragon_who_showed_up",
          "Someone had to be there for that and someone did not. Make it "
          "about attendance rather than the drake.",
          _always),
]

# =============================================================
# Baron and herald
# =============================================================

BARON = [
    Angle("baron_late_closing",
          "Baron this late usually ends games. Treat it as the closing move "
          "it probably is.",
          lambda s, e: s.phase == "late"),

    Angle("baron_while_behind",
          "You needed this. Say what it buys — a way back in, not a "
          "victory lap.",
          lambda s, e: e.get("side") == "mine" and s.kill_lead <= -3),

    Angle("baron_enemy_pressure",
          "They have Baron and your towers are already going. Be blunt "
          "about what is about to happen to the base.",
          lambda s, e: e.get("side") == "enemy" and s.turret_lead <= -2),

    Angle("baron_plain",
          "React to the Baron itself. One or two sentences, no wind-up.",
          _always),

    Angle("baron_what_now",
          "Baron is only worth what gets done with it. Point at what should "
          "happen next rather than at the buff.",
          _always),

    Angle("baron_flat",
          "Flat and short. Name it, and let the lack of reaction carry it.",
          _always),
]

HERALD = [
    Angle("herald_tower_value",
          "Herald is only ever worth the tower it takes. Say that, and be "
          "sceptical anyone will use it properly.",
          _always),

    Angle("herald_late_pointless",
          "Herald this late is nearly meaningless. Be openly unimpressed by "
          "the timing.",
          lambda s, e: s.minutes >= 18),

    Angle("herald_bored",
          "Rift Herald. Thrilling. One bored line.",
          _always),

    Angle("herald_who_cares",
          "Be openly uninterested that this is the thing being announced to "
          "you. One line.",
          _always),
]

# =============================================================
# His own play
# =============================================================

MY_KILL = [
    Angle("my_kill_carrying",
          "He is the reason this game is going well and the rest of the team "
          "is not keeping up. Say it as a fact you are keeping track of.",
          lambda s, e: s.kills >= 5 and s.kill_lead >= 0),

    Angle("my_kill_lonely",
          "He is doing his part while the team loses everywhere else. "
          "Approving of him and unimpressed by everyone else, in one breath.",
          lambda s, e: s.kills >= 3 and s.kill_lead <= -3),

    Angle("my_kill_cs_dig",
          "Take the kill, then needle him about his CS — the number is not "
          "flattering and you have been watching it.",
          lambda s, e: s.minutes >= 10 and 0 < s.cs_per_min < 5.5),

    Angle("my_kill_outclassing_team",
          "His line is better than every one of his teammates'. Say which of "
          "them he is carrying, by champion and number — the scoreboard is in "
          "front of you.",
          lambda s, e: s.carrying() and bool(s.allies)),

    Angle("my_kill_clean",
          "Short, clean approval. You do not gush; you note it and move on.",
          _always),

    Angle("my_kill_expected",
          "Act as though you expected nothing less. Approval disguised as a "
          "standard being met.",
          _always),

    Angle("my_kill_almost_proud",
          "You are closer to proud than you would like to admit, and you "
          "cover it badly. One sentence.",
          _always),
]

MY_DEATH = [
    Angle("my_death_first",
          "First death of the game. Almost gentle — mark it, do not "
          "prosecute it.",
          lambda s, e: e.get("death_count", 1) == 1),

    Angle("my_death_traded",
          "He got something for it. Grudgingly allow that it was a trade "
          "rather than a gift.",
          lambda s, e: e.get("was_trade", False)),

    Angle("my_death_pattern",
          "The same thing keeps happening. Point at the pattern rather than "
          "this one death.",
          lambda s, e: e.get("death_count", 1) >= 3),

    Angle("my_death_while_ahead",
          "He was ahead and just gave some of it back. Frustration, because "
          "this one was avoidable.",
          lambda s, e: s.kill_lead >= 3),

    Angle("my_death_late_costly",
          "Late game, long respawn, and the map is now open. Be direct about "
          "the cost instead of making a joke.",
          lambda s, e: s.phase == "late"),

    Angle("my_death_told_you",
          "He warned you about this champion himself, before the game. Say so "
          "— not smug, just the tone of someone who was listening. Stay inside "
          "what he actually told you; add no read of your own.",
          lambda s, e: e.get("killer_has_note", False)),

    Angle("my_death_plain",
          "React to the death itself. Disappointed, dismissive, your call.",
          _always),

    Angle("my_death_quiet",
          "Say almost nothing. A short, quiet line — you are not going to "
          "kick him while he is already annoyed.",
          _always),

    Angle("my_death_question",
          "Ask him one pointed question about what he thought was going to "
          "happen. Do not answer it for him.",
          _always),
]

# =============================================================
# Structures
# =============================================================

TURRET = [
    Angle("turret_map_pressure",
          "Towers are going one way in this game. Say what the map looks "
          "like now, not what just happened.",
          lambda s, e: abs(s.turret_lead) >= 3),

    Angle("turret_plain",
          "A tower. Note it, briefly, and do not dress it up.",
          _always),

    Angle("turret_credit",
          "Give him the credit for it, plainly and without ceremony.",
          _always),

    Angle("turret_unimpressed",
          "A building. Be visibly unmoved that this counts as an event.",
          _always),
]

INHIB = [
    Angle("inhib_closing",
          "An inhibitor is gone and the game is close to over. Say which "
          "way it is going.",
          _always),

    Angle("inhib_late_swing",
          "Super minions this late decide games. Be blunt about it.",
          lambda s, e: s.phase == "late"),

    Angle("inhib_pressure",
          "Say what the base looks like now. Concrete, not dramatic.",
          _always),

    Angle("inhib_short",
          "One clipped line. The situation speaks for itself.",
          _always),
]

# =============================================================
# Fights he was not in
# =============================================================

TEAMFIGHT_MISSED = [
    Angle("missed_where_were_you",
          "A fight happened and he was not in it. Ask where he was, and mean "
          "it — you are keeping score.",
          _always),

    Angle("missed_farming_defence",
          "He was farming instead, and the CS number either justifies it or "
          "does not. Use the number.",
          lambda s, e: s.minutes >= 8),

    Angle("missed_they_lost_it",
          "They fought without him and lost it. Let that be the point: they "
          "chose that.",
          lambda s, e: s.kill_lead < 0),

    Angle("missed_they_won_it",
          "They fought without him and actually won. Be a little offended on "
          "his behalf that it worked.",
          lambda s, e: s.kill_lead > 0),

    Angle("missed_no_call",
          "Nobody told him it was happening, and you are choosing to believe "
          "that. Defend him, sourly.",
          _always),

    Angle("missed_dry",
          "Dry and short. Note that a fight happened somewhere he was not.",
          _always),
]

ACE = [
    Angle("ace_ours",
          "Your team aced them. The map is completely open — say what should "
          "happen next, not how nice it was.",
          lambda s, e: e.get("side") == "mine"),

    Angle("ace_theirs",
          "Your whole team is dead at once. Embarrassment, not analysis.",
          lambda s, e: e.get("side") != "mine"),

    Angle("ace_flat",
          "State it flatly. Five of them, all dead, no commentary.",
          _always),

    Angle("ace_what_now",
          "An ace is a window, not a result. Say what it is worth if nobody "
          "uses it.",
          _always),

    Angle("ace_short",
          "One word to three. That is the whole reaction.",
          _always),
]

GAME_START = [
    # These four read from data/champions.json — HIS notes, not game knowledge.
    # They only fire when he actually wrote something, so an empty file leaves
    # the generic openers below doing exactly what they did before.
    Angle("start_matchup_note",
          "He has told you something about facing one of the champions on the "
          "enemy team. Open with that — in his voice, as a thing he admits "
          "rather than a thing you worked out. Do not add a read of your own "
          "about the matchup.",
          lambda s, e: e.get("has_matchup_note", False)),

    Angle("start_offrole",
          "He is playing this champion somewhere he does not normally play "
          "it, and he has said as much himself. Open on that — indulgent, "
          "not scathing. He knows.",
          lambda s, e: e.get("is_offrole", False)),

    Angle("start_champion_history",
          "He has history with this champion and has told you about it. Bring "
          "it up as the first thing you say, the way someone brings up a "
          "pattern they have watched for a while.",
          lambda s, e: e.get("has_champion_history", False)),

    Angle("start_role_read",
          "He has told you what he is like in this role. Open on that — his "
          "own assessment, said back to him.",
          lambda s, e: e.get("has_role_note", False)),

    Angle("start_their_threat",
          "Someone on the enemy team is already ahead of everyone. Name them "
          "and their line, nothing more.",
          lambda s, e: s.biggest_threat() is not None),

    Angle("start_matchup",
          "The game is starting and you can see both teams. Name what he is "
          "playing and one thing you notice about who he is up against — "
          "only what the champion list actually tells you.",
          lambda s, e: bool(s.enemy_champions)),

    Angle("start_focus",
          "Game starting. Short, expectant, a little demanding.",
          _always),

    Angle("start_low_expectations",
          "Set the bar somewhere he can clear. Affectionate, barely.",
          _always),

    Angle("start_watching",
          "Tell him you are watching. Not encouragement — notice.",
          _always),
]

GAME_END = [
    Angle("end_his_line",
          "The game is over. Reference his own final line — the numbers are "
          "in front of you.",
          lambda s, e: s.kills + s.deaths + s.assists > 0),

    Angle("end_objectives",
          "The game is over and the objective count explains it better than "
          "the kills do. Use that.",
          lambda s, e: abs(s.dragon_lead) >= 2 or abs(s.turret_lead) >= 3),

    Angle("end_plain",
          "React to the result. Smug if won, annoyed if lost.",
          _always),

    Angle("end_next_one",
          "The game is over. Point at the next one instead of dwelling.",
          _always),

    Angle("end_short",
          "One sentence on the result. Do not review the game.",
          _always),
]


ANGLES: dict[str, list[Angle]] = {
    "AllyDeath": ALLY_DEATH,
    "AllyKill": ALLY_KILL,
    "DragonKill": DRAGON,
    "BaronKill": BARON,
    "HeraldKill": HERALD,
    "MyKill": MY_KILL,
    "MyKillSpree": MY_KILL,
    "MyMultikill": MY_KILL,
    "MyDeath": MY_DEATH,
    "TurretKilled": TURRET,
    "InhibKilled": INHIB,
    "TeamfightMissed": TEAMFIGHT_MISSED,
    "Ace": ACE,
    "GameStart": GAME_START,
    "GameEnd": GAME_END,
}


class AngleChooser:
    """
    Picks an angle per event, remembering what it recently used.

    One instance per source, cleared between games — a fresh game should be
    allowed to open on the same angle the last one closed with.
    """

    def __init__(self, memory: int = RECENT_MEMORY):
        self._recent: deque[str] = deque(maxlen=memory)

    def reset(self) -> None:
        self._recent.clear()

    def choose(self, event_type: str, state: GameState,
               extra: dict | None = None) -> Angle | None:
        """
        The least recently used angle whose facts are currently true.

        Returns None for event types with no angles, which leaves the notebook
        on its old templates — this degrades to today's behaviour rather than
        going silent.
        """
        candidates = ANGLES.get(event_type)
        if not candidates:
            return None

        extra = extra or {}
        eligible = [a for a in candidates if _safe(a, state, extra)]
        if not eligible:
            return None

        # Least recently used wins, so lower sorts better: -1 for an angle
        # that is not in memory at all, then its position in the deque, oldest
        # first. The LAST occurrence is what counts — an angle used at both
        # ends of the window was, in fact, just used.
        #
        # Ties keep list order, because min() returns the first minimal
        # element. That is why the generic fallback sits last in every list:
        # among equally unused angles the situation-driven ones win.
        history = list(self._recent)

        def staleness(angle: Angle) -> int:
            for i in range(len(history) - 1, -1, -1):
                if history[i] == angle.id:
                    return i
            return -1           # never used — as stale as it gets

        chosen = min(eligible, key=staleness)
        self._recent.append(chosen.id)
        return chosen


def _safe(angle: Angle, state: GameState, extra: dict) -> bool:
    """A broken predicate must not take her voice away for the rest of a game."""
    try:
        return bool(angle.when(state, extra))
    except Exception as e:
        print(f"[angles] {angle.id} predicate failed: {e}")
        return False
