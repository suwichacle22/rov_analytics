from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import json

from . import recognise, refdata, review, source, store
from .models import GameInput, SeriesCreate
from . import push as cloud
from .push import convex_url, push_game
from .validate import validate_game

app = FastAPI(title="RoV draft extractor")
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _warm() -> None:
    import threading

    def run() -> None:
        # Hero art and learned crops are not in git. A machine that lacks them, such as a fresh
        # clone on a server, fetches them from Convex before the banks are loaded.
        if convex_url():
            r = cloud.pull_heroes()
            if not r.get("ok"):
                print(f"Heroes not fetched from Convex: {r.get('error')}", flush=True)
            elif r["heroes"] or r["art"] or r["crops"] or r["failed"]:
                print(f"Fetched from Convex: {r['heroes']} heroes, {r['art']} art files, {r['crops']} crops, {r['failed']} failed", flush=True)
        recognise.warm_up()

    threading.Thread(target=run, daemon=True).start()


@app.get("/")
def index() -> HTMLResponse:
    return _page("index.html")


@app.get("/api/ref")
def ref() -> dict[str, Any]:
    return refdata.bundle()


# ---------------------------------------------------------------- teams page
@app.get("/teams")
def teams_page() -> HTMLResponse:
    return _page("teams.html")


@app.get("/api/teams")
def teams_get() -> dict[str, Any]:
    roster = refdata.roster()
    return {"teams": [{**t, "players": roster.get(t["id"], [])} for t in refdata.teams()], "lanes": refdata.LANES}


class RosterSave(BaseModel):
    players: dict[str, list[dict[str, Any]]]


@app.put("/api/teams")
def teams_save(body: RosterSave) -> dict[str, Any]:
    known = refdata.team_ids()
    rosters: dict[str, list[dict[str, Any]]] = {}
    for team, items in body.players.items():
        if team not in known:
            raise HTTPException(400, f"Unknown team {team}")
        seen: set[str] = set()
        rosters[team] = []
        for p in items:
            name, lane = str(p.get("name") or "").strip(), p.get("lane") or None
            if not name:
                continue
            if name.lower() in seen:
                raise HTTPException(400, f"{team}: {name} is listed twice")
            if lane is not None and lane not in refdata.LANES:
                raise HTTPException(400, f"{team}: {lane} is not a position")
            seen.add(name.lower())
            rosters[team].append({"name": name, "lane": lane})
    refdata.save_roster(rosters)
    return teams_get()


# ---------------------------------------------------------------- heroes page
@app.get("/heroes")
def heroes_page() -> HTMLResponse:
    return _page("heroes.html")


