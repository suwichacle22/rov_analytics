"""Take the two screenshots of every game of a match out of its source video.

The broadcast carries a chapter where each draft starts and one where each game starts. Around
them the tool looks for:

- the draft bar with all ten picks locked, before the swap phase moves anything, and
- the full-screen GAME STATS screen after the game.

YouTube serves every rendition as a DASH mp4 with a segment index: a fragment every five seconds,
each starting on a keyframe. Only the fragments needed are fetched, over several connections at
once, and OpenCV decodes them, so no ffmpeg is needed. Scanning runs on a small rendition; only
the chosen frames come from the 1080p one.
"""
from __future__ import annotations

import bisect
import contextlib
import itertools
import re
import shutil
import struct
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np

from . import push as cloud
from . import recognise, refdata, store
from .paths import data_dir
from .source import _Silent

# "FS vs KOG เริ่มดราฟเกม 1" (draft of game 1 starts), "FS vs KOG เริ่มเกม 1" (game 1 starts)
CHAPTER_RE = re.compile(r"^\s*(\S+)\s+vs\.?\s+(\S+)\s+เริ่ม(ดราฟ)?เกม\s*(\d+)", re.IGNORECASE)
DRAFT_LEN = 560        # usual seconds from the draft chapter to the game chapter, for a missing one
POST_AFTER = 300       # no game ends sooner than this after its chapter (a 7:17 game showed its stats at 518 s)
POST_LIMIT = 3600      # nor later than this
SETTLE = 1.5           # seconds after the last pick locks, past its animation
CHUNK, WORKERS = 24, 8  # fragments per request, parallel requests

# Parts of the RPL 2026 screens that the layout file does not describe.
STAR = [(0.39, 0.66, 0.43, 0.88), (0.57, 0.66, 0.61, 0.88)]  # the turn marker under each team logo
BAN_LABELS = [(0.0, 0.03, 0.05, 0.19), (0.95, 0.03, 1.0, 0.19)]
PICK_ICON, PICK_PLAIN = (0.25, 0.38, 0.75, 0.62), [(0.15, 0.06, 0.85, 0.26), (0.15, 0.74, 0.85, 0.94)]
BAN_PLAIN = [(0.42, 0.12, 0.58, 0.26), (0.42, 0.74, 0.58, 0.88), (0.12, 0.42, 0.26, 0.58), (0.74, 0.42, 0.88, 0.58)]
STATS_TITLE, STATS_PANEL = (0.35, 0.31, 0.65, 0.37), (0.35, 0.39, 0.65, 0.85)
STATS_ITEMS = [(0.02, 0.14, 0.11, 0.18), (0.89, 0.14, 0.98, 0.18)]


def hms(t: float | None) -> str:
    if t is None:
        return "-"
    t = int(round(t))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}"


