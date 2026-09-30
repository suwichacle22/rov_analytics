"""Hero identity by finding a broadcast crop inside the hero artwork.

The broadcast draws every hero from the same splash art as the seed set in data/ref/art/heropick,
only zoomed and cropped differently per hero: a pick shows the upper body, a ban icon and a
post-game portrait show the face. So the crop is searched for inside each splash at several zoom
levels. The right hero scores 0.8 to 1.0 and every other hero stays near 0.6, which is a far wider
gap than comparing two resized images gives.

Heroes whose art is missing or different are covered by crops saved from games you confirmed
(data/ref/crops/<kind>/<hero>). Those are compared at the same zoom, against crops of the same kind.

Speed: all splashes are laid out in one sheet at quarter size, so one search per zoom level covers
every hero at once. Only the leaders are looked at again at half and at full size.

Forms of one hero (Flowborn Carry, Flowborn Mage) share their artwork and differ only in a small
white badge in the top right corner, so between them the badge decides and the artwork does not.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import cv2
import numpy as np

from . import refdata
from .paths import ref_dir

KINDS = ("pick", "ban")
ART_SIZE = (138, 250)  # width, height every splash is brought to
TRIM = 0.12            # share of the crop cut from every edge: frames, name plates and overlays live there
TINY, COARSE = 0.25, 0.5
MIN_TEMPLATE = 14      # pixels; a smaller template matches anything
MIN_TINY = 8           # the quarter-size pass only shortlists, so it may go smaller
SHORTLIST = (14, 5)    # heroes kept after the quarter-size and the half-size pass
# Width of the crop relative to the width of the splash art, per kind of crop.
ZOOM = {"pick": (0.38, 1.30), "ban": (0.28, 1.00), "face": (0.28, 1.05)}
STEP = 1.07
CONFIDENT = 0.80       # score of a match that can be trusted ...
MARGIN = 0.12          # ... when the next hero is at least this far behind
PLAUSIBLE = 0.62       # below this nothing is proposed at all
PLAUSIBLE_MARGIN = 0.04
SHEET_COLS = 16
BADGE_AREA = (0.5, 0.42)  # the badge sits right of this share of the width and above this share of the height
BADGE_WIDTH = 240         # that area is brought to this width before its white marks are taken
BADGE = 0.72              # a badge found this well decides the form ...
BADGE_GAP = 0.12          # ... when the badge of every other form is at least this far behind


@dataclass(frozen=True)
class Learned:
    hero: str
    kind: str
    image: np.ndarray  # grey


@dataclass(frozen=True)
class Refs:
    heroes: tuple[str, ...]          # one per splash, in sheet order
    full: tuple[np.ndarray, ...]     # grey splashes, ART_SIZE
    small: tuple[np.ndarray, ...]    # the same at COARSE size
    sheet: np.ndarray                # every splash at TINY size in one image
    cell: tuple[int, int]            # width, height of one splash on the sheet
    learned: tuple[Learned, ...]


def gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3].astype(np.float32) * alpha + 20 * (1 - alpha)).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def trim(g: np.ndarray, share: float = TRIM) -> np.ndarray:
    h, w = g.shape[:2]
    return g[int(h * share):max(int(h * share) + 1, int(h * (1 - share))), int(w * share):max(int(w * share) + 1, int(w * (1 - share)))]


_lock = threading.Lock()


@lru_cache(maxsize=1)
def refs() -> Refs:
    with _lock:
        folder = ref_dir() / "art" / refdata.ART_FOLDERS["pick"]
        known = set(refdata.hero_ids())
        heroes, full = [], []
        for hero, entry in sorted(refdata.art_map().items()):
            name = entry.get("pick")
            img = cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED) if name and hero in known else None
            if img is not None:
                heroes.append(hero)
                full.append(cv2.resize(gray(img), ART_SIZE, interpolation=cv2.INTER_AREA))
        small = [cv2.resize(g, None, fx=COARSE, fy=COARSE, interpolation=cv2.INTER_AREA) for g in full]
        cw, ch = int(ART_SIZE[0] * TINY), int(ART_SIZE[1] * TINY)
        rows = max(1, -(-len(full) // SHEET_COLS))
        sheet = np.zeros((rows * ch, SHEET_COLS * cw), np.uint8)
        for i, g in enumerate(full):
            y, x = (i // SHEET_COLS) * ch, (i % SHEET_COLS) * cw
            sheet[y:y + ch, x:x + cw] = cv2.resize(g, (cw, ch), interpolation=cv2.INTER_AREA)
        learned = []
        crops = ref_dir() / "crops"
        for kind in KINDS:
            if not (crops / kind).exists():
                continue
            for hero_dir in sorted((crops / kind).iterdir()):
                if hero_dir.name not in known:
                    continue
                for p in sorted(hero_dir.glob("*.png")):
                    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        learned.append(Learned(hero_dir.name, kind, gray(img)))
        return Refs(tuple(heroes), tuple(full), tuple(small), sheet, (cw, ch), tuple(learned))


def reset() -> None:
    refs.cache_clear()
    families.cache_clear()
    badges.cache_clear()


def learned_count(kind: str) -> int:
    return sum(1 for r in refs().learned if r.kind == kind)


def ncc(area: np.ndarray, template: np.ndarray, smallest: int = MIN_TEMPLATE) -> float:
    if template.shape[0] > area.shape[0] or template.shape[1] > area.shape[1]:
        return -1.0
    if min(template.shape[:2]) < smallest or float(template.std()) < 4.0:
        return -1.0
    return float(cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED).max())


def widths(lo: float, hi: float, step: float = STEP) -> list[float]:
    out, w = [], lo
    while w <= hi * 1.0001:
        out.append(w)
        w *= step
    return out


def _template(q: np.ndarray, area_width: int, zoom: float) -> np.ndarray | None:
    tw = int(round(area_width * zoom * (1 - 2 * TRIM)))
    if tw < 2:
        return None
    return cv2.resize(q, (tw, max(1, int(round(tw * q.shape[0] / q.shape[1])))), interpolation=cv2.INTER_AREA)


def _search(area: np.ndarray, q: np.ndarray, zooms: list[float]) -> tuple[float, float]:
    """Best score of the trimmed crop inside one splash, and the zoom it was found at."""
    best, best_z = -1.0, 0.0
    for z in zooms:
        t = _template(q, area.shape[1], z)
        s = ncc(area, t) if t is not None else -1.0
        if s > best:
            best, best_z = s, z
    return best, best_z


def _search_sheet(r: Refs, q: np.ndarray, zooms: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Best score and zoom per splash, from one search of the whole sheet per zoom level."""
    cw, ch = r.cell
    rows = r.sheet.shape[0] // ch
    best = np.full(rows * SHEET_COLS, -1.0, np.float32)
    best_z = np.zeros(rows * SHEET_COLS, np.float32)
    for z in zooms:
        t = _template(q, cw, z)
        if t is None or min(t.shape[:2]) < MIN_TINY or t.shape[0] > ch or t.shape[1] > cw or float(t.std()) < 4.0:
            continue
        res = cv2.matchTemplate(r.sheet, t, cv2.TM_CCOEFF_NORMED)
        full = np.full(r.sheet.shape, -1.0, np.float32)
        full[:res.shape[0], :res.shape[1]] = res
        cells = full.reshape(rows, ch, SHEET_COLS, cw)
        # A window that starts too far right or down would reach into the neighbouring splash.
        cells = cells[:, :ch - t.shape[0] + 1, :, :cw - t.shape[1] + 1]
        score = cells.max(axis=(1, 3)).reshape(-1)
        better = score > best
        best[better], best_z[better] = score[better], z
    return best[:len(r.heroes)], best_z[:len(r.heroes)]


