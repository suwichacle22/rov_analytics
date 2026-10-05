from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import refdata
from .layout import build_sequence
from .models import GameInput, Series, SeriesCreate
from .paths import series_dir


def series_id_for(s: SeriesCreate) -> str:
    """The id is fixed when the match is created and keeps that day even when the date is corrected
    later, so a second match that would get the same id takes a number."""
    base = f"{s.date}_{s.teamA}-{s.teamB}"
    sid, n = base, 1
    while series_exists(sid):
        n += 1
        sid = f"{base}-{n}"
    return sid


def series_path(series_id: str) -> Path:
    return series_dir() / series_id


def list_series() -> list[dict[str, Any]]:
    out = []
    for d in sorted(series_dir().iterdir(), reverse=True):
        f = d / "series.json"
        if d.is_dir() and f.exists():
            s = json.loads(f.read_text(encoding="utf-8"))
            games = sorted(int(m.group(1)) for p in d.glob("g*.json") if (m := re.fullmatch(r"g(\d+)\.json", p.name)))
            drafts = sorted(int(m.group(1)) for p in d.glob("g*.draft.json") if (m := re.fullmatch(r"g(\d+)\.draft\.json", p.name)))
            s["games"] = games
            s["drafts"] = [n for n in drafts if n not in games]
            s["score"] = series_score(s["seriesId"])
            out.append(s)
    return out


def create_series(s: SeriesCreate) -> Series:
    sid = series_id_for(s)
    d = series_path(sid)
    d.mkdir(parents=True, exist_ok=True)
    tournament = next((t for t in refdata.tournaments() if t["id"] == s.tournament), None)
    layout = tournament["layout"] if tournament else "rpl2026"
    series = Series(seriesId=sid, layout=layout, **s.model_dump())
    _write_json(d / "series.json", series.model_dump())
    return series


def load_series(series_id: str) -> Series:
    return Series(**json.loads((series_path(series_id) / "series.json").read_text(encoding="utf-8")))


def update_series(series_id: str, patch: dict[str, Any]) -> Series:
    s = load_series(series_id)
    merged = {**s.model_dump(), **{k: v for k, v in patch.items() if k in Series.model_fields and k != "seriesId"}}
    series = Series(**merged)
    _write_json(series_path(series_id) / "series.json", series.model_dump())
    return series


def load_game(series_id: str, game_no: int, draft: bool = False) -> dict[str, Any] | None:
    name = f"g{game_no}.draft.json" if draft else f"g{game_no}.json"
    p = series_path(series_id) / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_input(series_id: str, game_no: int) -> dict[str, Any] | None:
    """The form state for a game: the saved draft if present, otherwise the input embedded in the final file."""
    d = load_game(series_id, game_no, draft=True)
    if d is not None:
        return d
    g = load_game(series_id, game_no)
    if g is not None:
        return g.get("input")
    return None


def save_draft(series_id: str, game: GameInput) -> Path:
    p = series_path(series_id) / f"g{game.gameNo}.draft.json"
    _write_json(p, game.model_dump())
    return p


