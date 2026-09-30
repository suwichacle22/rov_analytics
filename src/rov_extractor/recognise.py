"""Recognition: propose values for the form from the two screenshots.

Nothing here writes game data. It returns a proposal with a confidence per field
and the form decides what to prefill.

- Text (names, K/D/A, damage, totals, caption, timer) comes from OCR run in
  recognition-only mode on single-line crops.
- Hero identity comes from artmatch: every crop is searched for inside the hero splash art.
  The draft bar and the post-game screen both show each ban, and the post-game portraits show
  each team's five heroes, so every slot gets a second opinion.
- The 18 slots are decided together. A hero is given to one slot only, and a team is never
  offered a hero it already picked earlier in the series.
- Who played which hero comes from the post-game screen. The names under the draft bar are the
  seats that made the pick, which differ whenever the team swapped.
"""
from __future__ import annotations

import difflib
import itertools
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import artmatch, refdata
from .paths import ref_dir

Box = tuple[float, float, float, float]



# ---------------------------------------------------------------- image helpers
def crop_rel(img: np.ndarray, box: Box, pad: float = 0.0) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[max(0, int((y0 - pad) * h)):min(h, int((y1 + pad) * h)), max(0, int((x0 - pad) * w)):min(w, int((x1 + pad) * w))]


def locate_bar(img: np.ndarray, layout: dict[str, Any]) -> np.ndarray | None:
    """Tight crop of the draft bar from either a tight crop or a full 16:9 frame."""
    h, w = img.shape[:2]
    ratio = w / h
    if ratio > 4.2:
        return img
    if 1.6 <= ratio <= 1.95:
        return img[int(layout["draftBar"]["fullFrameTop"] * h):h]
    return None


def hsv_hist(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 8, 4], [0, 180, 0, 256, 0, 256])
    cv2.normalize(h, h)
    return h


def face_vs_splash(face: np.ndarray, splash: np.ndarray) -> float:
    """Colour distribution of the portrait against the upper half of the splash."""
    top = splash[: int(splash.shape[0] * 0.5)]
    if face.size == 0 or top.size == 0:
        return -1.0
    return float(cv2.compareHist(hsv_hist(face), hsv_hist(top), cv2.HISTCMP_CORREL))


def flatten_alpha(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4] / 255.0
        return (img[:, :, :3].astype(np.float32) * alpha + 20 * (1 - alpha)).astype(np.uint8)
    return img


def is_empty_slot(crop: np.ndarray) -> bool:
    return crop.size == 0 or float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std()) < 12


# ---------------------------------------------------------------- reference art
def art_dir() -> Path:
    return ref_dir() / "art"


def crops_dir() -> Path:
    d = ref_dir() / "crops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reset_banks() -> None:
    """Forget the loaded artwork, after hero art or saved crops changed."""
    artmatch.reset()


# ---------------------------------------------------------------- progress
# Rough seconds per step on a desktop CPU. Only the proportions matter: the pace of the steps
# already finished rescales them to this machine.
LINE, DETECT, MATCH = 0.6, 9.5, 3.0
_run = threading.local()


class Progress:
    """How far one Recognise run is, read by the progress bar from another thread."""

    def __init__(self, draft: bool, post: bool) -> None:
        self.total = draft * (4 * MATCH + 11 * LINE) + post * (5 * LINE + 2 * (22 * LINE + 2 * MATCH + 3 * DETECT)) or 1.0
        self.done = self.spent = self.current = 0.0
        self.began = time.monotonic()
        self.label = "Starting"

    def fraction(self) -> float:
        pace = max(self.spent / self.done, 1e-6) if self.done else 1.0
        current, began = self.current, self.began
        # Inside a step the bar moves with the clock, and waits at 90% of the step if it runs long.
        part = current * min((time.monotonic() - began) / (current * pace), 0.9) if current else 0.0
        return min((self.done + part) / self.total, 0.99)


@contextmanager
def _step(weight: float):
    p = getattr(_run, "progress", None)
    if p is None:
        yield
        return
    p.began, p.current = time.monotonic(), weight
    try:
        yield
    finally:
        p.spent += time.monotonic() - p.began
        p.done, p.current = p.done + weight, 0.0


