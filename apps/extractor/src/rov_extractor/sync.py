"""Keep the working files of the extractor in step with Convex.

The extractor reads and writes JSON files: per match series.json, and per game the form
(g1.draft.json), the Recognise reading (g1.proposal.json) and the saved game (g1.json); plus the
team rosters in data/ref/players.json. Convex holds a copy of each of them, so every machine that
runs the extractor sees the same matches and none of these files has to be carried by hand.

One pass compares three things for every file: what is on disk, what Convex holds, and what both
held after the last pass (data/.sync.json). A file changed here goes up, a file changed there comes
down, and when both changed the newer one wins and the local loser is kept as <name>.bak. Deleting
a game file here deletes it there. A whole match is only ever removed by the Delete button, which
removes it in Convex itself; a match folder that is simply missing on this machine is fetched.

Screenshots are not handled here: they are stored when attached and fetched when needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .paths import data_dir, ref_dir, series_dir
from .push import convex_url

REF = "_ref"                       # folder name in Convex for the files of data/ref
REF_FILES = ("players.json",)
MATCH_FILE = re.compile(r"series\.json|g\d+(\.draft|\.proposal)?\.json")
BATCH = 600_000                    # characters of file text per request

_pass = threading.Lock()
_wake = threading.Event()
_state: dict[str, Any] = {"at": 0.0, "ok": None, "error": None, "last": None}


def _call(kind: str, path: str, args: dict[str, Any], timeout: float = 30) -> Any:
    """A Convex function over plain HTTP, so an unreachable Convex fails after `timeout`."""
    body = json.dumps({"path": path, "args": args, "format": "json"}).encode()
    req = urllib.request.Request(convex_url().rstrip("/") + f"/api/{kind}", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read())
    if out.get("status") != "success":
        raise RuntimeError(out.get("errorMessage") or "Convex refused the request")
    return out.get("value")


def _path(folder: str, name: str) -> Path:
    return (ref_dir() if folder == REF else series_dir() / folder) / name


def _read(path: Path) -> tuple[str, str] | None:
    """(hash, text) of a JSON file. The hash ignores layout and key order, so the same content
    written on Windows and on Linux counts as the same. None while the file cannot be parsed."""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    canon = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(canon.encode()).hexdigest(), json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _local() -> tuple[dict[tuple[str, str], str], set[tuple[str, str]]]:
    """Hash of every file on disk that is kept in step, and the files that exist but cannot be
    read right now (being written): those are left alone in this pass."""
    found: dict[tuple[str, str], str] = {}
    unreadable: set[tuple[str, str]] = set()
    keys = [(REF, n) for n in REF_FILES if (ref_dir() / n).is_file()]
    for d in sorted(series_dir().iterdir()):
        if d.is_dir():
            keys += [(d.name, p.name) for p in sorted(d.iterdir()) if p.is_file() and MATCH_FILE.fullmatch(p.name)]
    for key in keys:
        r = _read(_path(*key))
        if r is None:
            unreadable.add(key)
        else:
            found[key] = r[0]
    return found, unreadable


def _base_path() -> Path:
    return data_dir() / ".sync.json"


def _load_base() -> dict[tuple[str, str], str]:
    try:
        raw = json.loads(_base_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if raw.get("url") != convex_url():
        return {}  # another Convex than last time: nothing is known about it
    return {tuple(k.split("/", 1)): v for k, v in (raw.get("files") or {}).items()}


def _save_base(base: dict[tuple[str, str], str]) -> None:
    tmp = _base_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"url": convex_url(), "files": {"/".join(k): v for k, v in sorted(base.items())}}, indent=1), encoding="utf-8")
    tmp.replace(_base_path())


def _write(path: Path, content: str, stamp_ms: float, keep: bool) -> None:
    """Put a fetched file on disk in the layout the extractor writes itself."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep and path.exists():
        path.replace(path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(json.loads(content), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    os.utime(path, (stamp_ms / 1000, stamp_ms / 1000))


def run() -> dict[str, Any]:
    """One pass in both directions. Returns what moved, or {"ok": False, "error": ...}."""
    if not convex_url():
        return {"ok": False, "error": "Convex is not configured"}
    with _pass:
        try:
            out = _run()
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": str(e)}
        _state.update(at=time.time(), ok=out["ok"], error=out.get("error"), last=out if out["ok"] else _state["last"])
        return out


def _run() -> dict[str, Any]:
    remote = {(r["folder"], r["name"]): r for r in _call("query", "extractor:index", {}, timeout=15)}
    local, unreadable = _local()
    base = _load_base()
    if not remote:
        base = {}  # an empty Convex has lost nothing: everything here goes up

    push: list[tuple[str, str]] = []
    pull: dict[tuple[str, str], bool] = {}  # key -> keep the local file as .bak
    drop_remote: list[tuple[str, str]] = []
    drop_local: list[tuple[str, str]] = []
    for key in sorted(set(remote) | set(local) | set(base)):
        if key in unreadable:
            continue
        folder, name = key
        here, there, was = local.get(key), (remote.get(key) or {}).get("hash"), base.get(key)
        if here == there:
            if here is None:
                base.pop(key, None)
            else:
                base[key] = here
            continue
        # A match folder that is not on this machine was not deleted by the user (Delete removes
        # the match in Convex first), so its files are fetched, never removed.
        whole = folder == REF or name == "series.json" or not (series_dir() / folder / "series.json").is_file()
        if was is None:
            if here is None:
                pull[key] = False
            elif there is None:
                push.append(key)
            else:
                pull[key] = True  # never compared before and different: Convex is the store
        elif there == was:  # changed here only
            if here is not None:
                push.append(key)
            elif whole:
                pull[key] = False
            else:
                drop_remote.append(key)
        elif here == was:  # changed there only
            if there is not None:
                pull[key] = False
            elif folder == REF:
                push.append(key)
            else:
                drop_local.append(key)
        elif here is None:
            pull[key] = False
        elif there is None:
            push.append(key)
        elif _path(*key).stat().st_mtime * 1000 >= remote[key]["updatedAt"]:
            push.append(key)
        else:
            pull[key] = True

    # Down first, so a file that is fetched is never sent back in the same pass.
    by_folder: dict[str, list[str]] = {}
    for folder, name in pull:
        by_folder.setdefault(folder, []).append(name)
    pulled = kept = 0
    for folder, names in by_folder.items():
        for row in _call("query", "extractor:bodies", {"folder": folder, "names": names}):
            key = (folder, row["name"])
            path = _path(*key)
            now = _read(path) if path.exists() else None
            if (now[0] if now else None) != local.get(key):
                continue  # written here while this pass ran: the next pass decides
            keep = pull[key] and path.exists()
            _write(path, row["content"], remote[key]["updatedAt"], keep)
            base[key] = remote[key]["hash"]
            pulled += 1
            kept += keep
    for key in drop_local:
        path = _path(*key)
        now = _read(path) if path.exists() else None
        if now and now[0] == local.get(key):
            path.unlink()
        base.pop(key, None)

    batch: list[dict[str, Any]] = []
    size = 0

    def flush() -> None:
        nonlocal batch, size
        if batch:
            _call("mutation", "extractor:put", {"files": batch}, timeout=120)
            for f in batch:
                base[(f["folder"], f["name"])] = f["hash"]
            _save_base(base)
            batch, size = [], 0

    pushed = 0
    for key in push:
        path = _path(*key)
        r = _read(path)
        if r is None:
            continue
        if size + len(r[1]) > BATCH:
            flush()
        batch.append({"folder": key[0], "name": key[1], "hash": r[0], "size": len(r[1]),
                      "updatedAt": int(path.stat().st_mtime * 1000), "content": r[1]})
        size += len(r[1])
        pushed += 1
    flush()
    if drop_remote:
        _call("mutation", "extractor:remove", {"files": [{"folder": f, "name": n} for f, n in drop_remote]})
        for key in drop_remote:
            base.pop(key, None)
    _save_base(base)
    return {"ok": True, "pushed": pushed, "pulled": pulled, "kept": kept, "removedHere": len(drop_local), "removedThere": len(drop_remote)}


# ---------------------------------------------------------------- background
def request() -> None:
    """Ask for a pass soon. Called after every change made through the app."""
    _wake.set()


def request_if_stale(seconds: float = 20) -> None:
    """Ask for a pass when the last one is older than this: what another machine did shows up."""
    if time.time() - _state["at"] > seconds:
        _wake.set()


def status() -> dict[str, Any]:
    return {"at": _state["at"] or None, "ok": _state["ok"], "error": _state["error"], "last": _state["last"]}


def start() -> None:
    """Run passes in the background for as long as the server lives."""
    def loop() -> None:
        while True:
            # After a failed pass (Convex away) the next try comes by itself.
            _wake.wait(timeout=60 if _state["ok"] is False else None)
            time.sleep(1.5)  # a burst of autosaves becomes one pass
            _wake.clear()
            r = run()
            if r.get("ok") and (r["pulled"] or r["removedHere"]):
                print(f"From Convex: {r['pulled']} files fetched, {r['removedHere']} removed", flush=True)

    if convex_url():
        threading.Thread(target=loop, daemon=True).start()