def _page(name: str) -> HTMLResponse:
    """Serve a static page with every /static/ script and stylesheet link stamped by its file
    modification time, so a browser can never keep running an outdated copy after an update."""
    import re

    html = (STATIC / name).read_text(encoding="utf-8")

    def stamp(m: re.Match) -> str:
        path = STATIC / m.group(1)
        v = int(path.stat().st_mtime) if path.exists() else 0
        return f'/static/{m.group(1)}?v={v}'

    html = re.sub(r'/static/([\w./-]+\.(?:js|css))', stamp, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


def _crops_index() -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {"ban": {}, "pick": {}}
    for kind in out:
        d = recognise.crops_dir() / kind
        if d.exists():
            for hero_dir in sorted(d.iterdir()):
                files = sorted(p.name for p in hero_dir.glob("*.png"))
                if files:
                    out[kind][hero_dir.name] = files
    return out


@app.get("/api/heroes")
def heroes_get() -> dict[str, Any]:
    return {"heroes": refdata.heroes(), "map": refdata.art_map(), "files": refdata.art_files(), "crops": _crops_index()}


class HeroesSave(BaseModel):
    heroes: list[dict[str, Any]]
    map: dict[str, dict[str, Any]]


@app.put("/api/heroes")
def heroes_save(body: HeroesSave) -> dict[str, Any]:
    ids = [h.get("id") for h in body.heroes]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise HTTPException(400, "Every hero needs a unique id")
    for h in body.heroes:
        if not h.get("name"):
            raise HTTPException(400, f"Hero {h['id']} needs a name")
    refdata.save_heroes(body.heroes)
    current = refdata.art_map()
    merged = {}
    for i in ids:
        entry = dict(body.map.get(i, {"ban": None, "pick": None, "checked": False}))
        for kind in ("ban", "pick"):
            cached = (current.get(i) or {}).get(f"{kind}Storage")
            if cached and f"{kind}Storage" not in entry:
                entry[f"{kind}Storage"] = cached
        merged[i] = entry
    refdata.save_art_map(merged)
    recognise.reset_banks()
    out = heroes_get()
    if convex_url():
        out["cloud"] = cloud.push_heroes()
    return out


@app.get("/api/art/{kind}/{name}")
def art_file(kind: str, name: str) -> FileResponse:
    if kind not in refdata.ART_FOLDERS:
        raise HTTPException(404, "kind")
    p = recognise.art_dir() / refdata.ART_FOLDERS[kind] / Path(name).name
    if not p.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(p)


@app.post("/api/heroes/{hero}/art/{kind}")
def art_upload(hero: str, kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Set this hero's own ban icon or pick art from any image. The image is brought to the size of
    the other art files, paired with the hero at once and sent to Convex. A file the hero had before
    stays on disk under its old name."""
    if kind not in refdata.ART_FOLDERS:
        raise HTTPException(400, "kind must be ban or pick")
    name = next((h["name"] for h in refdata.heroes() if h["id"] == hero), None)
    if name is None:
        raise HTTPException(404, "Unknown hero. Save the hero list first.")
    folder = recognise.art_dir() / refdata.ART_FOLDERS[kind]
    stem = re.sub(r"[^A-Za-z0-9]", "", name) or hero
    dest, n = folder / f"{stem}.png", 1
    while dest.exists():
        n += 1
        dest = folder / f"{stem}-{n}.png"
    if not recognise.save_art_file(file.file.read(), dest, refdata.ART_SIZES[kind]):
        raise HTTPException(400, "Could not read this image. Use a PNG, JPG or WebP file.")
    mapping = refdata.art_map()
    mapping[hero][kind] = dest.name
    refdata.save_art_map(mapping)
    recognise.reset_banks()
    out: dict[str, Any] = {"file": dest.name, "files": refdata.art_files()}
    if convex_url():
        out["cloud"] = cloud.push_heroes()
    out["entry"] = refdata.art_map()[hero]
    return out


@app.get("/api/crops/{kind}/{hero}/{name}")
def crop_file(kind: str, hero: str, name: str) -> FileResponse:
    p = recognise.crops_dir() / kind / Path(hero).name / Path(name).name
    if not p.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(p)


@app.post("/api/heroes/{hero}/crops/{kind}")
async def crop_upload(hero: str, kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Add a broadcast crop of this hero by hand (a ban icon or a pick splash)."""
    if kind not in ("ban", "pick"):
        raise HTTPException(400, "kind must be ban or pick")
    if hero not in refdata.hero_ids():
        raise HTTPException(404, "unknown hero")
    d = recognise.crops_dir() / kind / hero
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("manual_*.png"))) + 1
    dest = d / f"manual_{n:03d}.png"
    if not recognise.save_crop_file(file.file.read(), dest):
        raise HTTPException(400, "not an image")
    recognise.reset_banks()
    if convex_url():
        cloud.push_crops()
    return {"ok": True, "file": dest.name}


@app.delete("/api/heroes/{hero}/crops/{kind}/{name}")
def crop_delete(hero: str, kind: str, name: str) -> dict[str, Any]:
    p = recognise.crops_dir() / kind / Path(hero).name / Path(name).name
    if p.exists():
        p.unlink()
        recognise.reset_banks()
    if convex_url():
        cloud.remove_crops([{"kind": kind, "heroId": Path(hero).name, "name": Path(name).name}])
    return {"ok": True}


class PlayersAdd(BaseModel):
    team: str
    names: list[str]


