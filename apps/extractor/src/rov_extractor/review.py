"""What in a game still needs a look by a person.

Recognise proposes every value with a score. For a game that is not saved yet this lists the
values the user should look at before saving: a hero read with less than REVIEW_SCORE, a hero that
is not what Recognise read, a slot without a hero, a player name that was matched loosely, a
missing winner or game time. A value the user chose by hand or confirmed is not listed again, and
a saved game needs no review.
"""
from __future__ import annotations

import json
from typing import Any

from . import refdata, store

REVIEW_SCORE = 0.90  # a hero read below this score is shown to the user
SLOT_KEYS = ("blueBans", "redBans", "bluePicks", "redPicks")

_counts: dict[tuple[str, int], tuple[tuple[float, ...], int]] = {}


def _label(layout: dict[str, Any], key: str, i: int) -> str:
    """The number on the slot as the form shows it: B1 to B8, P1 to P10."""
    if key.endswith("Bans"):
        return f"B{layout[key[:-4]]['banSlots'][i]}"
    return f"P{layout[key[:-5]]['pickSlots'][i]}"


def _proposal(series_id: str, game_no: int) -> dict[str, Any]:
    p = store.series_path(series_id) / f"g{game_no}.proposal.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def review_game(series_id: str, game_no: int, data: dict[str, Any] | None, saved: bool) -> dict[str, Any]:
    """`data` is the form state of the game. Each item has a `key` that names the field
    (`slot:bluePicks.3`, `player:red.0`, `field:winner`), a `message`, and `confirm`: whether the
    user can settle it by saying the value is right."""
    if saved:
        return {"status": "saved", "count": 0, "items": []}
    if not data:
        return {"status": "none", "count": 0, "items": []}
    series = store.load_series(series_id)
    layout = refdata.layout(series.layout)
    names = {h["id"]: h["name"] for h in refdata.heroes()}
    prop = _proposal(series_id, game_no)
    read = (prop.get("draft") or {}).get("slots")
    post = (prop.get("post") or {}).get("players") or {}
    items: list[dict[str, Any]] = []

    slots = data.get("slots") or {}
    for key in SLOT_KEYS:
        for i, e in enumerate(slots.get(key) or []):
            label, hero = _label(layout, key, i), e.get("hero")
            if not hero:
                items.append({"key": f"slot:{key}.{i}", "message": f"{label} has no hero", "confirm": False})
                continue
            if e.get("confirmed") or read is None:
                continue
            ps = (read.get(key) or [])[i] if i < len(read.get(key) or []) else {}
            if ps.get("hero") == hero:
                score = float(ps.get("score") or 0)
                if score >= REVIEW_SCORE:
                    continue
                items.append({"key": f"slot:{key}.{i}", "message": f"{label} {names.get(hero, hero)}, read at {round(score * 100)}%",
                              "score": score, "confirm": True})
            else:
                items.append({"key": f"slot:{key}.{i}", "message": f"{label} {names.get(hero, hero)}, not what Recognise read", "confirm": True})

    if not data.get("winner"):
        items.append({"key": "field:winner", "message": "No winner", "confirm": False})
    if not data.get("durationS"):
        items.append({"key": "field:durationS", "message": "No game time", "confirm": False})

    blue = data.get("blueTeam") or series.teamA
    red = series.teamB if blue == series.teamA else series.teamA
    for side, team in (("blue", blue), ("red", red)):
        rows = [p for p in data.get("players") or [] if p.get("team") == team]
        guesses = post.get(side) or []
        for i, row in enumerate(rows):
            name = row.get("player")
            who = name or f"player {i + 1}"
            if not name:
                items.append({"key": f"player:{side}.{i}", "message": f"{team} {who}: no name", "confirm": False})
            elif not row.get("confirmed") and i < len(guesses) and guesses[i].get("player") == name and not guesses[i].get("playerConfident"):
                raw = guesses[i].get("playerRaw") or "?"
                why = "not in the team list" if raw.lower() == name.lower() else f"the screen reads {raw}"
                items.append({"key": f"player:{side}.{i}", "message": f"{team} {name}: {why}", "confirm": True})
            if not row.get("hero"):
                items.append({"key": f"playerhero:{side}.{i}", "message": f"{team} {who}: no hero", "confirm": False})
    return {"status": "draft", "count": len(items), "items": items}


def review(series_id: str, game_no: int) -> dict[str, Any]:
    """The review of a game as it is on disk."""
    saved = store.load_game(series_id, game_no) is not None
    return review_game(series_id, game_no, None if saved else store.load_game(series_id, game_no, draft=True), saved)


def count(series_id: str, game_no: int) -> int:
    """How many values of this game wait for the user. Kept until one of its files changes."""
    d = store.series_path(series_id)
    stamp = tuple(p.stat().st_mtime if p.exists() else 0.0
                  for p in (d / f"g{game_no}.json", d / f"g{game_no}.draft.json", d / f"g{game_no}.proposal.json", refdata.ref_dir() / "heroes.json"))
    hit = _counts.get((series_id, game_no))
    if hit is None or hit[0] != stamp:
        hit = (stamp, review(series_id, game_no)["count"])
        _counts[(series_id, game_no)] = hit
    return hit[1]


def counts(entry: dict[str, Any]) -> dict[int, int]:
    """Per unsaved game of one match from store.list_series(): values waiting for the user."""
    return {n: count(entry["seriesId"], n) for n in entry.get("drafts", [])}