def _say(label: str) -> None:
    p = getattr(_run, "progress", None)
    if p is not None:
        p.label = label


# ---------------------------------------------------------------- OCR
@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def warm_up() -> None:
    """Load OCR and banks in the background so the first Recognise click is quick."""
    def run():
        try:
            _ocr_engine()
            artmatch.refs()
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()


def ocr_line(img: np.ndarray, scale: float = 3.0) -> tuple[str, float]:
    """Recognition-only OCR for a single-line crop."""
    if img.size == 0 or img.shape[0] < 4 or img.shape[1] < 4:
        return "", 0.0
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 8, 8, 8, 8, cv2.BORDER_REPLICATE)
    with _step(LINE):
        result, _ = _ocr_engine()(big, use_det=False, use_cls=False)
    if not result:
        return "", 0.0
    return str(result[0][0]).strip(), float(result[0][1])


def ocr_detect(img: np.ndarray, scale: float = 3.0) -> str:
    """Full detect-plus-recognise OCR. Slower, but reliable for lone digits on busy backgrounds."""
    if img.size == 0:
        return ""
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    with _step(DETECT):
        result, _ = _ocr_engine()(big)
    if not result:
        return ""
    result.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
    return " ".join(str(r[1]) for r in result)


def parse_number(t: str) -> int | None:
    t = unicodedata.normalize("NFKC", t).lower().replace(",", ".").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(k|m)?", t)
    if not m:
        return None
    v = float(m.group(1)) * {"k": 1000, "m": 1e6}.get(m.group(2) or "", 1)
    return int(round(v))


def ocr_number(img: np.ndarray, scale: float = 3.0) -> int | None:
    t, _ = ocr_line(img, scale=scale)
    t = t.lower().replace(",", ".").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(k|m)?", unicodedata.normalize("NFKC", t))
    if not m:
        return None
    v = float(m.group(1))
    v *= {"k": 1000, "m": 1e6}.get(m.group(2) or "", 1)
    return int(round(v))


def ocr_kda(img: np.ndarray) -> tuple[int | None, int | None, int | None]:
    t, _ = ocr_line(img)
    parts = re.findall(r"\d+", t.replace("/", " / "))
    if len(parts) >= 3:
        return int(parts[0]), int(parts[1]), int(parts[2])
    return None, None, None


def ocr_duration(img: np.ndarray) -> int | None:
    t, _ = ocr_line(img, scale=4.0)
    m = re.search(r"(\d{1,2})\s*[:.;]\s*(\d{2})", t)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def fuzzy_name(text: str, names: list[str]) -> tuple[str | None, float]:
    t = re.sub(r"[^a-z0-9]", "", text.lower())
    if not t:
        return None, 0.0
    best, score = None, 0.0
    for n in names:
        s = difflib.SequenceMatcher(None, t, re.sub(r"[^a-z0-9]", "", n.lower())).ratio()
        if s > score:
            best, score = n, s
    return (best if score >= 0.6 else None), score


def clean_name(raw: str) -> str | None:
    t = re.sub(r"[^A-Za-z0-9_]", "", raw)
    return t.title() if t else None