@app.post("/api/ref/players")
def ref_players_add(body: PlayersAdd) -> dict[str, Any]:
    return {"players": refdata.add_players(body.team, body.names)}


@app.get("/api/series")
def series_list() -> list[dict[str, Any]]:
    return [{**s, "review": review.counts(s)} for s in store.list_series()]


@app.post("/api/series")
def series_create(body: SeriesCreate) -> dict[str, Any]:
    if body.teamA == body.teamB:
        raise HTTPException(400, "Team A and Team B must differ")
    if body.homeTeam not in (body.teamA, body.teamB):
        raise HTTPException(400, "Home team must be one of the two teams")
    return store.create_series(body).model_dump()


@app.get("/api/video-date")
def video_date(url: str) -> dict[str, Any]:
    """Day of the video behind a source link, for the New match dialog."""
    return {"date": source.video_date(url)}


@app.get("/api/series/{series_id}")
def series_get(series_id: str) -> dict[str, Any]:
    try:
        s = store.load_series(series_id)
    except FileNotFoundError:
        raise HTTPException(404, "Match not found")
    entry = next((x for x in store.list_series() if x["seriesId"] == series_id), {})
    return {**s.model_dump(), "games": entry.get("games", []), "drafts": entry.get("drafts", []), "score": store.series_score(series_id),
            "review": review.counts(entry) if entry else {}}


@app.delete("/api/series/{series_id}")
def series_delete(series_id: str) -> dict[str, Any]:
    """Delete a series everywhere: Convex first, then the local folder and the crops learned from it."""
    if not store.series_exists(series_id):
        raise HTTPException(404, "Match not found")
    out: dict[str, Any] = {"ok": True, "seriesId": series_id}
    if convex_url():
        r = cloud.delete_series(series_id)
        if not r.get("ok"):
            raise HTTPException(502, f"Convex did not answer, nothing was deleted: {r.get('error')}")
        out["cloud"] = r.get("result")
    games = store.saved_games(series_id)
    store.delete_series(series_id)
    out["forgotCrops"] = sum(_forget_crops(f"{series_id}_g{n}") for n in games)
    return out


def _forget_crops(game_id: str) -> int:
    """Drop the crops learned from a game, here and in Convex."""
    n = recognise.forget_game(game_id)
    if n and convex_url():
        cloud.forget_crops(game_id)
    return n


@app.delete("/api/series/{series_id}/games/{game_no}")
def game_delete(series_id: str, game_no: int) -> dict[str, Any]:
    """Delete one game everywhere: Convex first, then local files and the crops learned from it."""
    if not store.series_exists(series_id):
        raise HTTPException(404, "Match not found")
    out: dict[str, Any] = {"ok": True, "gameId": f"{series_id}_g{game_no}"}
    if convex_url():
        r = cloud.delete_game(series_id, game_no, store.winner_without(series_id, game_no))
        if not r.get("ok"):
            raise HTTPException(502, f"Convex did not answer, nothing was deleted: {r.get('error')}")
        out["cloud"] = r.get("result")
    out["removed"] = store.delete_game(series_id, game_no)
    out["forgotCrops"] = _forget_crops(out["gameId"])
    return out