def _search_learned(ref: Learned, g: np.ndarray) -> float:
    """A crop saved from an earlier broadcast shows the same zoom, so only small shifts are tried."""
    h, w = g.shape[:2]
    area = cv2.resize(ref.image, (w, h), interpolation=cv2.INTER_AREA)
    best = -1.0
    for z in (0.94, 1.0, 1.06):
        t = trim(g)
        t = cv2.resize(t, (max(1, int(round(t.shape[1] * z))), max(1, int(round(t.shape[0] * z)))), interpolation=cv2.INTER_AREA)
        best = max(best, ncc(area, t))
    return best


def rank(crop: np.ndarray, kind: str, top: int = 12) -> list[dict[str, Any]]:
    """Heroes ordered by how well the crop is found in their artwork. One entry per hero."""
    if crop is None or crop.size == 0:
        return []
    r = refs()
    g = gray(crop)
    q = trim(g)
    best: dict[str, tuple[float, str]] = {}
    for ref in r.learned:
        if ref.kind == kind:
            s = _search_learned(ref, g)
            if s > best.get(ref.hero, (-9, ""))[0]:
                best[ref.hero] = (s, "learned")
    if r.heroes:
        score, zoom = _search_sheet(r, q, widths(*ZOOM[kind]))
        second = []
        for i in np.argsort(-score)[:SHORTLIST[0]]:
            z = float(zoom[i]) or ZOOM[kind][0]
            s2, z2 = _search(r.small[i], q, widths(z / STEP ** 2, z * STEP ** 2, 1.035))
            second.append((s2, z2 or z, int(i)))
        second.sort(reverse=True)
        for n, (s, z, i) in enumerate(second):
            if n < SHORTLIST[1] and s > 0:
                s = max(s, _search(r.full[i], q, widths(z / 1.035, z * 1.035, 1.012))[0])
            if s > best.get(r.heroes[i], (-9, ""))[0]:
                best[r.heroes[i]] = (s, "seed")
    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:top]
    return decide_form(g, kind, [{"hero": h, "score": round(float(s), 3), "source": src} for h, (s, src) in ranked])