# ---------------------------------------------------------------- draft bar
def recognise_draft_bar(path: Path, layout: dict[str, Any], teams: tuple[str, str], rosters: dict[str, list[str]]) -> dict[str, Any]:
    """Seat names, caption and a hero ranking per slot. recognise_game decides the heroes."""
    img = cv2.imread(str(path))
    if img is None:
        return {"error": "cannot read the draft image"}
    bar = locate_bar(img, layout)
    if bar is None:
        return {"error": "unrecognised draft image shape. Give a tight crop of the bar or a full 16:9 frame."}
    L = layout["draftBar"]
    out: dict[str, Any] = {"slots": {}, "fields": {}, "_crops": {}}
    for side, team in (("blue", teams[0]), ("red", teams[1])):
        _say(f"Draft screen: {team} bans and picks")
        ban_crops = [crop_rel(bar, box) for box in L[f"{side}Bans"]]
        pick_crops = [crop_rel(bar, box) for box in L[f"{side}Picks"]]
        out["_crops"][side] = pick_crops
        with _step(MATCH):
            ban_ranks = artmatch.rank_many([None if is_empty_slot(c) else c for c in ban_crops], "ban")
        with _step(MATCH):
            pick_ranks = artmatch.rank_many([None if is_empty_slot(c) else c for c in pick_crops], "pick")
        out["slots"][f"{side}Bans"] = [{"ranking": r, "empty": is_empty_slot(c)} for c, r in zip(ban_crops, ban_ranks)]
        picks = []
        for box, crop, ranking in zip(L[f"{side}Picks"], pick_crops, pick_ranks):
            raw, _ = ocr_line(crop_rel(bar, (box[0], L["nameBand"][0], box[2], L["nameBand"][1])))
            player, pscore = fuzzy_name(raw, rosters.get(team, []))
            picks.append({"player": player or clean_name(raw), "playerRaw": raw, "playerConfident": pscore >= 0.8,
                          "ranking": ranking, "empty": is_empty_slot(crop)})
        out["slots"][f"{side}Picks"] = picks
    cap, _ = ocr_line(crop_rel(bar, L["caption"]))
    out["fields"]["caption"] = cap
    m = re.search(r"game\s*(\d)", cap, re.I)
    if m:
        out["fields"]["gameNo"] = int(m.group(1))
    m = re.search(r"\b([A-Z0-9]{2,5})\s*VS\s*([A-Z0-9]{2,5})\b", cap.upper())
    if m:
        out["fields"]["captionTeams"] = [m.group(1), m.group(2)]
    out["fields"]["learnedPicks"] = artmatch.learned_count("pick")
    out["fields"]["learnedBans"] = artmatch.learned_count("ban")
    return out


# ---------------------------------------------------------------- post-game screen
def recognise_post_game(path: Path, layout: dict[str, Any], teams: tuple[str, str], rosters: dict[str, list[str]]) -> dict[str, Any]:
    img = cv2.imread(str(path))
    if img is None:
        return {"error": "cannot read the post-game image"}
    h, w = img.shape[:2]
    if not (1.6 <= w / h <= 1.95):
        return {"error": "the post-game image should be a full 16:9 screenshot"}
    P = layout["postGame"]
    out: dict[str, Any] = {"fields": {}, "players": {}, "teamStats": {}, "_faces": {}, "_bans": {}}
    _say("Post-game screen: result and game time")
    out["fields"]["durationS"] = ocr_duration(crop_rel(img, P["gameTime"], pad=0.004))
    out["fields"]["scoreBlue"] = ocr_number(crop_rel(img, P["scoreBlue"]))
    out["fields"]["scoreRed"] = ocr_number(crop_rel(img, P["scoreRed"]))
    res_b, _ = ocr_line(cv2.rotate(crop_rel(img, P["resultBlue"]), cv2.ROTATE_90_COUNTERCLOCKWISE))
    res_r, _ = ocr_line(cv2.rotate(crop_rel(img, P["resultRed"]), cv2.ROTATE_90_COUNTERCLOCKWISE))
    res_b, res_r = res_b.upper(), res_r.upper()
    winner = None
    if "VICT" in res_b or "DEFE" in res_r:
        winner = teams[0]
    elif "VICT" in res_r or "DEFE" in res_b:
        winner = teams[1]
    out["fields"]["winner"] = winner
    out["fields"]["resultText"] = [res_b, res_r]

    for side, team in (("blue", teams[0]), ("red", teams[1])):
        R = P[f"{side}Row"]
        rows = []
        faces = []
        _say(f"Post-game screen: {team} players")
        for i in range(5):
            y0 = P["rowTop"] + i * P["rowPitch"]
            rb = lambda b: (b[0], y0 + b[1], b[2], y0 + b[3])  # noqa: E731
            raw, _ = ocr_line(crop_rel(img, rb(R["name"])))
            player, pscore = fuzzy_name(raw, rosters.get(team, []))
            k, d, a = ocr_kda(crop_rel(img, rb(R["kda"])))
            rows.append({"player": player or clean_name(raw), "playerRaw": raw, "playerConfident": pscore >= 0.8,
                         "kills": k, "deaths": d, "assists": a,
                         "dmgDealt": ocr_number(crop_rel(img, rb(R["dmgDealt"]))),
                         "dmgTaken": ocr_number(crop_rel(img, rb(R["dmgTaken"]))),
                         "barSlot": None, "slotScore": None, "hero": None, "heroConfident": False})
            faces.append(crop_rel(img, rb(R["portrait"])))
        with _step(MATCH):
            rankings = artmatch.rank_many(faces, "face")
        for row, ranking in zip(rows, rankings):
            row["ranking"] = ranking
        out["_faces"][side] = faces
        with _step(MATCH):
            out["_bans"][side] = artmatch.rank_many([crop_rel(img, b) for b in P.get(f"{side}Bans", [])], "ban")
        out["players"][side] = rows
        _say(f"Post-game screen: {team} totals")
        stats = {}
        for key, boxes in P["teamStats"].items():
            # kills and gold are multi-character and read well in line mode; lone digits need detection
            val = ocr_number(crop_rel(img, boxes[side], pad=0.004)) if key in ("kills", "gold") else None
            if val is None:
                val = parse_number(ocr_detect(crop_rel(img, boxes[side], pad=0.02)))
            if val is None:
                val = ocr_number(crop_rel(img, boxes[side], pad=0.012), scale=4.0)
            stats[key] = val
        out["teamStats"][side] = stats
    return out


