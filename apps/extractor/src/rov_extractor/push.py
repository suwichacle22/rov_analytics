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
    return {"ok": True, "result": result, "count": len(rows), "uploaded": uploaded}


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