@app.patch("/api/series/{series_id}")
def series_patch(series_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Edit series fields such as the match type. Saved games carry a copy of some of them, so
    those copies are refreshed and, with Convex configured, pushed again."""
    from pydantic import ValidationError

    if not store.series_exists(series_id):
        raise HTTPException(404, "Match not found")
    try:
        series = store.update_series(series_id, body)
    except ValidationError as e:
        raise HTTPException(400, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
    out = series.model_dump()
    renamed = store.rename_images(series_id)
    games = store.restamp_games(series_id)
    if convex_url():
        failed = [r.get("error") for r in (push_game(series.model_dump(), g) for g in games) if not r.get("ok")]
        out["cloud"] = {"pushed": len(games) - len(failed)}
        r = cloud.rename_images(series_id, lambda n, kind, ext: store.image_name(series, n, kind, ext))
        out["cloud"]["renamedImages"] = r.get("renamed", 0)
        if not r.get("ok"):
            failed.append(r.get("error"))
        if failed:
            out["cloudError"] = failed[0]
    out["renamed"] = renamed
    return out


@app.get("/api/series/{series_id}/games/{game_no}")
def game_get(series_id: str, game_no: int) -> dict[str, Any]:
    series = store.load_series(series_id)
    data = store.load_input(series_id, game_no)
    saved = store.load_game(series_id, game_no)
    # The files on disk decide the names, so an image dropped into the folder by hand is picked up
    # and a name remembered from before a rename cannot point at nothing.
    found = {}
    for kind in ("draft", "post"):
        p = store.find_image(series_id, game_no, kind)
        if p is not None:
            found[kind] = p.name
        elif data and (data.get("images") or {}).get(f"{kind}Storage"):
            # Local copy was purged; the file lives in Convex.
            found[kind] = data["images"].get(kind) or store.image_name(series, game_no, kind, ".png")
    if found:
        data = data or {"gameNo": game_no, "blueTeam": series.teamA}
        data["images"] = {**{k: v for k, v in (data.get("images") or {}).items() if v}, **found}
    return {"input": data, "saved": saved is not None, "savedAt": (saved or {}).get("savedAt"), "series": series.model_dump(),
            "review": review.review_game(series_id, game_no, data, saved is not None)}


@app.post("/api/series/{series_id}/games/{game_no}/validate")
def game_validate(series_id: str, game_no: int, body: GameInput) -> dict[str, Any]:
    series = store.load_series(series_id)
    body.gameNo = game_no
    issues = validate_game(series, body, store.earlier_games(series_id, game_no))
    return {"issues": [i.model_dump() for i in issues], "valid": not any(i.level == "error" for i in issues)}


@app.put("/api/series/{series_id}/games/{game_no}/draft")
def game_autosave(series_id: str, game_no: int, body: GameInput) -> dict[str, Any]:
    body.gameNo = game_no
    p = store.save_draft(series_id, body)
    # An edit makes the game a draft again, so what is left to check is counted from the form.
    return {"ok": True, "path": str(p), "review": review.review_game(series_id, game_no, body.model_dump(), False)}


@app.put("/api/series/{series_id}/games/{game_no}")
def game_save(series_id: str, game_no: int, body: GameInput) -> JSONResponse:
    series = store.load_series(series_id)
    body.gameNo = game_no
    issues = validate_game(series, body, store.earlier_games(series_id, game_no))
    if any(i.level == "error" for i in issues):
        return JSONResponse(status_code=422, content={"ok": False, "issues": [i.model_dump() for i in issues]})
    _remember_players(series, body)
    p, record = store.save_game(series_id, body)
    learned = 0
    if body.images.get("draft"):
        try:
            draft_image = store.find_image(series_id, game_no, "draft") or store.series_path(series_id) / body.images["draft"]
            learned = recognise.remember_game(draft_image, refdata.layout(series.layout), record)
        except Exception:  # noqa: BLE001
            learned = 0
        if learned and convex_url():
            cloud.push_crops()
    return JSONResponse({"ok": True, "path": str(p), "gameId": record["gameId"], "issues": [i.model_dump() for i in issues], "learnedCrops": learned})


RUNS: dict[tuple[str, int], recognise.Progress] = {}


@app.get("/api/series/{series_id}/games/{game_no}/recognise/progress")
def game_recognise_progress(series_id: str, game_no: int) -> dict[str, Any]:
    run = RUNS.get((series_id, game_no))
    if run is None:
        return {"running": False}
    return {"running": True, "percent": int(run.fraction() * 100), "label": run.label}


@app.post("/api/series/{series_id}/games/{game_no}/recognise")
def game_recognise(series_id: str, game_no: int, body: GameInput) -> dict[str, Any]:
    """Propose values from the attached images. Never writes game data."""
    series = store.load_series(series_id)
    blue = body.blueTeam
    red = series.teamB if blue == series.teamA else series.teamA
    images = dict(body.images)
    for kind in ("draft", "post"):
        p = store.find_image(series_id, game_no, kind)
        if p is None and (images.get(kind) or images.get(f"{kind}Storage")) and convex_url():
            p = cloud.fetch_image(series_id, game_no, kind, store.series_path(series_id))
        if p is not None:
            images[kind] = p.name
    folder = store.series_path(series_id)
    match = _date_from_source(series)
    series = store.load_series(series_id)
    run = RUNS[(series_id, game_no)] = recognise.Progress(*(bool(images.get(k)) and (folder / images[k]).exists() for k in ("draft", "post")))
    try:
        result = recognise.recognise_game(folder, images, refdata.layout(series.layout), (blue, red), refdata.players(),
                                          used=store.used_picks(series_id, game_no), progress=run)
    finally:
        if RUNS.get((series_id, game_no)) is run:
            del RUNS[(series_id, game_no)]
    result["images"] = images
    result["match"] = match
    (store.series_path(series_id) / f"g{game_no}.proposal.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


@app.post("/api/series/{series_id}/games/{game_no}/images/{kind}")
async def game_image(series_id: str, game_no: int, kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if kind not in ("draft", "post"):
        raise HTTPException(400, "kind must be draft or post")
    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Only png, jpg or webp images")
    if not store.series_exists(series_id):
        raise HTTPException(404, "Match not found")
    name = store.image_name(store.load_series(series_id), game_no, kind, ext)
    dest = store.series_path(series_id) / name
    for old in store.images_of(series_id, game_no, kind):
        if old.name != name:
            old.unlink()  # replaced: an older name or another file type for the same slot
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    result: dict[str, Any] = {"ok": True, "file": name}
    if convex_url():
        r = cloud.upload_image(series_id, game_no, kind, dest)
        result["cloud"] = r.get("storageId") if r.get("ok") else None
        if not r.get("ok"):
            result["cloudError"] = r.get("error")
    return result


@app.get("/api/series/{series_id}/files/{name}")
def series_file(series_id: str, name: str) -> FileResponse:
    p = store.series_path(series_id) / Path(name).name
    if not p.exists():
        parts = store.parse_image_name(Path(name).name)
        p = (parts and store.find_image(series_id, parts[0], parts[1])) or _restore_image(series_id, Path(name).name) or p
    if not p.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(p)


def _restore_image(series_id: str, name: str) -> Path | None:
    """Re-download a screenshot from Convex storage into the series folder."""
    parts = store.parse_image_name(name)
    if not parts or not convex_url():
        return None
    return cloud.fetch_image(series_id, parts[0], parts[1], store.series_path(series_id))


@app.post("/api/series/{series_id}/games/{game_no}/push")
def game_push(series_id: str, game_no: int) -> dict[str, Any]:
    game = store.load_game(series_id, game_no)
    if game is None:
        raise HTTPException(404, "Save the game first")
    return push_game(store.load_series(series_id).model_dump(), game)


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {"convexUrl": convex_url() or None, "seriesDir": str(store.series_dir()), "cloudImages": bool(convex_url())}


def _date_from_source(series) -> dict[str, Any]:
    """The screenshots show no date, so the day of the match comes from its source link. A date
    typed by hand stays."""
    out: dict[str, Any] = {"date": series.date, "dateChanged": False, "dateNote": None}
    if series.dateManual:
        return out
    if not series.vodUrl:
        out["dateNote"] = "no source link, so the date was not checked"
        return out
    day = source.video_date(series.vodUrl)
    if day is None:
        out["dateNote"] = "the date could not be read from the source link"
    elif day != series.date:
        series_patch(series.seriesId, {"date": day})
        out.update(date=day, dateChanged=True)
    return out


def _remember_players(series, game: GameInput) -> None:
    for team in (series.teamA, series.teamB):
        names = [p.player for p in game.players if p.team == team and p.player]
        if names:
            refdata.add_players(team, names)


@app.middleware("http")
async def _no_stale_static(request, call_next):
    """Browsers must revalidate the page scripts after every update; ETags still allow a cheap 304."""
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path in ("/", "/heroes", "/teams"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")
