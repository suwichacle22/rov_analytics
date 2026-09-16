"""Map zones as polygons in normalised minimap coordinates (0..1, y down).

The default layout is an approximation of the Arena of Valor map with blue base at the
bottom-left and red base at the top-right. Tune it with `rov zones-preview`, which draws
the polygons over a real minimap frame.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Zone:
    name: str
    polygon: list[list[float]]  # [[x, y], ...] normalised


def default_zones() -> list[Zone]:
    # Coordinates are rough. The diagonal from bottom-left to top-right is mid lane.
    return [
        Zone("blue_base", [[0.00, 0.80], [0.20, 0.80], [0.20, 1.00], [0.00, 1.00]]),
        Zone("red_base", [[0.80, 0.00], [1.00, 0.00], [1.00, 0.20], [0.80, 0.20]]),
        # Top lane runs up the left edge then along the top edge.
        Zone("top_lane_blue", [[0.00, 0.35], [0.14, 0.35], [0.14, 0.80], [0.00, 0.80]]),
        Zone("top_lane_mid", [[0.00, 0.00], [0.35, 0.00], [0.14, 0.14], [0.00, 0.35]]),
        Zone("top_lane_red", [[0.35, 0.00], [0.80, 0.00], [0.80, 0.14], [0.35, 0.14]]),
        # Bottom lane runs along the bottom edge then up the right edge.
        Zone("bot_lane_blue", [[0.20, 0.86], [0.65, 0.86], [0.65, 1.00], [0.20, 1.00]]),
        Zone("bot_lane_mid", [[0.65, 0.86], [1.00, 0.65], [1.00, 1.00], [0.65, 1.00]]),
        Zone("bot_lane_red", [[0.86, 0.20], [1.00, 0.20], [1.00, 0.65], [0.86, 0.65]]),
        # Mid lane is a band along the main diagonal.
        Zone("mid_lane_blue", [[0.20, 0.72], [0.28, 0.80], [0.46, 0.62], [0.38, 0.54]]),
        Zone("mid_lane_center", [[0.38, 0.54], [0.46, 0.62], [0.62, 0.46], [0.54, 0.38]]),
        Zone("mid_lane_red", [[0.54, 0.38], [0.62, 0.46], [0.80, 0.28], [0.72, 0.20]]),
        # River band along the anti-diagonal, with objective pits at each end.
        Zone("dark_slayer_pit", [[0.14, 0.14], [0.30, 0.14], [0.30, 0.30], [0.14, 0.30]]),
        Zone("abyssal_dragon_pit", [[0.70, 0.70], [0.86, 0.70], [0.86, 0.86], [0.70, 0.86]]),
        Zone("river", [[0.30, 0.22], [0.38, 0.30], [0.70, 0.62], [0.62, 0.70], [0.30, 0.38], [0.22, 0.30]]),
        # Jungle quadrants: blue-side top (left), blue-side bottom, red-side top, red-side bottom.
        Zone("jungle_blue_top", [[0.14, 0.30], [0.30, 0.38], [0.38, 0.54], [0.20, 0.72], [0.14, 0.80]]),
        Zone("jungle_blue_bot", [[0.28, 0.80], [0.46, 0.62], [0.62, 0.70], [0.70, 0.86], [0.65, 0.86], [0.20, 0.86]]),
        Zone("jungle_red_top", [[0.35, 0.14], [0.80, 0.14], [0.80, 0.20], [0.72, 0.20], [0.54, 0.38], [0.38, 0.30], [0.30, 0.14]]),
        Zone("jungle_red_bot", [[0.62, 0.46], [0.80, 0.28], [0.86, 0.20], [0.86, 0.65], [0.70, 0.70]]),
    ]


def save_zones(zones: list[Zone], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"name": z.name, "polygon": z.polygon} for z in zones], indent=2), encoding="utf-8")


def load_zones(path: str | Path | None) -> list[Zone]:
    if path is None:
        return default_zones()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Zone(d["name"], d["polygon"]) for d in data]


class ZoneIndex:
    def __init__(self, zones: list[Zone]) -> None:
        self.zones = zones
        self._contours = [np.array(z.polygon, dtype=np.float32).reshape(-1, 1, 2) for z in zones]

    def lookup(self, x: float | None, y: float | None) -> str:
        if x is None or y is None:
            return ""
        for zone, contour in zip(self.zones, self._contours):
            if cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0:
                return zone.name
        return "unzoned"

    def draw(self, image: np.ndarray, label: bool = True) -> np.ndarray:
        out = image.copy()
        h, w = out.shape[:2]
        for zone in self.zones:
            pts = np.array([[int(x * w), int(y * h)] for x, y in zone.polygon], dtype=np.int32)
            cv2.polylines(out, [pts], True, (255, 255, 255), 1, cv2.LINE_AA)
            if label:
                cx, cy = pts.mean(axis=0).astype(int)
                cv2.putText(out, zone.name, (int(cx) - 20, int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1, cv2.LINE_AA)
        return out