# ---------------------------------------------------------------- video
class Stream:
    """One video-only mp4 rendition, read by byte range through its segment index (sidx)."""

    def __init__(self, page: str, fmt: dict[str, Any], tmp: Path) -> None:
        self.page, self.format_id, self.height, self.tmp = page, fmt["format_id"], fmt.get("height"), tmp
        self.url, self.headers = fmt["url"], dict(fmt.get("http_headers") or {})
        self.lock = threading.Lock()
        head = self._get(0, 400_000)
        pos = 0
        while pos + 8 <= len(head):
            size, typ = struct.unpack(">I4s", head[pos:pos + 8])
            if typ == b"sidx" or size < 8:
                break
            pos += size
        if head[pos + 4:pos + 8] != b"sidx":
            raise RuntimeError("the stream has no segment index")
        body = head[pos + 8:pos + size]
        scale = struct.unpack(">I", body[8:12])[0]
        ept, first, q = struct.unpack(">II", body[12:20]) + (20,) if body[0] == 0 else struct.unpack(">QQ", body[12:28]) + (28,)
        count = struct.unpack(">H", body[q + 2:q + 4])[0]
        off, t = pos + size + first, ept / scale
        self.segs: list[tuple[int, int]] = []
        self.starts: list[float] = []
        for k in range(count):
            ref, dur = struct.unpack(">II", body[q + 4 + 12 * k:q + 12 + 12 * k])
            self.segs.append((off, off + (ref & 0x7FFFFFFF)))
            self.starts.append(t)
            off, t = off + (ref & 0x7FFFFFFF), t + dur / scale
        self.init = head[:pos]

    def _get(self, a: int, b: int) -> bytes:
        for attempt in range(6):  # YouTube answers a range request with a 5xx now and then
            url = self.url
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={**self.headers, "Range": f"bytes={a}-{b}"}), timeout=60) as r:
                    return r.read()
            except OSError as e:
                if attempt == 5:
                    raise
                if getattr(e, "code", None) == 403:
                    with self.lock:
                        if self.url == url:
                            self._renew()
                time.sleep(2 ** attempt)
        return b""

    def _renew(self) -> None:
        """A fresh address for the same rendition, after YouTube refused the old one."""
        fmt = next((f for f in _open(self.page).get("formats") or [] if f.get("format_id") == self.format_id and f.get("protocol") == "https"), None)
        if fmt:
            self.url, self.headers = fmt["url"], dict(fmt.get("http_headers") or {})

    def index(self, t: float) -> int:
        return max(0, bisect.bisect_right(self.starts, t) - 1)

    def _load(self, idx: list[int]) -> dict[int, bytes]:
        """Fragments by index. Neighbours share a request, and requests run in parallel."""
        runs: list[list[int]] = []
        for i in idx:
            if runs and i == runs[-1][-1] + 1 and len(runs[-1]) < CHUNK:
                runs[-1].append(i)
            else:
                runs.append([i])

        def fetch(run: list[int]) -> dict[int, bytes]:
            a = self.segs[run[0]][0]
            data = self._get(a, self.segs[run[-1]][1] - 1)
            return {i: data[self.segs[i][0] - a:self.segs[i][1] - a] for i in run}

        out: dict[int, bytes] = {}
        with ThreadPoolExecutor(WORKERS) as ex:
            for part in ex.map(fetch, runs):
                out.update(part)
        return out

    def _decode(self, i: int, data: bytes, every: float | None, stop: float = float("inf")) -> list[tuple[float, np.ndarray]]:
        """Frames of one fragment: the first only, or one every `every` seconds up to `stop`."""
        p = self.tmp / f"{self.height}_{i}.mp4"
        p.write_bytes(self.init + data)
        cap = cv2.VideoCapture(str(p))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        out, n, due = [], 0, 0.0
        while self.starts[i] + n / fps <= stop and cap.grab():
            if n / fps >= due - 1e-6:
                ok, img = cap.retrieve()
                if ok:
                    out.append((self.starts[i] + n / fps, img))
                if every is None:
                    break
                due += every
            n += 1
        cap.release()
        with contextlib.suppress(OSError):  # a virus scanner may still hold it; the folder goes at the end
            p.unlink()
        return out

    def keyframes(self, t0: float, t1: float) -> Iterator[tuple[float, np.ndarray]]:
        """The first frame of every fragment between t0 and t1, in order, fetched a batch at a time."""
        idx = list(range(self.index(t0), self.index(t1) + 1))
        for k in range(0, len(idx), CHUNK * WORKERS):
            part = self._load(idx[k:k + CHUNK * WORKERS])
            with ThreadPoolExecutor(WORKERS) as ex:
                for frames in ex.map(lambda i: self._decode(i, part[i], None), sorted(part)):
                    yield from frames

    def frames(self, t0: float, t1: float, every: float) -> list[tuple[float, np.ndarray]]:
        part = self._load(list(range(self.index(t0), self.index(t1) + 1)))
        with ThreadPoolExecutor(WORKERS) as ex:
            decoded = ex.map(lambda i: self._decode(i, part[i], every), sorted(part))
        return [(t, img) for frames in decoded for t, img in frames if t0 <= t <= t1]

    def frame_at(self, t: float) -> tuple[float, np.ndarray]:
        i = self.index(t)
        frames = self._decode(i, self._load([i])[i], 0.001, stop=t + 0.05)
        return min(frames, key=lambda f: abs(f[0] - t))


def _open(url: str) -> dict[str, Any]:
    """Chapters and renditions of the video. YouTube leaves the https renditions out now and then, so ask again."""
    from yt_dlp import YoutubeDL

    for attempt in range(4):
        with YoutubeDL({"quiet": True, "no_warnings": True, "logger": _Silent(), "skip_download": True, "noplaylist": True, "socket_timeout": 30}) as ydl:
            info = ydl.extract_info(url, download=False)
        if attempt == 3 or any(f.get("protocol") == "https" and f.get("height") == 1080 for f in info.get("formats") or []):
            return info
        time.sleep(3)
    return info