# ---------------------------------------------------------------- deciding the heroes
def _sure(ranking: list[dict[str, Any]]) -> tuple[str | None, float]:
    """The hero of a ranking when it clearly leads, else None."""
    if not ranking:
        return None, 0.0
    lead = ranking[0]["score"] - (ranking[1]["score"] if len(ranking) > 1 else 0.0)
    if ranking[0]["score"] >= artmatch.CONFIDENT and lead >= artmatch.MARGIN:
        return ranking[0]["hero"], ranking[0]["score"]
    return None, 0.0


def _team_support(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Heroes the post-game portraits of one team show for certain."""
    support: dict[str, float] = {}
    for row in rows:
        hero, score = _sure(row.get("ranking") or [])
        if hero:
            support[hero] = max(support.get(hero, 0.0), score)
    return support


def _seconded(ranking: list[dict[str, Any]], support: dict[str, float]) -> list[dict[str, Any]]:
    """Lift the heroes of a pick ranking that the team's portraits confirm, halfway to the portrait score."""
    out = []
    for m in ranking:
        s = support.get(m["hero"], 0.0)
        out.append({**m, "score": round(m["score"] + 0.5 * (s - m["score"]), 3), "seconded": True} if s > m["score"] else m)
    return sorted(out, key=lambda m: m["score"], reverse=True)


def _propose_heroes(draft: dict[str, Any], post: dict[str, Any] | None, teams: tuple[str, str], used: dict[str, set[str]]) -> None:
    slots = []
    for side, team in (("blue", teams[0]), ("red", teams[1])):
        support = _team_support(post["players"][side]) if post else {}
        header = (post or {}).get("_bans", {}).get(side, [])
        for i, slot in enumerate(draft["slots"][f"{side}Bans"]):
            slot["ranking"] = artmatch.merge(slot["ranking"], header[i] if i < len(header) else [])
            slots.append(slot)
        for slot in draft["slots"][f"{side}Picks"]:
            slot["ranking"] = _seconded(slot["ranking"], support)
            slot["banned"] = set(used.get(team, ()))
            slots.append(slot)
    artmatch.assign([s for s in slots if not s["empty"]])
    for s in slots:
        if s["empty"]:
            s.update({"hero": None, "score": None, "confident": False, "candidates": []})


def _face_in_crop(face: np.ndarray, crop: np.ndarray) -> float:
    """How well a post-game portrait is found inside a draft-bar splash."""
    if face.size == 0 or crop.size == 0:
        return -1.0
    q = artmatch.trim(artmatch.gray(face))
    area = artmatch.gray(crop)
    ratio = q.shape[0] / q.shape[1]
    best = -1.0
    for z in artmatch.widths(0.25, 1.0):
        tw = int(round(area.shape[1] * z * (1 - 2 * artmatch.TRIM)))
        if tw < artmatch.MIN_TEMPLATE:
            continue
        best = max(best, artmatch.ncc(area, cv2.resize(q, (tw, max(1, int(round(tw * ratio)))), interpolation=cv2.INTER_AREA)))
    return best


def _map_rows(draft: dict[str, Any] | None, post: dict[str, Any]) -> None:
    """Which draft-bar pick each post-game row played. One row per pick.

    A row whose portrait names a hero for certain goes to the pick with that hero. Only the rows
    and picks left over are compared as images, portrait against draft-bar splash.
    """
    for side in ("blue", "red"):
        rows = post["players"][side]
        faces = post["_faces"][side]
        if not draft:
            continue
        picks = draft["slots"][f"{side}Picks"]
        crops = draft["_crops"][side]
        M = [[0.0] * 5 for _ in range(5)]
        named_rows, named_slots = set(), set()
        for i, row in enumerate(rows):
            hero, score = _sure(row.get("ranking") or [])
            for j, slot in enumerate(picks):
                if hero and slot.get("hero") == hero:
                    M[i][j] = score
                    named_rows.add(i)
                    named_slots.add(j)
        for i, face in enumerate(faces):
            for j, crop in enumerate(crops):
                if i not in named_rows and j not in named_slots:
                    M[i][j] = max(_face_in_crop(face, crop), face_vs_splash(face, crop))
        best = max(itertools.permutations(range(5)), key=lambda perm: sum(M[i][perm[i]] for i in range(5)))
        for i, j in enumerate(best):
            others = max(M[i][k] for k in range(5) if k != j)
            rows[i]["barSlot"] = j
            rows[i]["slotScore"] = round(M[i][j], 3)
            rows[i]["slotConfident"] = bool(M[i][j] >= 0.75 and M[i][j] - others >= 0.08)
            rows[i]["hero"] = picks[j].get("hero")
            rows[i]["heroConfident"] = bool(rows[i]["slotConfident"] and picks[j].get("confident"))


def _rows_without_draft(post: dict[str, Any]) -> None:
    """Only the post-game screen is attached: name the heroes from the portraits alone."""
    rows = [r for side in ("blue", "red") for r in post["players"][side]]
    slots = [{"ranking": r.get("ranking") or []} for r in rows]
    artmatch.assign(slots)
    for row, slot in zip(rows, slots):
        row["hero"], row["heroConfident"], row["candidates"] = slot["hero"], slot["confident"], slot["candidates"]


# ---------------------------------------------------------------- learning
def remember_game(draft_path: Path | None, layout: dict[str, Any], record: dict[str, Any]) -> int:
    """Save draft-bar crops from a confirmed game as references. Returns crops written.

    A crop is kept only when the artwork alone did not already name that hero for certain: a hero
    with no seed art, newer art, or an unusual zoom. Heroes the artwork finds need no copy.
    """
    if not draft_path or not draft_path.exists():
        return 0
    img = cv2.imread(str(draft_path))
    bar = locate_bar(img, layout) if img is not None else None
    if bar is None:
        return 0
    L = layout["draftBar"]
    by_key = {(a["side"], a["action"], a["slot"]): a for a in record["draft"]}
    todo = []
    for side in ("blue", "red"):
        for kind, key in (("ban", "Bans"), ("pick", "Picks")):
            for i, box in enumerate(L[f"{side}{key}"]):
                a = by_key.get((side, kind, i + 1))
                crop = crop_rel(bar, box)
                if a and a.get("hero") and not is_empty_slot(crop):
                    todo.append((kind, a["hero"], crop, f"{record['gameId']}_{side}{kind[0]}{i + 1}"))
    n = 0
    for kind in ("ban", "pick"):
        items = [t for t in todo if t[0] == kind]
        for (_, hero, crop, name), ranking in zip(items, artmatch.rank_many([t[2] for t in items], kind)):
            if _sure(ranking)[0] != hero:
                n += _save_crop(kind, hero, crop, name)
    if n:
        reset_banks()
    return n


def _save_crop(kind: str, hero: str, crop: np.ndarray, name: str) -> int:
    if crop.size == 0:
        return 0
    d = crops_dir() / kind / hero
    d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(d / f"{name}.png"), crop)
    return 1


