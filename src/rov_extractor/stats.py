"""Draft statistics of one team, computed from the games on disk.

A saved game counts as checked. A game that only has a draft (filled by Recognise or typed half
way) is included and marked unchecked, so the dashboard shows something before every game is
confirmed. Slots without a hero are left out of the hero tables and counted in `coverage`.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import refdata, store
from .models import GameInput

# Pick numbers that are made in one turn, in draft order.
TURNS = [(1,), (2, 3), (4, 5), (6,), (7,), (8, 9), (10,)]
TEAM_STATS = ("kills", "gold", "towers", "dragons", "slayers")


def games_in_scope() -> list[dict[str, Any]]:
    """Every game with at least one hero entered, oldest first, as a game record."""
    out = []
    for s in store.list_series():
        series = store.load_series(s["seriesId"])
        for n in sorted(set(s["games"]) | set(s["drafts"])):
            rec = store.load_game(series.seriesId, n)
            checked = rec is not None
            if rec is None:
                try:
                    rec = store.build_game_record(series, GameInput(**store.load_game(series.seriesId, n, draft=True)))
                except Exception:  # noqa: BLE001  a half-typed draft that does not parse is skipped
                    continue
            if not any(a.get("hero") for a in rec["draft"]):
                continue
            rec["checked"] = checked
            out.append(rec)
    out.sort(key=lambda g: (g["date"], g["seriesId"], g["gameNo"]))
    return out


class Tally:
    """Counts per hero, with the games behind each count for the tooltip."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def add(self, hero: str, game: dict[str, Any], **extra: Any) -> dict[str, Any]:
        row = self.rows.setdefault(hero, {"hero": hero, "games": 0, "wins": 0, "losses": 0, "where": []})
        row["games"] += 1
        if game["won"] is True:
            row["wins"] += 1
        elif game["won"] is False:
            row["losses"] += 1
        row["where"].append({"opp": game["opp"], "n": game["gameNo"], "date": game["date"], "won": game["won"], **extra})
        return row

    def list(self) -> list[dict[str, Any]]:
        rows = sorted(self.rows.values(), key=lambda r: (-r["games"], -r["wins"], r["hero"]))
        return [{k: (dict(v) if isinstance(v, Counter) else v) for k, v in r.items()} for r in rows]


