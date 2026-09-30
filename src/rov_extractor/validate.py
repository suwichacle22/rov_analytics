"""Draft-rule validation. Returns issues; errors block saving, warnings do not."""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import refdata
from .models import GameInput, Series, ValidationIssue
from .layout import build_sequence


def validate_game(series: Series, game: GameInput, earlier: list[dict[str, Any]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    err = lambda code, msg, field=None: issues.append(ValidationIssue(level="error", code=code, message=msg, field=field))
    warn = lambda code, msg, field=None: issues.append(ValidationIssue(level="warning", code=code, message=msg, field=field))

    hero_ids = refdata.hero_ids()
    forms = refdata.hero_forms()
    teams = {series.teamA, series.teamB}
    blue = game.blueTeam
    red = series.teamB if blue == series.teamA else series.teamA

    if blue not in teams:
        err("blue-team", "Blue side must be one of the two teams in the match", "blueTeam")
    if game.winner not in teams:
        err("winner", "Winner must be set", "winner")
    if not game.durationS or game.durationS <= 0:
        err("duration", "Duration must be set", "durationS")
    if not series.date:
        err("date", "Match date is missing", "date")

    # Series state: no game after the series is decided; earlier games should exist
    need = series.bestOf // 2 + 1
    wins: dict[str, int] = {series.teamA: 0, series.teamB: 0}
    seen = set()
    for g in earlier:
        seen.add(g.get("gameNo"))
        if g.get("winner"):
            wins[g["winner"]] = wins.get(g["winner"], 0) + 1
    decided = next((t for t, w in wins.items() if w >= need), None)
    if decided:
        err("series-decided", f"{decided} already won this match {wins[series.teamA]}-{wins[series.teamB]}. Game {game.gameNo} cannot exist.")
    missing = [n for n in range(1, game.gameNo) if n not in seen]
    if missing:
        warn("series-gap", f"Games {missing} are not saved yet, so Global Ban-Pick and the match score are only partly checked.")
    if game.gameNo > series.bestOf:
        err("game-no", f"Game {game.gameNo} is beyond a Bo{series.bestOf}")

    layout = refdata.layout(series.layout)
    actions = build_sequence(layout, game.slots.model_dump(), blue, red)

    # Every slot filled with a known hero
    for a in actions:
        field = f"slots.{a['side']}{'Bans' if a['action']=='ban' else 'Picks'}.{a['slot']-1}"
        if not a["hero"]:
            err("empty-slot", f"{a['action'].title()} {a['order']} ({a['side']} slot {a['slot']}) is empty", field)
        elif a["hero"] not in hero_ids:
            err("unknown-hero", f"Unknown hero '{a['hero']}' at {a['action']} {a['order']}", field)
        elif a["action"] == "ban" and a["hero"] in forms and not a.get("form"):
            err("missing-form", f"{a['hero']} is banned by form. Pick the form for ban {a['order']}", field)

    # No hero twice in a game (a Flowborn form ban blocks that form only; treat forms as distinct on bans)
    keys = []
    for a in actions:
        if not a["hero"]:
            continue
        if a["action"] == "ban" and a.get("form"):
            keys.append(f"{a['hero']}/{a['form']}")
        else:
            keys.append(a["hero"])
    for hero, n in Counter(keys).items():
        if n > 1:
            err("duplicate-hero", f"{hero} appears {n} times in this game")

    # Global Ban-Pick: a team cannot pick a hero it picked earlier in the series, except game 7 of a Bo7
    exempt = series.bestOf == 7 and game.gameNo == 7
    if not exempt:
        used: dict[str, set[str]] = {series.teamA: set(), series.teamB: set()}
        for g in earlier:
            for a in g.get("draft", []):
                if a.get("action") == "pick" and a.get("hero"):
                    used.setdefault(a["team"], set()).add(a["hero"])
        for a in actions:
            if a["action"] == "pick" and a["hero"] and a["hero"] in used.get(a["team"], set()):
                err("global-ban-pick", f"{a['team']} already picked {a['hero']} earlier in this match (Global Ban-Pick)")

    # Players: five per team, distinct names, distinct lanes, heroes equal the team's picks
    picks_by_team = {t: sorted(a["hero"] for a in actions if a["action"] == "pick" and a["team"] == t and a["hero"]) for t in (blue, red)}
    for team in (blue, red):
        rows = [p for p in game.players if p.team == team]
        if len(rows) != 5:
            err("players-count", f"{team} needs 5 player rows, has {len(rows)}")
            continue
        names = [p.player for p in rows]
        if any(not n for n in names):
            err("player-name", f"{team}: every row needs a player name")
        elif len({n.lower() for n in names if n}) != 5:
            err("player-dup", f"{team}: player names must be distinct")
        lanes = [p.lane for p in rows]
        if any(not l for l in lanes):
            err("lane", f"{team}: every row needs a lane")
        elif len(set(lanes)) != 5:
            err("lane-dup", f"{team}: lanes must be distinct")
        heroes = sorted(p.hero for p in rows if p.hero)
        if len(heroes) != 5:
            err("player-hero", f"{team}: every row needs the hero played (post-swap)")
        elif heroes != picks_by_team[team] and len(picks_by_team[team]) == 5:
            missing = set(picks_by_team[team]) - set(heroes)
            extra = set(heroes) - set(picks_by_team[team])
            err("hero-mismatch", f"{team}: post-swap heroes do not match the picks. Missing {sorted(missing)}, extra {sorted(extra)}")
        missing_kda = [p.player or f"row {i + 1}" for i, p in enumerate(rows) if any(getattr(p, k) is None for k in ("kills", "deaths", "assists"))]
        if missing_kda:
            warn("kda", f"{team}: K/D/A not set for {', '.join(missing_kda)}")

    for team in (blue, red):
        ts = game.teamStats.get(team)
        if ts is None or ts.kills is None:
            warn("team-stats", f"{team}: team totals not set")

    if game.winner in teams and all(game.teamStats.get(t) and game.teamStats[t].towers is not None for t in (blue, red)):
        loser = red if game.winner == blue else blue
        if game.teamStats[loser].towers > game.teamStats[game.winner].towers:
            warn("towers-vs-winner", "Loser has more towers than the winner. Check the result.")

    if not game.images.get("draft"):
        warn("image-draft", "No draft-bar image attached")
    if not game.images.get("post"):
        warn("image-post", "No post-game image attached")

    return issues