# ---------------------------------------------------------------- forms of one hero
@lru_cache(maxsize=1)
def families() -> dict[str, tuple[str, ...]]:
    """Hero id -> all forms of that hero. Forms are heroes named alike: "Flowborn (Carry)", "Flowborn (Mage)"."""
    groups: dict[str, list[str]] = {}
    for h in refdata.heroes():
        base, bracket, _ = h["name"].partition(" (")
        if bracket:
            groups.setdefault(base.strip().lower(), []).append(h["id"])
    return {hero: tuple(ids) for ids in groups.values() if len(ids) > 1 for hero in ids}


def badge_marks(g: np.ndarray) -> np.ndarray:
    """The white marks in the top right corner of a crop: pixels far brighter than their surroundings."""
    h, w = g.shape[:2]
    area = g[:max(2, int(h * BADGE_AREA[1])), int(w * BADGE_AREA[0]):]
    area = cv2.resize(area, (BADGE_WIDTH, max(8, int(BADGE_WIDTH * area.shape[0] / area.shape[1]))), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    return (((area - cv2.GaussianBlur(area, (0, 0), 25)) > 40) & (area > 150)).astype(np.float32)


def badge_shape(marks: np.ndarray) -> np.ndarray | None:
    """The largest mark, cut to its outline. None when the corner holds nothing badge-sized."""
    joined = cv2.dilate(marks.astype(np.uint8), np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in stats[i, :4])
    if w < BADGE_WIDTH * 0.2 or h < BADGE_WIDTH * 0.2:
        return None
    return (marks * (labels == i))[y:y + h, x:x + w]


@lru_cache(maxsize=1)
def badges() -> tuple[tuple[str, str, np.ndarray], ...]:
    """(hero, kind, badge) for every form that has a crop from a confirmed game. The seed art draws
    the badges differently from the broadcast, so it is no help here."""
    forms = families()
    out = []
    for ref in refs().learned:
        shape = badge_shape(badge_marks(ref.image)) if ref.hero in forms else None
        if shape is not None:
            out.append((ref.hero, ref.kind, shape))
    return tuple(out)


def _badge_score(marks: np.ndarray, shape: np.ndarray) -> float:
    best = 0.0
    for z in (0.8, 0.87, 0.94, 1.0, 1.06, 1.14, 1.22):
        tw, th = int(round(shape.shape[1] * z)), int(round(shape.shape[0] * z))
        if th >= marks.shape[0] or tw >= marks.shape[1]:
            continue
        t = (cv2.resize(shape, (tw, th), interpolation=cv2.INTER_AREA) > 0.4).astype(np.float32)
        best = max(best, float(cv2.matchTemplate(marks, t, cv2.TM_CCOEFF_NORMED).max()))
    return best


def decide_form(g: np.ndarray, kind: str, ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Settle which form of a hero a crop shows. The ranking comes back with one form at most.

    - A known badge is found: that form, whatever the artwork scored. No other hero carries a
      badge, so it also names the hero when the broadcast shows artwork no reference has.
    - A crop from a confirmed game says it is this hero but the badge is none of the known ones:
      the one form never seen before, as a guess.
    - Neither: no form at all. A wrong form would look as certain as the right one.
    """
    forms = families()
    if not forms:
        return ranking
    marks = badge_marks(g)
    score: dict[str, float] = {}
    for hero, its_kind, shape in badges():
        if its_kind == kind:
            score[hero] = max(score.get(hero, 0.0), _badge_score(marks, shape))
    ordered = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    lead = next((m for m in ranking if m["hero"] in forms), None)
    found = None
    if ordered and ordered[0][1] >= BADGE and ordered[0][1] - (ordered[1][1] if len(ordered) > 1 else 0.0) >= BADGE_GAP:
        hero, s = ordered[0]
        art = max((m["score"] for m in ranking if m["hero"] in forms[hero]), default=0.0)
        found = {"hero": hero, "score": round(max(s, art), 3), "source": "badge"}
    elif lead is not None and lead is ranking[0] and lead["source"] == "learned" and lead["score"] >= CONFIDENT:
        unseen = [h for h in forms[lead["hero"]] if h not in score]
        if score and len(unseen) == 1:
            found = {"hero": unseen[0], "score": round(min(lead["score"], CONFIDENT - 0.01), 3), "source": "badge"}
    if found is None and lead is None:
        return ranking
    members = set(forms[(found or lead)["hero"]])
    rest = [m for m in ranking if m["hero"] not in members]
    return sorted(rest + ([found] if found else []), key=lambda m: m["score"], reverse=True)


def rank_many(crops: list[np.ndarray | None], kind: str, top: int = 12) -> list[list[dict[str, Any]]]:
    """rank() for several crops at once."""
    refs()
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda c: rank(c, kind, top) if c is not None else [], crops))


def merge(*rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Two views of the same slot (draft bar and post-game header): keep the better score per hero."""
    best: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for m in ranking or []:
            if m["score"] > best.get(m["hero"], {"score": -9})["score"]:
                best[m["hero"]] = m
    return sorted(best.values(), key=lambda m: m["score"], reverse=True)


def assign(slots: list[dict[str, Any]]) -> None:
    """Give every hero to at most one slot, best matches first.

    Each slot is {"ranking": [...], "banned": set of hero ids it may not take}. The function adds
    hero, score, margin, confident and candidates to every slot. A slot whose best free hero is not
    plausible stays empty: an empty field asks for your choice, a wrong name hides the problem.
    """
    pairs = sorted(((m["score"], i, m["hero"]) for i, s in enumerate(slots) for m in s.get("ranking") or []
                    if m["hero"] not in (s.get("banned") or ())), reverse=True)
    taken: dict[str, int] = {}
    chosen: dict[int, tuple[str, float]] = {}
    for score, i, hero in pairs:
        if i in chosen or hero in taken or score < PLAUSIBLE:
            continue
        chosen[i] = (hero, score)
        taken[hero] = i
    for i, s in enumerate(slots):
        free = [m for m in s.get("ranking") or [] if taken.get(m["hero"], i) == i and m["hero"] not in (s.get("banned") or ())]
        s["candidates"] = free[:5]
        hero, score = chosen.get(i, (None, 0.0))
        rest = max((m["score"] for m in free if m["hero"] != hero), default=0.0)
        margin = score - rest
        if hero is not None and margin < PLAUSIBLE_MARGIN:
            taken.pop(hero, None)
            hero = None
        source = next((m.get("source") for m in free if m["hero"] == hero), None)
        s.update({"hero": hero, "score": round(score, 3) if hero else None, "margin": round(margin, 3) if hero else None,
                  "source": source, "confident": bool(hero and score >= CONFIDENT and margin >= MARGIN)})
