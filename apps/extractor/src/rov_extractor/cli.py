from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import store
from .models import GameInput
from .push import push_game
from .validate import validate_game


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rov-extract", description="RoV draft extractor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the local entry form")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--reload", action="store_true", help="restart automatically when a Python file under src/ changes")
    s.add_argument("--open", action="store_true", help="open the browser once the server is up")
    s.add_argument("--lan", action="store_true", help="listen on every interface so phones on the same Wi-Fi can open it")

    v = sub.add_parser("validate", help="Re-run validation on saved games")
    v.add_argument("series", metavar="match", nargs="?", help="match id, default all")

    p = sub.add_parser("push", help="Push saved games to Convex")
    p.add_argument("series", metavar="match", nargs="?", help="match id, default all")
    p.add_argument("--game", type=int, help="single game number")
    p.add_argument("--heroes", action="store_true", help="also mirror heroes.json into Convex")
    p.add_argument("--drafts", action="store_true", help="also push games that are not saved yet, marked as unchecked")

    sub.add_parser("pull", help="Fetch hero art and learned crops from Convex that this machine lacks")
    sub.add_parser("sync", help="Bring the matches and games here and in Convex in step, in both directions")

    ls = sub.add_parser("list", help="List matches and games on disk")

    pi = sub.add_parser("purge-images", help="Delete local screenshots that are already stored in Convex")
    pi.add_argument("series", metavar="match", nargs="?", help="match id, default all")
    pi.add_argument("--dry-run", action="store_true")

    rc = sub.add_parser("recognise", help="Run recognition on a game's images and print the proposal")
    rc.add_argument("series")
    rc.add_argument("game", type=int)

    rl = sub.add_parser("relearn", help="Rebuild the hero reference bank from every saved game")

    gb = sub.add_parser("grab", help="Take the draft and post-game screenshots of every game from the match's source video")
    gb.add_argument("series", metavar="match")
    gb.add_argument("--game", type=int, help="single game number")
    gb.add_argument("--force", action="store_true", help="replace screenshots that are already attached")
    gb.add_argument("--dry-run", action="store_true", help="find the frames and print the times, attach nothing")

    im = sub.add_parser("import", help="Create the matches named in the broadcasts listed in data/links.txt")
    im.add_argument("--file", type=Path, help="another list of links")
    im.add_argument("--grab", action="store_true", help="also take the screenshots of every match found")
    im.add_argument("--dry-run", action="store_true", help="say what would be created, create nothing")

    args = ap.parse_args(argv)
    if args.cmd == "import":
        from .links import import_links

        return 1 if import_links(args.file, args.grab, args.dry_run) else 0
    if args.cmd == "grab":
        from .grab import grab

        return 1 if grab(args.series, args.game, args.force, args.dry_run) else 0
    if args.cmd == "recognise":
        from . import recognise, refdata

        series = store.load_series(args.series)
        data = store.load_input(args.series, args.game) or {"blueTeam": series.teamA, "images": {}}
        blue = data.get("blueTeam") or series.teamA
        red = series.teamB if blue == series.teamA else series.teamA
        images = dict(data.get("images") or {})
        for kind in ("draft", "post"):
            found = store.find_image(args.series, args.game, kind)
            if found is not None:
                images[kind] = found.name
        r = recognise.recognise_game(store.series_path(args.series), images, refdata.layout(series.layout), (blue, red), refdata.players(),
                                     used=store.used_picks(args.series, args.game))
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "relearn":
        import shutil

        from . import recognise, refdata

        shutil.rmtree(recognise.crops_dir(), ignore_errors=True)
        n = 0
        for sid, gno, game in _iter_games(None):
            series = store.load_series(sid)
            img = (game.get("images") or {}).get("draft")
            if img:
                n += recognise.remember_game(store.series_path(sid) / img, refdata.layout(series.layout), game)
        print(f"{n} crops saved")
        return 0
    if args.cmd == "serve":
        import uvicorn

        host = "0.0.0.0" if args.lan else args.host
        if args.lan:
            print("Reachable on this network at:", flush=True)
            for ip in _lan_ips():
                print(f"   http://{ip}:{args.port}/heroes", flush=True)
            print("Same Wi-Fi only. Windows may ask once to allow Python through the firewall: choose Private networks.", flush=True)
        if args.open:
            _open_browser_when_ready(f"http://127.0.0.1:{args.port}/")
        src_dir = str(Path(__file__).resolve().parent)
        uvicorn.run(
            "rov_extractor.app:app", host=host, port=args.port,
            reload=args.reload,
            # Only code changes restart the server. Static files are read fresh on every request
            # anyway, and the data folder must never trigger a restart (autosaves, uploads).
            reload_dirs=[src_dir] if args.reload else None,
            reload_includes=["*.py"] if args.reload else None,
        )
        return 0
    if args.cmd == "pull":
        from . import push as cloud

        r = cloud.pull_heroes()
        if not r["ok"]:
            print(f"FAILED {r['error']}")
            return 1
        print(f"{r['heroes']} heroes added, {r['art']} art files and {r['crops']} crops fetched, {r['failed']} failed")
        return 1 if r["failed"] else 0
    if args.cmd == "sync":
        from . import sync

        r = sync.run()
        if not r["ok"]:
            print(f"FAILED {r['error']}")
            return 1
        print(f"{r['pulled']} files fetched ({r['kept']} local versions kept as .bak), {r['pushed']} sent, "
              f"{r['removedHere']} removed here, {r['removedThere']} removed in Convex")
        return 0
    if args.cmd == "list":
        for s in store.list_series():
            print(f"{s['seriesId']}  {s['teamA']} vs {s['teamB']}  Bo{s['bestOf']}  games {s['games']}  drafts {s['drafts']}")
        return 0
    if args.cmd == "validate":
        bad = 0
        for sid, n, game in _iter_games(args.series):
            series = store.load_series(sid)
            issues = validate_game(series, GameInput(**game["input"]), store.earlier_games(sid, n))
            errors = [i for i in issues if i.level == "error"]
            print(f"{sid} g{n}: {len(errors)} errors, {len(issues) - len(errors)} warnings")
            for i in issues:
                print(f"   [{i.level}] {i.message}")
            bad += bool(errors)
        return 1 if bad else 0
    if args.cmd == "push":
        from . import push as cloud

        failed = 0
        if args.heroes:
            hr = cloud.push_heroes()
            print(f"heroes: {'ok ' + str(hr['result']) if hr['ok'] else 'FAILED ' + hr['error']}")
            failed += not hr["ok"]
        tr = cloud.push_teams()
        if not tr["ok"]:
            print(f"teams: FAILED {tr['error']}")
            failed += 1
        games = list(_iter_games(args.series, args.game))
        if args.drafts:
            games += list(_iter_drafts(args.series, args.game))
        for sid, n, game in games:
            series = store.load_series(sid).model_dump()
            r = push_game(series, game)
            imgs = []
            for kind in ("draft", "post"):
                name = (game.get("images") or {}).get(kind)
                path = store.find_image(sid, n, kind) or (store.series_path(sid) / name if name else None)
                if path and path.exists() and not cloud.image_info(sid, n, kind):
                    u = cloud.upload_image(sid, n, kind, path)
                    imgs.append(f"{kind} {'uploaded' if u['ok'] else 'FAILED ' + u['error']}")
            note = "" if game.get("checked", True) else " (unchecked)"
            print(f"{sid} g{n}{note}: {'ok' if r['ok'] else 'FAILED ' + r['error']}" + (f"  images: {', '.join(imgs)}" if imgs else ""))
            failed += not r["ok"]
        return 1 if failed else 0
    if args.cmd == "purge-images":
        import re

        from . import push as cloud

        if not cloud.convex_url():
            print("Convex is not configured; nothing to purge against.")
            return 1
        removed = 0
        for s in store.list_series():
            if args.series and s["seriesId"] != args.series:
                continue
            stored = {(i["gameNo"], i["kind"]): i for i in cloud.list_images(s["seriesId"])}
            for p in sorted(store.series_path(s["seriesId"]).iterdir()):
                m = store.parse_image_name(p.name) if p.is_file() else None
                if not m:
                    continue
                info = stored.get((m[0], m[1]))
                if info and info.get("size") == p.stat().st_size:
                    print(f"{'would remove' if args.dry_run else 'removed'} {s['seriesId']}/{p.name}")
                    if not args.dry_run:
                        p.unlink()
                    removed += 1
                else:
                    print(f"keep {s['seriesId']}/{p.name} (not in Convex yet: run push)")
        print(f"{removed} files")
        return 0
    return 0


