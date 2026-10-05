"""Talk to Convex: push confirmed games, upload and fetch screenshots.

Needs CONVEX_URL (cloud) or CONVEX_SELF_HOSTED_URL plus CONVEX_SELF_HOSTED_ADMIN_KEY (self-hosted)
in the environment or in a .env.local file at the repo root. The functions live in
`packages/backend/convex/` and are deployed with `bun run backend:deploy` from the repo root.
"""
from __future__ import annotations

import mimetypes
import os
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .paths import repo_root


def _load_env() -> None:
    load_dotenv(repo_root() / ".env.local")
    load_dotenv(repo_root() / ".env")


def convex_url() -> str | None:
    _load_env()
    return os.environ.get("CONVEX_URL") or os.environ.get("CONVEX_SELF_HOSTED_URL")


def convex_admin_key() -> str | None:
    _load_env()
    return os.environ.get("CONVEX_SELF_HOSTED_ADMIN_KEY")


def client():
    """A ConvexClient for the configured deployment, or None when nothing is configured."""
    url = convex_url()
    if not url:
        return None
    from convex import ConvexClient

    c = ConvexClient(url)
    key = convex_admin_key()
    if key:
        c.set_admin_auth(key)
    return c


def push_game(series: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    c = client()
    if c is None:
        return {"ok": False, "error": "CONVEX_URL or CONVEX_SELF_HOSTED_URL is not set. Put it in .env.local at the repo root."}
    payload = {"series": series, "game": _strip_input(game)}
    try:
        result = c.mutation("games:upsert", payload)
        return {"ok": True, "result": result}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _upload_bytes(c, path: Path) -> str:
    """Send a file to Convex storage and return its storage id."""
    import json

    data = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    upload_url = c.mutation("files:generateUploadUrl", {})
    req = urllib.request.Request(upload_url, data=data, method="POST", headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["storageId"]


def push_heroes(upload_art: bool = True) -> dict[str, Any]:
    """Mirror heroes.json into the Convex heroes table. With upload_art, each hero's ban icon and pick
    art go to Convex storage once; the storage id and file name are cached in art-map.json so a later
    Save only re-uploads a file you changed."""
    from . import refdata
    from .recognise import art_dir, crops_dir

    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    if upload_art:
        # On a machine that lacks files Convex holds, fetch them first. After that, a file that
        # is missing here is one the user removed.
        pull_heroes(add_heroes=False)
    art = refdata.art_map()
    rows = []
    uploaded = 0
    changed = False
    for h in refdata.heroes():
        entry = art.setdefault(h["id"], {"ban": None, "pick": None, "checked": False})
        row: dict[str, Any] = {"heroId": h["id"], "name": h["name"], "checked": bool(entry.get("checked")),
                               "hasArt": bool(entry.get("ban") and entry.get("pick"))}
        if h.get("forms"):
            row["forms"] = list(h["forms"])
        for kind, key in (("ban", "banArtId"), ("pick", "pickArtId")):
            name = entry.get(kind)
            path = art_dir() / refdata.ART_FOLDERS[kind] / name if name else None
            if path is None:
                # A hero without art of its own shows the first crop learned from a broadcast.
                crops = sorted((crops_dir() / kind / h["id"]).glob("*.png"))
                if crops:
                    name, path = f"crop/{crops[0].name}", crops[0]
            cached = entry.get(f"{kind}Storage") or {}
            if path and path.exists():
                stamp = f"{name}:{path.stat().st_size}"
                if upload_art and cached.get("file") != stamp:
                    try:
                        cached = {"id": _upload_bytes(c, path), "file": stamp}
                        entry[f"{kind}Storage"] = cached
                        uploaded += 1
                        changed = True
                    except Exception as e:  # noqa: BLE001
                        return {"ok": False, "error": f"upload of {name} failed: {e}"}
                if cached.get("id"):
                    row[key] = cached["id"]
                    row[f"{kind}ArtName"] = name
            elif name and cached.get("id") and str(cached.get("file", "")).rsplit(":", 1)[0] == name:
                # The paired file is not on this machine and could not be fetched. What Convex
                # holds stays: a missing file must never delete the stored one.
                row[key] = cached["id"]
                row[f"{kind}ArtName"] = name
            elif cached:
                entry.pop(f"{kind}Storage", None)
                changed = True
        rows.append(row)
    try:
        result = c.mutation("heroes:sync", {"heroes": rows})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    if changed:
        refdata.save_art_map(art)
    out = {"ok": True, "result": result, "count": len(rows), "uploaded": uploaded}
    if upload_art:
        out["crops"] = push_crops(c)
    return out


def _local_crops() -> list[tuple[str, str, Path]]:
    """(kind, hero id, file) of every learned crop that belongs to a hero in the list."""
    from . import refdata
    from .recognise import crops_dir

    known = refdata.hero_ids()
    out = []
    for kind in ("ban", "pick"):
        d = crops_dir() / kind
        if d.exists():
            for hero_dir in sorted(d.iterdir()):
                if hero_dir.name in known:
                    out += [(kind, hero_dir.name, p) for p in sorted(hero_dir.glob("*.png"))]
    return out


def push_crops(c=None) -> dict[str, Any]:
    """Send the crops in data/ref/crops that Convex lacks or holds in another size, so another
    machine can fetch them. Nothing is removed there; remove_crops does that."""
    c = c or client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        stored = {(r["kind"], r["heroId"], r["name"]): r for r in (c.query("heroes:mirror", {}) or {}).get("crops", [])}
        rows = []
        for kind, hero, path in _local_crops():
            size = path.stat().st_size
            cur = stored.get((kind, hero, path.name))
            if not cur or int(cur["size"]) != size:
                rows.append({"heroId": hero, "kind": kind, "name": path.name, "storageId": _upload_bytes(c, path), "size": size})
        if rows:
            c.mutation("heroes:addCrops", {"crops": rows})
        return {"ok": True, "uploaded": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def remove_crops(crops: list[dict[str, str]]) -> dict[str, Any]:
    """Remove crops from Convex that were deleted here. Each is {kind, heroId, name}."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        return {"ok": True, "result": c.mutation("heroes:removeCrops", {"crops": crops}) if crops else None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def forget_crops(game_id: str) -> dict[str, Any]:
    """Remove from Convex the crops learned from one game, after the game was deleted here."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        gone = [{"kind": r["kind"], "heroId": r["heroId"], "name": r["name"]}
                for r in (c.query("heroes:mirror", {}) or {}).get("crops", []) if r["name"].startswith(f"{game_id}_")]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return remove_crops(gone)


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/version", timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


def _download(url: str, dest: Path) -> bool:
    """Fetch a stored file. It appears under its name only once it is complete."""
    part = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as resp:
            part.write_bytes(resp.read())
        part.replace(dest)
        return True
    except Exception:  # noqa: BLE001
        part.unlink(missing_ok=True)
        return False


def pull_heroes(add_heroes: bool = True) -> dict[str, Any]:
    """Fetch from Convex what this machine lacks: art files, learned crops and, with add_heroes,
    heroes missing from heroes.json. Nothing on disk is replaced and the pairing of art to heroes
    made here is kept, so it is safe to run on every start. This is what fills data/ref/art and
    data/ref/crops on a fresh clone, which git does not carry."""
    from concurrent.futures import ThreadPoolExecutor

    from . import refdata
    from .recognise import art_dir, crops_dir, reset_banks

    url = convex_url()
    if not url:
        return {"ok": False, "error": "Convex is not configured"}
    if not _reachable(url):
        return {"ok": False, "error": f"Convex does not answer at {url}"}
    try:
        data = client().query("heroes:mirror", {}) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

    local = refdata.heroes()
    have = {h["id"] for h in local}
    added = [{"id": r["heroId"], "name": r["name"], **({"forms": list(r["forms"])} if r.get("forms") else {})}
             for r in data.get("heroes", []) if r["heroId"] not in have] if add_heroes else []
    if added:
        refdata.save_heroes(local + added)
    new = {h["id"] for h in added}

    art = refdata.art_map()
    wanted: list[tuple[str, Path]] = []
    for r in data.get("heroes", []):
        entry = art.get(r["heroId"])
        if entry is None:
            continue
        for kind in ("ban", "pick"):
            stored = r.get(f"{kind}ArtName")  # None on a row pushed before names were kept
            link = r.get(f"{kind}ArtUrl")
            if not link or (stored or "").startswith("crop/"):
                continue
            if r["heroId"] in new and stored:
                entry[kind] = Path(stored).name
                entry["checked"] = bool(r.get("checked"))
            name = entry.get(kind)
            # Only the file this machine pairs with the hero is fetched, and only when it is the
            # one Convex holds.
            same = Path(stored).name == name if stored else (entry.get(f"{kind}Storage") or {}).get("id") == r.get(f"{kind}ArtId")
            if name and same:
                dest = art_dir() / refdata.ART_FOLDERS[kind] / Path(name).name
                if not dest.exists():
                    wanted.append((link, dest))
    n_art = len(wanted)
    for r in data.get("crops", []):
        if r.get("url") and r["kind"] in ("ban", "pick"):
            dest = crops_dir() / r["kind"] / Path(r["heroId"]).name / Path(r["name"]).name
            if not dest.exists():
                wanted.append((r["url"], dest))
    with ThreadPoolExecutor(max_workers=8) as pool:
        done = list(pool.map(lambda w: _download(*w), wanted))
    if added:
        refdata.save_art_map(art)
    if wanted or added:
        reset_banks()
    return {"ok": True, "heroes": len(added), "art": sum(done[:n_art]), "crops": sum(done[n_art:]), "failed": len(done) - sum(done)}


def push_teams() -> dict[str, Any]:
    """Mirror the team names from teams.json into the Convex teams table."""
    from . import refdata

    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        rows = [{"teamId": t["id"], "name": t["name"]} for t in refdata.teams()]
        return {"ok": True, "result": c.mutation("teams:sync", {"teams": rows})}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def upload_image(series_id: str, game_no: int, kind: str, path: Path) -> dict[str, Any]:
    """Store a screenshot in Convex file storage and link it to the game. Returns the storage id."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        storage_id = _upload_bytes(c, path)
        c.mutation("files:saveImage", {
            "seriesId": series_id, "gameNo": game_no, "kind": kind, "name": path.name,
            "storageId": storage_id, "size": path.stat().st_size,
            "contentType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        })
        return {"ok": True, "storageId": storage_id}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def image_info(series_id: str, game_no: int, kind: str) -> dict[str, Any] | None:
    """{name, storageId, url} for a stored screenshot, or None."""
    c = client()
    if c is None:
        return None
    try:
        return c.query("files:imageUrl", {"seriesId": series_id, "gameNo": game_no, "kind": kind})
    except Exception:  # noqa: BLE001
        return None


def fetch_image(series_id: str, game_no: int, kind: str, dest_dir: Path) -> Path | None:
    """Download a stored screenshot into the series folder (a local cache). Returns the path."""
    info = image_info(series_id, game_no, kind)
    if not info or not info.get("url"):
        return None
    dest = dest_dir / info["name"]
    try:
        with urllib.request.urlopen(info["url"], timeout=120) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.read())
        return dest
    except Exception:  # noqa: BLE001
        return None


def list_images(series_id: str) -> list[dict[str, Any]]:
    c = client()
    if c is None:
        return []
    try:
        return c.query("files:listImages", {"seriesId": series_id}) or []
    except Exception:  # noqa: BLE001
        return []


def _strip_input(game: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in game.items() if k != "input"}


def delete_game(series_id: str, game_no: int, winner: str | None) -> dict[str, Any]:
    """Remove one game from Convex: the game, its draft actions and its stored screenshots."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        return {"ok": True, "result": c.mutation("games:removeGame", {"seriesId": series_id, "gameNo": game_no, "winner": winner})}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def delete_series(series_id: str) -> dict[str, Any]:
    """Remove a whole series from Convex, including every game and stored screenshot."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        return {"ok": True, "result": c.mutation("games:removeSeries", {"seriesId": series_id})}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def rename_images(series_id: str, name_for) -> dict[str, Any]:
    """Rename the stored screenshots of a series in Convex. `name_for(game_no, kind, ext)` gives the
    wanted name. The stored file itself is untouched; only its record changes."""
    c = client()
    if c is None:
        return {"ok": False, "error": "Convex is not configured"}
    try:
        n = 0
        for i in c.query("files:listImages", {"seriesId": series_id}) or []:
            new = name_for(int(i["gameNo"]), i["kind"], Path(i["name"]).suffix or ".png")
            if new == i["name"]:
                continue
            args = {"seriesId": series_id, "gameNo": int(i["gameNo"]), "kind": i["kind"], "name": new, "storageId": i["storageId"],
                    "contentType": mimetypes.guess_type(new)[0] or "application/octet-stream"}
            if i.get("size") is not None:
                args["size"] = i["size"]
            c.mutation("files:saveImage", args)
            n += 1
        return {"ok": True, "renamed": n}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