def _bump(row: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        row.setdefault(key, Counter())[value] += 1


def _avg(values: list[float], digits: int = 0) -> float | None:
    if not values:
        return None
    v = sum(values) / len(values)
    return round(v, digits) if digits else round(v)


def team_stats(team: str, stage: str | None = None, games: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    games = [g for g in (games_in_scope() if games is None else games)
             if team in (g["blue"], g["red"]) and (not stage or g["stage"] == stage)]
    picks, bans, bans_vs, opp_picks = Tally(), Tally(), Tally(), Tally()
    first_blue, first_red, first_faced = Tally(), Tally(), Tally()
    meta: dict[str, dict[str, Any]] = {}
    players: dict[str, dict[str, Any]] = {}
    lane_order: dict[str, list[int]] = {lane: [0] * 5 for lane in refdata.LANES}
    pairs: Counter = Counter()
    pair_wins: Counter = Counter()
    matches: dict[str, dict[str, Any]] = {}
    sides = {side: {"games": 0, "wins": 0, "losses": 0} for side in ("blue", "red")}
    durations: dict[str, list[int]] = {"all": [], "wins": [], "losses": []}
    totals = {who: {k: [] for k in TEAM_STATS} for who in ("team", "opp")}
    cov = {"games": len(games), "checked": 0, "slots": 0, "unnamed": 0, "noWinner": 0}

    for g in games:
        side = "blue" if g["blue"] == team else "red"
        g["opp"] = g["red"] if side == "blue" else g["blue"]
        g["won"] = None if not g.get("winner") else g["winner"] == team
        result = None if g["won"] is None else "wins" if g["won"] else "losses"
        cov["checked"] += 1 if g["checked"] else 0
        cov["noWinner"] += 1 if result is None else 0
        sides[side]["games"] += 1
        if result:
            sides[side][result] += 1
        if g.get("durationS"):
            durations["all"].append(g["durationS"])
            if result:
                durations[result].append(g["durationS"])
        for who, name in (("team", team), ("opp", g["opp"])):
            for k in TEAM_STATS:
                v = (g.get("teamStats", {}).get(name) or {}).get(k)
                if v is not None:
                    totals[who][k].append(v)

        m = matches.setdefault(g["seriesId"], {"seriesId": g["seriesId"], "date": g["date"], "opp": g["opp"], "bestOf": g["bestOf"],
                                                "stage": g["stage"], "games": [], "wins": 0, "losses": 0})
        m["games"].append({"n": g["gameNo"], "side": side, "won": g["won"], "durationS": g.get("durationS"), "checked": g["checked"],
                           "unnamed": sum(1 for a in g["draft"] if not a.get("hero"))})
        if result:
            m[result] += 1

        mine_no = 0
        by_order: dict[int, dict[str, Any]] = {}
        for a in g["draft"]:
            cov["slots"] += 1
            hero = a.get("hero")
            if a["action"] == "pick":
                by_order[a["order"]] = a
            if not hero:
                cov["unnamed"] += 1
                continue
            mine = a["team"] == team
            row = meta.setdefault(hero, {"hero": hero, "picks": 0, "bans": 0, "wins": 0, "losses": 0, "teamPicks": 0, "teamBans": 0, "oppPicks": 0, "oppBans": 0})
            if a["action"] == "ban":
                row["bans"] += 1
                row["teamBans" if mine else "oppBans"] += 1
                r = (bans if mine else bans_vs).add(hero, g, phase=a["phase"])
                _bump(r, "phases", a["phase"])
                continue
            row["picks"] += 1
            row["teamPicks" if mine else "oppPicks"] += 1
            if result:  # the record of the team that picked the hero
                row["wins" if g["won"] == mine else "losses"] += 1
            if not mine:
                opp_picks.add(hero, g, player=a.get("player"))
                if a["order"] == 1:
                    first_faced.add(hero, g)
                continue
            mine_no += 1
            r = picks.add(hero, g, player=a.get("player"), order=a["order"])
            _bump(r, "players", a.get("player"))
            if a.get("lane") in lane_order:
                lane_order[a["lane"]][mine_no - 1] += 1
            if a["order"] == 1:
                first_blue.add(hero, g, player=a.get("player"))
            elif a["order"] in (2, 3):
                first_red.add(hero, g, player=a.get("player"))

        # What the team picked right after the opponent's picks: every own turn is paired with the
        # opponent's turns that came just before it.
        turns = [[by_order[o] for o in turn if o in by_order] for turn in TURNS]
        for i, acts in enumerate(turns):
            if not acts or acts[0]["team"] != team:
                continue
            j = i - 1
            while j >= 0 and turns[j] and turns[j][0]["team"] == team:
                j -= 1
            before: list[dict[str, Any]] = []
            while j >= 0 and turns[j] and turns[j][0]["team"] != team:
                before += turns[j]
                j -= 1
            for x in before:
                for y in acts:
                    if x.get("hero") and y.get("hero"):
                        pairs[(x["hero"], y["hero"])] += 1
                        pair_wins[(x["hero"], y["hero"])] += 1 if g["won"] else 0

        for p in g.get("players") or []:
            if p.get("team") != team or not p.get("player"):
                continue
            row = players.setdefault(p["player"], {"lanes": Counter(), "games": 0, "heroes": Tally(), "kda": [0, 0, 0], "kdaGames": 0,
                                                     "dmgDealt": [], "dmgTaken": []})
            row["games"] += 1
            if p.get("lane"):
                row["lanes"][p["lane"]] += 1
            if p.get("hero"):
                row["heroes"].add(p["hero"], g)
            if all(p.get(k) is not None for k in ("kills", "deaths", "assists")):
                row["kdaGames"] += 1
                for i, k in enumerate(("kills", "deaths", "assists")):
                    row["kda"][i] += p[k]
            for k in ("dmgDealt", "dmgTaken"):
                if p.get(k) is not None:
                    row[k].append(p[k])

    record = {"wins": 0, "losses": 0, "open": 0}
    for m in matches.values():
        need = store.wins_needed(m["bestOf"])
        m["won"] = True if m["wins"] >= need else False if m["losses"] >= need else None
        record["open" if m["won"] is None else "wins" if m["won"] else "losses"] += 1

    lanes = refdata.LANES
    player_list = []
    for name, row in players.items():
        lane = row["lanes"].most_common(1)[0][0] if row["lanes"] else None
        player_list.append({"player": name, "lane": lane, "games": row["games"], "heroes": row["heroes"].list(),
                            "kills": row["kda"][0], "deaths": row["kda"][1], "assists": row["kda"][2], "kdaGames": row["kdaGames"],
                            "avgDmgDealt": _avg(row["dmgDealt"]), "avgDmgTaken": _avg(row["dmgTaken"])})
    player_list.sort(key=lambda p: (lanes.index(p["lane"]) if p["lane"] in lanes else len(lanes), -p["games"]))

    meta_list = sorted(meta.values(), key=lambda r: (-(r["picks"] + r["bans"]), -r["picks"], r["hero"]))
    for r in meta_list:
        r["presence"] = round((r["picks"] + r["bans"]) / (len(games) or 1), 3)

    return {
        "team": team,
        "stage": stage or "",
        "coverage": cov,
        "record": {"matches": record, "games": {k: sum(s[k] for s in sides.values()) for k in ("wins", "losses")}, "sides": sides,
                   "avgDurationS": _avg(durations["all"]), "avgWinS": _avg(durations["wins"]), "avgLossS": _avg(durations["losses"])},
        "matches": sorted(matches.values(), key=lambda m: (m["date"], m["seriesId"])),
        "picks": picks.list(),
        "bans": bans.list(),
        "bansAgainst": bans_vs.list(),
        "oppPicks": opp_picks.list(),
        "players": player_list,
        "openers": {"blue": first_blue.list(), "red": first_red.list(), "faced": first_faced.list()},
        "laneOrder": lane_order,
        "answers": [{"after": x, "then": y, "games": c, "wins": pair_wins[(x, y)]} for (x, y), c in pairs.most_common() if c >= 2],
        "meta": meta_list,
        "totals": {who: {k: {"avg": _avg(v, 1), "games": len(v)} for k, v in d.items()} for who, d in totals.items()},
    }


def dashboard(team: str | None = None, stage: str | None = None) -> dict[str, Any]:
    """What the Dashboard page shows. Without a team it takes the one with the most games.
    `stage` None means no choice was made: the team's only match type, or all of them. An empty
    string asks for all match types."""
    games = games_in_scope()
    teams: Counter = Counter()
    for g in games:
        teams[g["blue"]] += 1
        teams[g["red"]] += 1
    if team not in teams:
        team = teams.most_common(1)[0][0] if teams else (team or "")
    stages = Counter(g["stage"] for g in games if team in (g["blue"], g["red"]))
    if stage is None:
        stage = next(iter(stages)) if len(stages) == 1 else ""
    out = team_stats(team, stage or None, games)
    out["options"] = {"teams": dict(teams), "stages": dict(stages)}
    return out
