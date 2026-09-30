from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import ref_dir


def _load(name: str) -> dict[str, Any]:
    path = ref_dir() / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save(name: str, payload: dict[str, Any]) -> None:
    path = ref_dir() / name
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def heroes() -> list[dict[str, Any]]:
    return _load("heroes.json")["heroes"]


def save_heroes(items: list[dict[str, Any]]) -> None:
    payload = _load("heroes.json")
    payload["heroes"] = items
    _save("heroes.json", payload)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


ART_FOLDERS = {"ban": "ban", "pick": "heropick"}
ART_ALIASES = {"illumia": "ilumia", "jinna": "jinnar"}


def art_files() -> dict[str, list[str]]:
    """Image files on disk per kind, from data/ref/art (local only, gitignored)."""
    out = {}
    for kind, folder in ART_FOLDERS.items():
        d = ref_dir() / "art" / folder
        out[kind] = sorted(p.name for p in d.glob("*.png")) if d.exists() else []
    return out


def guess_art_map() -> dict[str, dict[str, Any]]:
    """Match art files to heroes by filename. Used until art-map.json exists."""
    idx: dict[str, str] = {}
    for h in heroes():
        idx[_norm(h["name"])] = h["id"]
        idx[_norm(h["id"])] = h["id"]
    for alias, hid in ART_ALIASES.items():
        idx[alias] = hid
    out: dict[str, dict[str, Any]] = {h["id"]: {"ban": None, "pick": None, "checked": False} for h in heroes()}
    for kind, files in art_files().items():
        for name in files:
            hid = idx.get(_norm(Path(name).stem))
            if hid and out[hid][kind] is None:
                out[hid][kind] = name
    return out


def art_map() -> dict[str, dict[str, Any]]:
    """hero id -> {ban: file, pick: file, checked: bool}. Saved in art-map.json once reviewed."""
    path = ref_dir() / "art-map.json"
    if path.exists():
        saved = _load("art-map.json")["map"]
    else:
        saved = {}
    guessed = guess_art_map()
    out = {}
    for h in heroes():
        entry = {**guessed.get(h["id"], {"ban": None, "pick": None, "checked": False}), **saved.get(h["id"], {})}
        out[h["id"]] = entry
    return out


def save_art_map(mapping: dict[str, dict[str, Any]]) -> None:
    _save("art-map.json", {"note": "hero id -> art file per kind; reviewed on the Heroes page", "map": mapping})


def hero_ids() -> set[str]:
    return {h["id"] for h in heroes()}


def hero_forms() -> dict[str, list[str]]:
    return {h["id"]: h.get("forms", []) for h in heroes() if h.get("forms")}


def teams() -> list[dict[str, Any]]:
    return _load("teams.json")["teams"]


def team_ids() -> set[str]:
    return {t["id"] for t in teams()}


def tournaments() -> list[dict[str, Any]]:
    return _load("tournaments.json")["tournaments"]


def layout(layout_id: str) -> dict[str, Any]:
    path = ref_dir() / "layouts" / f"{layout_id}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


LANES = ["DSL", "JGL", "MID", "ADL", "SUP"]


def roster() -> dict[str, list[dict[str, Any]]]:
    """The team master: per team, each player with the position they play. Files written before
    the master existed hold bare names."""
    raw = _load("players.json")["players"]
    return {team: [{"name": p, "lane": None} if isinstance(p, str) else {"name": p["name"], "lane": p.get("lane")} for p in items]
            for team, items in raw.items()}


def save_roster(rosters: dict[str, list[dict[str, Any]]]) -> None:
    payload = _load("players.json")
    payload["players"] = {**roster(), **rosters}
    _save("players.json", payload)


def players() -> dict[str, list[str]]:
    return {team: [p["name"] for p in items] for team, items in roster().items()}


def add_players(team: str, names: list[str]) -> dict[str, list[str]]:
    rosters = roster()
    members = rosters.setdefault(team, [])
    lower = {p["name"].lower() for p in members}
    for name in names:
        name = name.strip()
        if name and name.lower() not in lower:
            members.append({"name": name, "lane": None})
            lower.add(name.lower())
    save_roster(rosters)
    return players()


def _stages() -> list[dict[str, str]]:
    from .models import STAGES

    return STAGES


def bundle() -> dict[str, Any]:
    """Everything the form needs in one response."""
    return {
        "heroes": heroes(),
        "teams": teams(),
        "tournaments": tournaments(),
        "players": players(),
        "roster": roster(),
        "layouts": {t["layout"]: layout(t["layout"]) for t in tournaments()},
        "lanes": LANES,
        "stages": _stages(),
        "artMap": art_map(),
    }