def _lan_ips() -> list[str]:
    """Best-effort list of this machine's private IPv4 addresses."""
    import socket

    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip not in ips:
                ips.insert(0, ip)
    except OSError:
        pass
    return ips or ["<this-pc-ip>"]


def _open_browser_when_ready(url: str) -> None:
    import socket
    import threading
    import time
    import webbrowser
    from urllib.parse import urlparse

    u = urlparse(url)

    def wait() -> None:
        for _ in range(120):
            try:
                with socket.create_connection((u.hostname, u.port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        webbrowser.open(url)

    threading.Thread(target=wait, daemon=True).start()


def _iter_games(series_id: str | None, game_no: int | None = None):
    for s in store.list_series():
        if series_id and s["seriesId"] != series_id:
            continue
        for n in s["games"]:
            if game_no and n != game_no:
                continue
            yield s["seriesId"], n, store.load_game(s["seriesId"], n)


def _iter_drafts(series_id: str | None, game_no: int | None = None):
    """Games that only have a draft, as game records marked unchecked. A draft without any hero,
    or one that does not parse yet, is skipped."""
    for s in store.list_series():
        if series_id and s["seriesId"] != series_id:
            continue
        series = store.load_series(s["seriesId"])
        for n in s["drafts"]:
            if game_no and n != game_no:
                continue
            try:
                record = store.build_game_record(series, GameInput(**store.load_game(s["seriesId"], n, draft=True)))
            except Exception:  # noqa: BLE001
                continue
            if any(a.get("hero") for a in record["draft"]):
                record["checked"] = False
                yield s["seriesId"], n, record


if __name__ == "__main__":
    sys.exit(main())
