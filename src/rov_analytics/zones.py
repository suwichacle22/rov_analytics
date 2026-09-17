"""Map zones in normalised minimap coordinates (0..1, y down).

Two ways to define zones:

1. Geometric (default). The Arena of Valor map is a square with blue base bottom-left and
   red base top-right. Mid lane is the main diagonal, the river is the anti-diagonal, the
   side lanes hug the edges. A few numbers describe all of it, and every point gets a zone.
2. Polygon JSON, for hand-drawn overrides (`rov zones-init` writes a starting file).

Check either with `rov zones-preview`, which paints the zones over a real minimap frame.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

SQRT2 = math.sqrt(2.0)


@dataclass
class GeometricZones:
    """Parameters are fractions of the minimap width. Tune against `rov zones-preview`."""

    base_radius: float = 0.24          # corner distance (x + y style) that counts as base
    lane_band: float = 0.12            # width of the side-lane strips along the edges
    mid_band: float = 0.055            # half-width of the mid-lane band around the main diagonal
    river_band: float = 0.05           # half-width of the river band around the anti-diagonal
    river_span: tuple[float, float] = (0.22, 0.78)  # river only exists between these along the diagonal
    dark_slayer: tuple[float, float] = (0.335, 0.31)
    abyssal_dragon: tuple[float, float] = (0.67, 0.71)
    pit_radius: float = 0.085
    lane_split: tuple[float, float] = (0.75, 1.25)  # along-lane position (0..2) splitting blue/mid/red thirds
    mid_split: tuple[float, float] = (0.40, 0.60)   # along-mid position (0..1) splitting blue/center/red

    def classify(self, x: float, y: float) -> str:
        p = self
        # Bases: corners (0,1) blue and (1,0) red.
        if x + (1 - y) < p.base_radius:
            return "blue_base"
        if (1 - x) + y < p.base_radius:
            return "red_base"
        # Objective pits.
        if math.hypot(x - p.dark_slayer[0], y - p.dark_slayer[1]) < p.pit_radius:
            return "dark_slayer_pit"
        if math.hypot(x - p.abyssal_dragon[0], y - p.abyssal_dragon[1]) < p.pit_radius:
            return "abyssal_dragon_pit"
        # Side lanes: top lane = left edge then top edge; bot lane = bottom edge then right edge.
        if x < p.lane_band or y < p.lane_band:
            s = (1 - y) if x < p.lane_band else 1 + x  # 0 at blue base, 2 at red base
            return "top_lane_" + _third(s, p.lane_split)
        if y > 1 - p.lane_band or x > 1 - p.lane_band:
            s = x if y > 1 - p.lane_band else 1 + (1 - y)
            return "bot_lane_" + _third(s, p.lane_split)
        # Mid lane: main diagonal x + y = 1.
        if abs(x + y - 1) / SQRT2 < p.mid_band:
            t = (x + (1 - y)) / 2  # 0 at blue base, 1 at red base
            if t < p.mid_split[0]:
                return "mid_lane_blue"
            if t > p.mid_split[1]:
                return "mid_lane_red"
            return "mid_lane_center"
        # River: anti-diagonal y = x, only in the middle stretch.
        along = (x + y) / 2
        if abs(x - y) / SQRT2 < p.river_band and p.river_span[0] < along < p.river_span[1]:
            return "river"
        # Jungle: team half by the river line, top/bot by the mid line.
        side = "blue" if y > x else "red"
        part = "top" if x + y < 1 else "bot"
        return f"jungle_{side}_{part}"


def _third(s: float, split: tuple[float, float]) -> str:
    if s < split[0]:
        return "blue"
    if s > split[1]:
        return "red"
    return "mid"


@dataclass
class Zone:
    name: str
    polygon: list[list[float]]  # [[x, y], ...] normalised


def default_polygons() -> list[Zone]:
    """A coarse hand-drawn layout, exported by `rov zones-init` as a starting point for edits."""
    return [
        Zone("blue_base", [[0.00, 0.80], [0.20, 0.80], [0.20, 1.00], [0.00, 1.00]]),
        Zone("red_base", [[0.80, 0.00], [1.00, 0.00], [1.00, 0.20], [0.80, 0.20]]),
        Zone("top_lane_blue", [[0.00, 0.35], [0.12, 0.35], [0.12, 0.80], [0.00, 0.80]]),
        Zone("top_lane_mid", [[0.00, 0.00], [0.35, 0.00], [0.12, 0.12], [0.00, 0.35]]),
        Zone("top_lane_red", [[0.35, 0.00], [0.80, 0.00], [0.80, 0.12], [0.35, 0.12]]),
        Zone("bot_lane_blue", [[0.20, 0.88], [0.65, 0.88], [0.65, 1.00], [0.20, 1.00]]),
        Zone("bot_lane_mid", [[0.65, 0.88], [1.00, 0.65], [1.00, 1.00], [0.65, 1.00]]),
        Zone("bot_lane_red", [[0.88, 0.20], [1.00, 0.20], [1.00, 0.65], [0.88, 0.65]]),
        Zone("dark_slayer_pit", [[0.25, 0.22], [0.42, 0.22], [0.42, 0.40], [0.25, 0.40]]),
        Zone("abyssal_dragon_pit", [[0.58, 0.62], [0.76, 0.62], [0.76, 0.80], [0.58, 0.80]]),
    ]


def save_zones(zones: list[Zone], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"name": z.name, "polygon": z.polygon} for z in zones], indent=2), encoding="utf-8")


def load_zones(path: str | Path | None) -> "ZoneIndex":
    """None -> geometric default. JSON list -> polygons. JSON object -> geometric with overrides."""
    if path is None:
        return ZoneIndex(geometric=GeometricZones())
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        params = {k: (tuple(v) if isinstance(v, list) else v) for k, v in data.items()}
        return ZoneIndex(geometric=GeometricZones(**params))
    return ZoneIndex(polygons=[Zone(d["name"], d["polygon"]) for d in data], geometric=GeometricZones())


class ZoneIndex:
    """Polygons win where they exist; the geometric classifier fills everything else."""

    def __init__(self, polygons: list[Zone] | None = None, geometric: GeometricZones | None = None) -> None:
        self.polygons = polygons or []
        self.geometric = geometric
        self._contours = [np.array(z.polygon, dtype=np.float32).reshape(-1, 1, 2) for z in self.polygons]

    def lookup(self, x: float | None, y: float | None) -> str:
        if x is None or y is None:
            return ""
        for zone, contour in zip(self.polygons, self._contours):
            if cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0:
                return zone.name
        if self.geometric is not None:
            return self.geometric.classify(x, y)
        return "unzoned"

    def draw(self, image: np.ndarray, step: int = 2) -> np.ndarray:
        """Paint zone boundaries and labels over a minimap image."""
        h, w = image.shape[:2]
        labels = np.zeros((h // step, w // step), dtype=np.int32)
        names: dict[str, int] = {}
        for j in range(labels.shape[0]):
            for i in range(labels.shape[1]):
                name = self.lookup((i * step + step / 2) / w, (j * step + step / 2) / h)
                labels[j, i] = names.setdefault(name, len(names) + 1)
        big = cv2.resize(labels.astype(np.uint16), (w, h), interpolation=cv2.INTER_NEAREST).astype(np.int32)
        edge = np.zeros((h, w), dtype=np.uint8)
        edge[:, 1:] |= (big[:, 1:] != big[:, :-1]).astype(np.uint8)
        edge[1:, :] |= (big[1:, :] != big[:-1, :]).astype(np.uint8)
        out = image.copy()
        out[edge > 0] = (255, 255, 255)
        for name, idx in names.items():
            ys, xs = np.where(big == idx)
            if len(xs) == 0:
                continue
            cx, cy = int(xs.mean()), int(ys.mean())
            cv2.putText(out, name, (max(2, cx - 28), cy), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(out, name, (max(2, cx - 28), cy), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1, cv2.LINE_AA)
        return out