def _rendition(info: dict[str, Any], height: int, exact: bool = False) -> dict[str, Any]:
    """The H.264 video-only mp4 closest to `height` from above."""
    cands = [f for f in info.get("formats") or [] if f.get("ext") == "mp4" and f.get("protocol") == "https" and f.get("height")
             and str(f.get("vcodec") or "").startswith("avc1") and f.get("acodec") in (None, "none")]
    fit = [f for f in cands if (f["height"] == height if exact else f["height"] >= height)]
    if not fit:
        raise RuntimeError(f"no {height}p mp4 stream in this video")
    return min(fit, key=lambda f: (f["height"], f.get("tbr") or 0))


# ---------------------------------------------------------------- chapters
def chapters(info: dict[str, Any], teams: set[str]) -> tuple[dict[int, dict[str, float]], list[float]]:
    """Draft and game start per game of this match, and the start of every other chapter."""
    games: dict[int, dict[str, float]] = {}
    others = []
    for c in info.get("chapters") or []:
        m = CHAPTER_RE.match(c.get("title") or "")
        if m and {m.group(1).upper(), m.group(2).upper()} == teams:
            games.setdefault(int(m.group(4)), {})["draft" if m.group(3) else "game"] = float(c["start_time"])
        else:
            others.append(float(c["start_time"]))
    return games, others


# ---------------------------------------------------------------- draft bar
def _hsv_share(crop: np.ndarray, lo: tuple[int, int, int], hi: tuple[int, int, int]) -> float:
    return float(cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), lo, hi).mean() / 255) if crop.size else 0.0