def save_crop_file(data: bytes, dest: Path) -> bool:
    """Decode an uploaded image and store it as a PNG reference crop."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None or img.size == 0:
        return False
    cv2.imwrite(str(dest), flatten_alpha(img))
    return True


# ---------------------------------------------------------------- entry point
def recognise_game(series_dir: Path, images: dict[str, str], layout: dict[str, Any], teams: tuple[str, str],
                   rosters: dict[str, list[str]], used: dict[str, set[str]] | None = None,
                   progress: Progress | None = None) -> dict[str, Any]:
    """`used` holds, per team, the heroes it picked earlier in the series (Global Ban-Pick)."""
    _run.progress = progress
    try:
        return _recognise_game(series_dir, images, layout, teams, rosters, used)
    finally:
        _run.progress = None


def _recognise_game(series_dir: Path, images: dict[str, str], layout: dict[str, Any], teams: tuple[str, str],
                    rosters: dict[str, list[str]], used: dict[str, set[str]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"draft": None, "post": None, "errors": []}
    draft_path = series_dir / images["draft"] if images.get("draft") else None
    post_path = series_dir / images["post"] if images.get("post") else None
    draft = post = None
    if draft_path and draft_path.exists():
        draft = recognise_draft_bar(draft_path, layout, teams, rosters)
        if "error" in draft:
            out["errors"].append(draft["error"])
            draft = None
    if post_path and post_path.exists():
        post = recognise_post_game(post_path, layout, teams, rosters)
        if "error" in post:
            out["errors"].append(post["error"])
            post = None
    _say("Deciding the heroes")
    if draft:
        _propose_heroes(draft, post, teams, used or {})
    if post:
        _map_rows(draft, post) if draft else _rows_without_draft(post)
    if not draft_path and not post_path:
        out["errors"].append("attach at least one image first")
    out["draft"], out["post"] = _public(draft), _public(post)
    return out


def _public(part: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop the working data (image crops, full rankings) before the proposal leaves this module."""
    if part is None:
        return None
    part = {k: v for k, v in part.items() if not k.startswith("_")}
    for group in list((part.get("slots") or {}).values()) + list((part.get("players") or {}).values()):
        for item in group:
            item.pop("ranking", None)
            item.pop("banned", None)
    return part