def build_game_record(series: Series, game: GameInput) -> dict[str, Any]:
    layout = refdata.layout(series.layout)
    blue = game.blueTeam
    red = series.teamB if blue == series.teamA else series.teamA
    actions = build_sequence(layout, game.slots.model_dump(), blue, red)
    played_by(actions, [p.model_dump() for p in game.players])
    first_pick = blue
    record = {
        "gameId": f"{series.seriesId}_g{game.gameNo}",
        "seriesId": series.seriesId,
        "tournament": series.tournament,
        "stage": series.stage,
        "bestOf": series.bestOf,
        "gameNo": game.gameNo,
        "date": series.date,
        "patch": game.patch or series.patch,
        "layout": series.layout,
        "blue": blue,
        "red": red,
        "firstPick": first_pick,
        "winner": game.winner,
        "durationS": game.durationS,
        "draft": actions,
        "players": [p.model_dump(exclude={"confirmed"}) for p in game.players],
        "teamStats": {k: v.model_dump() for k, v in game.teamStats.items()},
        "images": game.images,
        "notes": game.notes,
        "input": game.model_dump(),
        "savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return record


def save_game(series_id: str, game: GameInput) -> tuple[Path, dict[str, Any]]:
    series = load_series(series_id)
    record = build_game_record(series, game)
    p = series_path(series_id) / f"g{game.gameNo}.json"
    _write_json(p, record)
    draft = series_path(series_id) / f"g{game.gameNo}.draft.json"
    if draft.exists():
        draft.unlink()
    refresh_series_winner(series_id)
    return p, record


def wins_needed(best_of: int) -> int:
    return best_of // 2 + 1


def series_score(series_id: str) -> dict[str, Any]:
    """Wins per team from saved games, and the winner once a team reaches the target."""
    s = load_series(series_id)
    wins = {s.teamA: 0, s.teamB: 0}
    decided_in = None
    winner = None
    need = wins_needed(s.bestOf)
    for n in range(1, s.bestOf + 1):
        g = load_game(series_id, n)
        if g is None or not g.get("winner"):
            continue
        wins[g["winner"]] = wins.get(g["winner"], 0) + 1
        if winner is None and wins[g["winner"]] >= need:
            winner, decided_in = g["winner"], n
    return {"wins": wins, "winner": winner, "decidedIn": decided_in, "need": need}


def refresh_series_winner(series_id: str) -> Series:
    return update_series(series_id, {"winner": series_score(series_id)["winner"]})


def earlier_games(series_id: str, game_no: int) -> list[dict[str, Any]]:
    out = []
    for n in range(1, game_no):
        g = load_game(series_id, n)
        if g is not None:
            out.append(g)
    return out


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def series_exists(series_id: str) -> bool:
    """True for a real series folder. Rejects ids that would point outside data/series."""
    if not series_id or Path(series_id).name != series_id or series_id in (".", ".."):
        return False
    return (series_path(series_id) / "series.json").is_file()


def game_files(series_id: str, game_no: int) -> list[Path]:
    """Every local file of one game: saved record, draft, proposal and screenshots."""
    pattern = rf"g{game_no}(\.draft|\.proposal)?\.json(\.tmp)?"
    return [p for p in sorted(series_path(series_id).iterdir()) if p.is_file()
            and (re.fullmatch(pattern, p.name) or (parse_image_name(p.name) or (None,))[0] == game_no)]


def winner_without(series_id: str, game_no: int) -> str | None:
    """The series winner as it would stand with one game taken out."""
    s = load_series(series_id)
    wins: dict[str, int] = {}
    for n in range(1, s.bestOf + 1):
        g = load_game(series_id, n) if n != game_no else None
        if g and g.get("winner"):
            wins[g["winner"]] = wins.get(g["winner"], 0) + 1
            if wins[g["winner"]] >= wins_needed(s.bestOf):
                return g["winner"]
    return None


def delete_game(series_id: str, game_no: int) -> list[str]:
    removed = []
    for p in game_files(series_id, game_no):
        p.unlink()
        removed.append(p.name)
    refresh_series_winner(series_id)
    return removed


def saved_games(series_id: str) -> list[int]:
    d = series_path(series_id)
    return sorted(int(m.group(1)) for p in d.glob("g*.json") if (m := re.fullmatch(r"g(\d+)\.json", p.name)))


def delete_series(series_id: str) -> None:
    import shutil

    shutil.rmtree(series_path(series_id))


def restamp_games(series_id: str) -> list[dict[str, Any]]:
    """Copy the series fields that are baked into each saved game (tournament, stage, best of, date)
    from series.json again, after the series was edited. Returns the saved games."""
    series = load_series(series_id)
    out = []
    for n in saved_games(series_id):
        g = load_game(series_id, n)
        if g is None:
            continue
        fresh = {"tournament": series.tournament, "stage": series.stage, "bestOf": series.bestOf, "date": series.date}
        if any(g.get(k) != v for k, v in fresh.items()):
            g.update(fresh)
            _write_json(series_path(series_id) / f"g{n}.json", g)
        out.append(g)
    return out


# ---------------------------------------------------------------- screenshots
# A screenshot is named <teamA>_vs_<teamB>_<stage>_g<N>_<kind>.<ext>, for example
# FS_vs_BRU_leg1_g1_draft.png. Only the tail g<N>_<kind>.<ext> identifies it, so files from before
# the naming rule (g1_draft.png) and files named under an older match type are still found.
IMAGE_RE = re.compile(r"(?:.+_)?g(\d+)_(draft|post)(\.(?:png|jpe?g|webp))", re.IGNORECASE)


def parse_image_name(name: str) -> tuple[int, str, str] | None:
    """(game number, kind, extension) of a screenshot file name, or None for any other file."""
    m = IMAGE_RE.fullmatch(name or "")
    return (int(m.group(1)), m.group(2).lower(), m.group(3).lower()) if m else None


def image_name(series: Series, game_no: int, kind: str, ext: str) -> str:
    return f"{series.teamA}_vs_{series.teamB}_{series.stage}_g{game_no}_{kind}{ext.lower()}"


def images_of(series_id: str, game_no: int, kind: str) -> list[Path]:
    """Local screenshots of one slot, newest first."""
    d = series_path(series_id)
    if not d.is_dir():
        return []
    hits = [p for p in d.iterdir() if p.is_file() and (parse_image_name(p.name) or ())[:2] == (game_no, kind)]
    return sorted(hits, key=lambda p: p.stat().st_mtime, reverse=True)


def find_image(series_id: str, game_no: int, kind: str) -> Path | None:
    hits = images_of(series_id, game_no, kind)
    return hits[0] if hits else None


def rename_images(series_id: str) -> dict[str, str]:
    """Give every screenshot of the series its current name, on disk and inside the game files.
    Returns old name -> new name for everything that changed."""
    series = load_series(series_id)
    d = series_path(series_id)
    renamed: dict[str, str] = {}
    files = [p for p in d.iterdir() if p.is_file() and parse_image_name(p.name)]
    for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        new = image_name(series, *parse_image_name(p.name))
        if new != p.name and not (d / new).exists():
            p.rename(d / new)
            renamed[p.name] = new
    for p in sorted(d.glob("g*.json")):
        if not re.fullmatch(r"g\d+(\.draft|\.proposal)?\.json", p.name):
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        changed = False
        for holder in (data, data.get("input") or {}):
            images = holder.get("images")
            if not isinstance(images, dict):
                continue
            for kind in ("draft", "post"):
                parts = parse_image_name(images.get(kind) or "")
                if parts and image_name(series, *parts) != images[kind]:
                    renamed.setdefault(images[kind], image_name(series, *parts))
                    images[kind] = image_name(series, *parts)
                    changed = True
        if changed:
            _write_json(p, data)
    return renamed



def played_by(actions: list[dict[str, Any]], players: list[dict[str, Any]]) -> None:
    """Put the player and lane on every pick, taken from the post-game rows.

    The post-game screen is the only place that shows who played which hero. The name under a
    draft-bar pick is the seat that made the pick (kept as preSwapPlayer) and differs from the
    player whenever the team swapped heroes.
    """
    rows = {(p.get("team"), p.get("hero")): p for p in players if p.get("hero")}
    for a in actions:
        if a["action"] == "pick":
            row = rows.get((a["team"], a["hero"])) if a.get("hero") else None
            a["player"] = (row or {}).get("player") or None
            a["lane"] = (row or {}).get("lane") or None


def used_picks(series_id: str, game_no: int) -> dict[str, set[str]]:
    """Heroes each team already picked in earlier saved games of the series. Under Global Ban-Pick
    the team cannot pick them again, except in game 7 of a best of seven."""
    series = load_series(series_id)
    used: dict[str, set[str]] = {series.teamA: set(), series.teamB: set()}
    if series.bestOf == 7 and game_no == 7:
        return used
    for g in earlier_games(series_id, game_no):
        for a in g.get("draft", []):
            if a.get("action") == "pick" and a.get("hero"):
                used.setdefault(a["team"], set()).add(a["hero"])
    return used