def _gray(crop: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else np.zeros((1, 1), np.uint8)


def _pick_filled(crop: np.ndarray) -> bool:
    """An open pick slot shows a gold role icon on a dark, see-through ground."""
    if recognise.is_empty_slot(crop):
        return False
    icon = _hsv_share(recognise.crop_rel(crop, PICK_ICON), (15, 25, 190), (32, 120, 255))
    return not (icon > 0.3 and max(_gray(recognise.crop_rel(crop, b)).mean() for b in PICK_PLAIN) < 90)


def _ban_filled(crop: np.ndarray) -> bool:
    """An open ban slot is a dark box with a thin X; the parts beside the X stay plain."""
    if recognise.is_empty_slot(crop):
        return False
    return not all(_gray(p).mean() < 90 and _gray(p).std() < 20 for p in (recognise.crop_rel(crop, b) for b in BAN_PLAIN))


def draft_state(img: np.ndarray, layout: dict[str, Any]) -> dict[str, Any] | None:
    """What the draft bar shows in one frame, or None when the bar is not on screen."""
    L = layout["draftBar"]
    bar = recognise.locate_bar(img, layout)
    if bar is None:
        return None
    boxes = L["bluePicks"] + L["redPicks"]
    # Light strips with dark seat names beside a dark caption strip, and the white letters of BAN at
    # both ends. Stage shots with a white desk or floor along the bottom pass one test, never all.
    y0, y1 = L["nameBand"]
    names = [_gray(recognise.crop_rel(bar, (b[0], y0 + 0.4 * (y1 - y0), b[2], y1))) for b in boxes]
    caption = _gray(recognise.crop_rel(bar, (L["caption"][0], y0 + 0.4 * (y1 - y0), L["caption"][2], y1)))
    labels = [_gray(recognise.crop_rel(bar, b)) for b in BAN_LABELS]
    if (min(np.percentile(n, 75) for n in names) < 170 or min((n < 120).mean() for n in names) < 0.04
            or np.percentile(caption, 25) > 100 or not all(0.1 < (g > 200).mean() < 0.4 for g in labels)):
        return None
    picks = [recognise.crop_rel(bar, b) for b in boxes]
    return {
        "picks": [_pick_filled(c) for c in picks],
        "bans": [_ban_filled(recognise.crop_rel(bar, b)) for b in L["blueBans"] + L["redBans"]],
        "star": max(_hsv_share(recognise.crop_rel(bar, b), (95, 110, 170), (130, 255, 255)) for b in STAR) > 0.03,
        "thumbs": [cv2.resize(_gray(c), (12, 20), interpolation=cv2.INTER_AREA).astype(np.int16) for c in picks],
    }


def _moved(a: dict[str, Any], b: dict[str, Any], skip: int | None = None) -> list[int]:
    """Pick slots whose art differs between two states. Another hero differs by 40 or more; a
    keyframe of the small scan rendition alone can shift a busy splash by up to 30."""
    return [i for i, (x, y) in enumerate(zip(a["thumbs"], b["thumbs"])) if i != skip and float(np.abs(x - y).mean()) > 35]


def _locked(s: dict[str, Any] | None) -> bool:
    return bool(s and all(s["picks"]) and not s["star"])


def _last_pick(layout: dict[str, Any]) -> int:
    """Position of pick 10 in the blue-then-red list of pick slots."""
    order = layout["blue"]["pickSlots"] + layout["red"]["pickSlots"]
    return order.index(max(order))


def find_draft(scan: Stream, full: Stream, layout: dict[str, Any], lo: float, hi: float, game_no: int, teams: set[str]) -> dict[str, Any] | None:
    """Earliest frame with every pick locked and nothing swapped yet.

    While a pick is open the turn marker shows under that team's logo, and the hovered hero is
    already drawn in its slot. The marker goes away when pick 10 locks and the swap phase starts,
    so the first frame with ten heroes and no marker is the one. At the same moment the timer resets
    for the swap phase, and it must still read 00:59 (00:57 at the lowest) on the frame taken: the
    latest 1080p frame up to SETTLE seconds on with the best reading and no hero moved. A frame
    that misses the rule comes back with ok False and is not attached.
    """
    first = next((t for t, img in scan.keyframes(lo, hi) if (s := draft_state(img, layout)) and all(s["picks"])), None)
    if first is None:
        return None
    notes: list[str] = []
    states = [(t, draft_state(img, layout)) for t, img in scan.frames(first - 5.5, first + 60, 0.25)]
    hover = t = None
    for k, (t0, s0) in enumerate(states):
        if s0 and all(s0["picks"]) and s0["star"]:
            hover = s0
        if not _locked(s0):
            continue
        run = [(u, s) for u, s in states[k:] if u <= t0 + SETTLE + 0.01]
        if any(s and s["star"] for _, s in run):
            continue  # the marker was only between two turns
        held = list(itertools.takewhile(lambda f: _locked(f[1]) and not _moved(s0, f[1]), run))
        t = held[-1][0]
        if len(held) < len(run):
            notes.append(f"the bar changed {t - t0 + 0.25:.2f} s after the last pick locked")
        break
    if t is None:
        t0 = t = first
        notes.append("no frame with the last pick locked; took the first full bar")
    elif hover is None:
        notes.append("the last pick was not seen open, so a swap before this frame cannot be ruled out")
    elif _moved(hover, s0, skip=_last_pick(layout)):
        notes.append("heroes moved between the last pick and this frame (swap?)")
    best = None
    for u, big in full.frames(t0 - 0.25, t, 0.25):
        clock = draft_timer(big, layout)
        if clock[1] in (57, 58, 59) and _locked(draft_state(big, layout)) and (best is None or clock[1] >= best[2][1]):
            best = (u, big, clock)
    if best is None:
        t, img = full.frame_at(t)
        clock = draft_timer(img, layout)
        notes.append(f"the timer reads '{clock[0]}', not 00:57 to 00:59: not attached")
    else:
        t, img, clock = best
    s = draft_state(img, layout)
    if not _locked(s):
        notes.append("the 1080p frame does not show ten locked picks")
    elif not all(s["bans"]):
        notes.append(f"{8 - sum(s['bans'])} ban slot(s) look empty")
    bar = recognise.locate_bar(img, layout)
    cap = recognise.ocr_line(recognise.crop_rel(bar, layout["draftBar"]["caption"]))[0].upper() if bar is not None else ""
    m = re.search(r"GAME\s*(\d)", cap)
    if not m or int(m.group(1)) != game_no or not all(team in cap for team in teams):
        notes.append(f"caption reads '{cap}'")
    return {"time": t, "image": img, "notes": notes, "timer": clock[0], "ok": best is not None}


def draft_timer(img: np.ndarray, layout: dict[str, Any]) -> tuple[str, int | None]:
    """The timer on the draft bar as read, and in seconds when it reads as 00:ss."""
    bar = recognise.locate_bar(img, layout)
    text = recognise.ocr_line(recognise.crop_rel(bar, layout["draftBar"]["timer"]))[0] if bar is not None else ""
    m = re.fullmatch(r"\s*00\D?(\d{2})\s*", text)
    return text, int(m.group(1)) if m else None


# ---------------------------------------------------------------- post-game screen
def stats_screen(img: np.ndarray) -> bool:
    """Cheap look for the full-screen GAME STATS layout: light title box over a dark panel, blue ITEMS labels."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    title, panel = recognise.crop_rel(hsv, STATS_TITLE), recognise.crop_rel(hsv, STATS_PANEL)
    items = [recognise.crop_rel(hsv, b).reshape(-1, 3).mean(0) for b in STATS_ITEMS]
    return bool(title[..., 2].mean() > 120 and title[..., 1].mean() < 80 and panel[..., 2].mean() < 90
                and all(100 <= h <= 128 and s > 100 and v > 140 for h, s, v in items))


def read_stats(img: np.ndarray, layout: dict[str, Any]) -> dict[str, Any]:
    """The game time, VICTORY or DEFEAT, and how many of the 20 damage numbers can be read.

    The damage numbers sit on the bars that grow in when the screen appears, so all 20 mean
    the screen is fully drawn. VICTORY on the left runs upwards, so both turns are read.
    """
    P = layout["postGame"]
    clock = recognise.ocr_line(recognise.crop_rel(img, P["gameTime"], pad=0.004), scale=4.0)[0]
    result = " ".join(recognise.ocr_line(cv2.rotate(recognise.crop_rel(img, P[k]), turn))[0].upper()
                      for k in ("resultBlue", "resultRed") for turn in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE))
    damage = 0
    for side in ("blue", "red"):
        for i in range(5):
            y0 = P["rowTop"] + i * P["rowPitch"]
            for key in ("dmgDealt", "dmgTaken"):
                box = P[f"{side}Row"][key]
                damage += recognise.ocr_number(recognise.crop_rel(img, (box[0], y0 + box[1], box[2], y0 + box[3]))) is not None
    return {"clock": clock, "result": ("VICT" in result) + ("DEFE" in result), "damage": damage,
            # the colon of the game time reads as - or . now and then
            "ok": bool(re.search(r"\d{1,2}\D{1,2}\d{2}", clock)) and ("VICT" in result or "DEFE" in result)}


def find_post(scan: Stream, full: Stream, layout: dict[str, Any], lo: float, hi: float) -> dict[str, Any] | None:
    """First GAME STATS screen after the game, taken in the middle of its time on screen."""
    for tk, img in scan.keyframes(lo, hi):
        if not stats_screen(img) or not read_stats(full.frame_at(tk)[1], layout)["ok"]:
            continue
        near = scan.frames(tk - 30, tk + 90, 0.5)
        k = next(i for i, (t, _) in enumerate(near) if t >= tk - 0.01)
        a = b = k
        while a > 0 and stats_screen(near[a - 1][1]):
            a -= 1
        while b + 1 < len(near) and stats_screen(near[b + 1][1]):
            b += 1
        start, end = near[a][0], near[b][0]
        best = None
        for frac in (0.5, 0.7, 0.3, 0.85):
            t, big = full.frame_at(start + (end - start) * frac)
            r = read_stats(big, layout)
            if r["ok"] and r["damage"] == 20 and r["result"] == 2:
                return {"time": t, "image": big, "notes": [] if end - start >= 4 else [f"on screen only {end - start:.0f} s"]}
            if best is None or (r["ok"], r["damage"], r["result"]) > (best[2]["ok"], best[2]["damage"], best[2]["result"]):
                best = (t, big, r)
        t, big, r = best
        return {"time": t, "image": big, "notes": [f"read {r['damage']}/20 damage numbers, {r['result']}/2 of VICTORY and DEFEAT"]}
    return None


# ---------------------------------------------------------------- attach
def has_image(series_id: str, game_no: int, kind: str) -> bool:
    return store.find_image(series_id, game_no, kind) is not None or bool(cloud.convex_url() and cloud.image_info(series_id, game_no, kind))


def attach(series_id: str, game_no: int, kind: str, img: np.ndarray) -> str:
    """Store a frame the way the upload endpoint stores an attached screenshot."""
    name = store.image_name(store.load_series(series_id), game_no, kind, ".png")
    for old in store.images_of(series_id, game_no, kind):
        if old.name != name:
            old.unlink()
    dest = store.series_path(series_id) / name
    cv2.imwrite(str(dest), img)
    if cloud.convex_url():
        r = cloud.upload_image(series_id, game_no, kind, dest)
        if not r.get("ok"):
            return f"{name} (Convex upload FAILED: {r.get('error')})"
    return name


# ---------------------------------------------------------------- entry point
def grab(series_id: str, game_no: int | None = None, force: bool = False, dry_run: bool = False,
         say=lambda line: print(line, flush=True)) -> int:
    """Find and attach the screenshots of every game of a match. Returns the number of problems."""
    series = store.load_series(series_id)
    if not series.vodUrl:
        say(f"{series_id} has no source link")
        return 1
    layout = refdata.layout(series.layout)
    teams = {series.teamA.upper(), series.teamB.upper()}
    began = time.monotonic()
    try:
        info = _open(series.vodUrl)
    except Exception as e:  # noqa: BLE001  yt-dlp raises its own errors, for example a bot check
        say(f"cannot open the video: {e}")
        return 1
    games, others = chapters(info, teams)
    if not games:
        say(f"no chapter of {series.teamA} vs {series.teamB} in the video")
        return 1
    tmp = data_dir() / "grab_tmp" / series_id
    tmp.mkdir(parents=True, exist_ok=True)
    problems = 0
    try:
        try:
            full = Stream(series.vodUrl, _rendition(info, 1080, exact=True), tmp)
            draft_scan, post_scan = (Stream(series.vodUrl, _rendition(info, h), tmp) for h in (360, 144))
        except (RuntimeError, OSError) as e:
            say(f"cannot read the video: {e}")
            return 1
        end = float(info.get("duration") or full.starts[-1])
        found_post = None
        for n in range(1, max(games) + 1):
            if game_no and n != game_no:
                continue
            g, notes = games.get(n, {}), []
            draft_at, game_at = g.get("draft"), g.get("game")
            if draft_at is None and game_at is None:
                prev = games.get(n - 1, {})
                draft_at = found_post or (prev.get("game", prev.get("draft", 0)) + POST_AFTER)
                notes.append("no chapter for this game, searched after the previous one")
            elif draft_at is None:
                draft_at = game_at - DRAFT_LEN
                notes.append("draft chapter missing, estimated")
            elif game_at is None:
                notes.append("game chapter missing, estimated")
            todo = [k for k in ("draft", "post") if force or not has_image(series_id, n, k)]
            if not todo:
                say(f"g{n}  both screenshots already attached, skipped")
                continue
            t_game = time.monotonic()
            draft = post = None
            wide = 300 if notes else 0
            if "draft" in todo or game_at is None:
                draft = find_draft(draft_scan, full, layout, draft_at - 30 - wide, (game_at or draft_at + DRAFT_LEN) + 60 + wide, n, teams)
            if game_at is None:
                game_at = draft["time"] + 150 if draft else draft_at + DRAFT_LEN
            # the post-game screen comes before the next draft, the next match, and the end of the video
            bounds = others + [t for k, v in games.items() if k != n for t in v.values()]
            stop = min([t for t in bounds if t > game_at + 60] + [game_at + POST_LIMIT, end])
            if "post" in todo:
                post = find_post(post_scan, full, layout, game_at + POST_AFTER, stop)
                found_post = post["time"] if post else None
            files = []
            for kind, hit in (("draft", draft), ("post", post)):
                if kind not in todo:
                    files.append(f"{kind} kept")
                    continue
                if hit is None:
                    files.append(f"{kind} NOT FOUND")
                    problems += 1
                    continue
                notes += [f"{kind}: {x}" for x in hit["notes"]]
                shown = f"{kind} {hms(hit['time'])}" + (f" timer {hit['timer'] or '?'}" if kind == "draft" else "")
                if not hit.get("ok", True):
                    files.append(f"{shown} NOT ATTACHED")
                    problems += 1
                    continue
                files.append(f"{shown} " + ("(dry run)" if dry_run else attach(series_id, n, kind, hit["image"])))
            flag = "?" if notes else " "
            say(f"g{n}{flag} " + "  ".join(files) + f"  [{time.monotonic() - t_game:.0f} s]")
            for x in notes:
                say(f"      ? {x}")
            problems += bool(notes)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if tmp.parent.exists() and not any(tmp.parent.iterdir()):
            tmp.parent.rmdir()
    say(f"{series_id}: done in {time.monotonic() - began:.0f} s")
    return problems