def debug_boxes(path: Path, layout: dict[str, Any], kind: str, out_path: Path) -> None:
    img = cv2.imread(str(path))
    if kind == "draft":
        vis = locate_bar(img, layout).copy()
        L = layout["draftBar"]
        h, w = vis.shape[:2]
        for key, colour in (("blueBans", (255, 128, 0)), ("redBans", (0, 0, 255)), ("bluePicks", (255, 200, 0)), ("redPicks", (0, 80, 255))):
            for b in L[key]:
                cv2.rectangle(vis, (int(b[0] * w), int(b[1] * h)), (int(b[2] * w), int(b[3] * h)), colour, 2)
        for key in ("caption", "timer", "score"):
            b = L[key]
            cv2.rectangle(vis, (int(b[0] * w), int(b[1] * h)), (int(b[2] * w), int(b[3] * h)), (0, 255, 0), 2)
    else:
        P = layout["postGame"]
        vis = img.copy()
        h, w = vis.shape[:2]
        def rect(b, c):
            cv2.rectangle(vis, (int(b[0] * w), int(b[1] * h)), (int(b[2] * w), int(b[3] * h)), c, 2)
        for key in ("scoreBlue", "scoreRed", "gameTime", "resultBlue", "resultRed"):
            rect(P[key], (0, 255, 0))
        for side in ("blue", "red"):
            R = P[f"{side}Row"]
            for i in range(5):
                y0 = P["rowTop"] + i * P["rowPitch"]
                for k, c in (("portrait", (255, 0, 0)), ("name", (0, 255, 255)), ("kda", (255, 0, 255)), ("dmgDealt", (0, 200, 255)), ("dmgTaken", (0, 128, 255))):
                    b = R[k]
                    rect((b[0], y0 + b[1], b[2], y0 + b[3]), c)
        for boxes in P["teamStats"].values():
            rect(boxes["blue"], (0, 255, 0)); rect(boxes["red"], (0, 255, 0))
    cv2.imwrite(str(out_path), vis)


def forget_game(game_id: str) -> int:
    """Delete the reference crops that were learned from one saved game. Returns crops removed."""
    root = crops_dir()
    if not root.exists():
        return 0
    n = 0
    for p in root.glob(f"*/*/{game_id}_*.png"):
        p.unlink()
        n += 1
    if n:
        reset_banks()
    return n
