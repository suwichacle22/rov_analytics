"""Interactive helpers: pick the minimap box, sample ring colours, crop a hero template."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .config import HsvRange, SourceConfig


def select_box(image: np.ndarray, title: str, max_display: int = 1280) -> list[int]:
    """Let the user drag a rectangle. Returns [x, y, w, h] in original pixels."""
    h, w = image.shape[:2]
    scale = min(1.0, max_display / max(h, w))
    shown = cv2.resize(image, (int(w * scale), int(h * scale))) if scale < 1 else image
    x, y, bw, bh = cv2.selectROI(title, shown, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    if bw == 0 or bh == 0:
        raise ValueError("no box selected")
    return [int(x / scale), int(y / scale), int(bw / scale), int(bh / scale)]


def pick_points(image: np.ndarray, title: str, count: int, scale: int = 1) -> list[tuple[int, int]]:
    """Collect `count` clicks. Returns points in original pixels."""
    shown = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST) if scale > 1 else image.copy()
    clicks: list[tuple[int, int]] = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < count:
            clicks.append((x // scale, y // scale))
            cv2.circle(shown, (x, y), 4, (255, 255, 255), 1)
            cv2.imshow(title, shown)

    cv2.imshow(title, shown)
    cv2.setMouseCallback(title, on_mouse)
    while len(clicks) < count:
        if cv2.waitKey(30) & 0xFF in (27, ord("q")):
            break
    cv2.destroyWindow(title)
    return clicks


def hsv_range_around(image: np.ndarray, point: tuple[int, int], radius: int = 1, hue_tol: int = 12) -> list[HsvRange]:
    """Build HSV range(s) around the colour at a clicked point. Handles red hue wrap."""
    x, y = point
    patch = image[max(0, y - radius) : y + radius + 1, max(0, x - radius) : x + radius + 1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    h, s, v = (int(c) for c in np.median(hsv, axis=0))
    s_lo, v_lo = max(0, int(s * 0.55)), max(0, int(v * 0.55))
    lo, hi = h - hue_tol, h + hue_tol
    ranges = []
    if lo < 0:
        ranges.append(HsvRange([0, s_lo, v_lo], [hi, 255, 255]))
        ranges.append(HsvRange([180 + lo, s_lo, v_lo], [179, 255, 255]))
    elif hi > 179:
        ranges.append(HsvRange([lo, s_lo, v_lo], [179, 255, 255]))
        ranges.append(HsvRange([0, s_lo, v_lo], [hi - 180, 255, 255]))
    else:
        ranges.append(HsvRange([lo, s_lo, v_lo], [hi, 255, 255]))
    return ranges


def calibrate_interactive(frame: np.ndarray, name: str, sample_rings: bool = True) -> SourceConfig:
    print("1) Drag a box around the MINIMAP, then press ENTER or SPACE.")
    box = select_box(frame, "Select minimap")
    x, y, w, h = box
    minimap = frame[y : y + h, x : x + w]

    print("2) Drag a box tightly around ONE hero icon (ring included), then press ENTER.")
    ix, iy, iw, ih = select_box(minimap, "Select one hero icon", max_display=900)
    icon_diameter = int(round((iw + ih) / 2))

    cfg = SourceConfig(name=name, minimap_box=box, icon_diameter_px=icon_diameter)
    if sample_rings:
        print("3) Click ONE pixel on a BLUE team ring, then ONE pixel on a RED team ring. (q to keep defaults)")
        pts = pick_points(minimap, "Click blue ring, then red ring", count=2, scale=4)
        if len(pts) == 2:
            cfg.ring_ranges = {
                "blue": hsv_range_around(minimap, pts[0]),
                "red": hsv_range_around(minimap, pts[1]),
            }
    return cfg


def crop_template_interactive(minimap: np.ndarray) -> np.ndarray:
    print("Drag a box tightly around the hero icon (ring included), then press ENTER.")
    x, y, w, h = select_box(minimap, "Select hero icon", max_display=900)
    return minimap[y : y + h, x : x + w].copy()


def save_template(template: np.ndarray, templates_dir: str | Path, hero: str, source_name: str) -> Path:
    """Templates are keyed by hero only. A hero's minimap face is the same on either side."""
    out = Path(templates_dir) / source_name / f"{_slug(hero)}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), template)
    return out


def template_path(templates_dir: str | Path, hero: str, source_name: str, side: str | None = None) -> Path:
    """Resolve the template for a hero. Falls back to the old `<hero>_<side>.png` naming."""
    base = Path(templates_dir) / source_name
    candidates = [base / f"{_slug(hero)}.png"]
    if side:
        candidates.append(base / f"{_slug(hero)}_{side}.png")
    for c in candidates:
        if c.exists():
            return c
    known = sorted(p.stem for p in base.glob("*.png")) if base.exists() else []
    raise FileNotFoundError(
        f"no template for hero '{hero}' in {base}. Known templates: {known}. "
        f"Create one with: rov template <video> --source <config> --hero {hero} --time <sec>"
    )


def _slug(name: str) -> str:
    return "".join(ch for ch in name.strip().lower().replace(" ", "_") if ch.isalnum() or ch in "_-")
