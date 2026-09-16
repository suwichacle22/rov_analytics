"""Find one known hero icon inside a minimap crop.

Method: normalised cross-correlation of the hero template over the whole minimap,
restricted to places where the team ring colour is present. Cheap, no training, and
works because we already know which hero and which side we are looking for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import HsvRange, SourceConfig


@dataclass
class Detection:
    found: bool
    x_px: float           # centre in minimap crop pixels
    y_px: float
    x_norm: float         # centre normalised to 0..1 of the crop
    y_norm: float
    score: float          # template match score, -1..1
    ring_pixels: int      # how many team-colour pixels were under the icon


def load_template(path: str | Path) -> np.ndarray:
    tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if tpl is None:
        raise FileNotFoundError(f"template not found: {path}")
    return tpl


def ring_mask(minimap: np.ndarray, ranges: list[HsvRange]) -> np.ndarray:
    """Binary mask of pixels matching any of the team ring HSV ranges."""
    hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
    mask = np.zeros(minimap.shape[:2], dtype=np.uint8)
    for r in ranges:
        mask |= cv2.inRange(hsv, np.array(r.low, dtype=np.uint8), np.array(r.high, dtype=np.uint8))
    return mask


class IconDetector:
    def __init__(
        self,
        template: np.ndarray,
        source: SourceConfig,
        side: str,
        min_score: float = 0.55,
        min_ring_pixels: int = 6,
    ) -> None:
        self.template = template
        self.source = source
        self.side = side
        self.min_score = min_score
        self.min_ring_pixels = min_ring_pixels
        self.ranges = source.ring_ranges[side]
        th, tw = template.shape[:2]
        # A ring-presence kernel the size of the icon, used to count team pixels per location.
        self._ring_kernel = np.ones((th, tw), dtype=np.float32)

    def detect(self, minimap: np.ndarray) -> Detection:
        th, tw = self.template.shape[:2]
        h, w = minimap.shape[:2]
        if h < th or w < tw:
            return Detection(False, 0, 0, 0, 0, -1.0, 0)

        scores = cv2.matchTemplate(minimap, self.template, cv2.TM_CCOEFF_NORMED)

        # Count team-colour pixels inside every candidate window of template size.
        mask = ring_mask(minimap, self.ranges).astype(np.float32)
        ring_counts = cv2.filter2D(mask, -1, self._ring_kernel, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        ring_counts = ring_counts[: scores.shape[0], : scores.shape[1]]

        gated = np.where(ring_counts >= self.min_ring_pixels, scores, -1.0)
        _, best, _, loc = cv2.minMaxLoc(gated)
        if best < self.min_score:
            # Report the ungated best so the caller can see how close we were.
            _, raw_best, _, raw_loc = cv2.minMaxLoc(scores)
            cx, cy = raw_loc[0] + tw / 2, raw_loc[1] + th / 2
            return Detection(False, cx, cy, cx / w, cy / h, float(raw_best), int(ring_counts[raw_loc[1], raw_loc[0]]))

        cx, cy = loc[0] + tw / 2, loc[1] + th / 2
        return Detection(True, cx, cy, cx / w, cy / h, float(best), int(ring_counts[loc[1], loc[0]]))
