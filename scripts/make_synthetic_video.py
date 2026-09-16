"""Generate a fake broadcast video with a minimap and moving hero icons.

Used to test the pipeline end to end without a real VOD. The "jungler" walks a known
route so the resulting track can be checked against ground truth.

Usage: python scripts/make_synthetic_video.py data/synthetic/game.mp4 --seconds 60
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np

FRAME_W, FRAME_H = 1280, 720
MINIMAP = (20, 480, 220, 220)  # x, y, w, h  (bottom-left like a broadcast)
ICON_R = 9                      # icon radius in minimap px (diameter 18 + 2px ring)
FPS = 30


def hero_icon(seed: int, ring_bgr: tuple[int, int, int], size: int) -> np.ndarray:
    """A round 'portrait' with a distinctive random texture and a coloured ring."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    face = rng.integers(40, 220, size=(4, 4, 3), dtype=np.uint8)
    face = cv2.resize(face, (size, size), interpolation=cv2.INTER_NEAREST)
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(mask, (size // 2, size // 2), size // 2 - 2, 255, -1)
    img[mask > 0] = face[mask > 0]
    cv2.circle(img, (size // 2, size // 2), size // 2 - 1, ring_bgr, 2, cv2.LINE_AA)
    return img, mask


def paste(dst: np.ndarray, icon: np.ndarray, mask: np.ndarray, cx: int, cy: int) -> None:
    s = icon.shape[0]
    x0, y0 = cx - s // 2, cy - s // 2
    h, w = dst.shape[:2]
    if x0 < 0 or y0 < 0 or x0 + s > w or y0 + s > h:
        return
    ring = np.zeros_like(mask)
    cv2.circle(ring, (s // 2, s // 2), s // 2 - 1, 255, 2)
    m = (mask | ring) > 0
    dst[y0 : y0 + s, x0 : x0 + s][m] = icon[m]


def jungler_route(t: float) -> tuple[float, float]:
    """Normalised position over time: blue jungle clear, then a gank top, then recall."""
    waypoints = [
        (0.0, (0.10, 0.90)),   # base
        (6.0, (0.25, 0.70)),   # blue jungle camp 1
        (12.0, (0.20, 0.55)),  # camp 2
        (18.0, (0.33, 0.60)),  # camp 3
        (26.0, (0.15, 0.35)),  # walk to top lane
        (32.0, (0.10, 0.25)),  # gank top
        (38.0, (0.10, 0.25)),  # stay in fight
        (38.5, (0.10, 0.90)),  # recall (teleport)
        (46.0, (0.35, 0.80)),  # bottom jungle
        (54.0, (0.55, 0.60)),  # river
        (60.0, (0.70, 0.75)),  # dragon pit
    ]
    if t <= waypoints[0][0]:
        return waypoints[0][1]
    for (t0, p0), (t1, p1) in zip(waypoints, waypoints[1:]):
        if t0 <= t <= t1:
            a = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return (p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a)
    return waypoints[-1][1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=60.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    size = ICON_R * 2 + 2
    blue, red = (200, 90, 30), (30, 40, 220)  # BGR
    jungler, jmask = hero_icon(1, blue, size)
    others = [hero_icon(s, blue, size) for s in range(2, 6)] + [hero_icon(s, red, size) for s in range(6, 11)]
    rng = random.Random(0)
    other_pos = [(rng.uniform(0.15, 0.85), rng.uniform(0.15, 0.85)) for _ in others]
    other_vel = [(rng.uniform(-0.01, 0.01), rng.uniform(-0.01, 0.01)) for _ in others]

    # Static minimap background: dark green with lanes drawn.
    mx, my, mw, mh = MINIMAP
    bg = np.full((mh, mw, 3), (35, 60, 35), dtype=np.uint8)
    cv2.line(bg, (0, mh), (mw, 0), (60, 90, 60), 6)
    cv2.line(bg, (0, mh), (0, 0), (60, 90, 60), 6)
    cv2.line(bg, (0, 0), (mw, 0), (60, 90, 60), 6)
    cv2.line(bg, (0, mh), (mw, mh), (60, 90, 60), 6)
    cv2.line(bg, (mw, mh), (mw, 0), (60, 90, 60), 6)
    cv2.line(bg, (0, 0), (mw, mh), (40, 70, 90), 4)  # river

    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (FRAME_W, FRAME_H))
    truth = []
    n = int(args.seconds * FPS)
    for i in range(n):
        t = i / FPS
        frame = np.full((FRAME_H, FRAME_W, 3), (20, 20, 20), dtype=np.uint8)
        cv2.putText(frame, f"SYNTHETIC BROADCAST {int(t//60):02d}:{int(t%60):02d}", (400, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        mm = bg.copy()
        # Occasional ping (a ring of the team colour with no face) as a distractor.
        if int(t * 2) % 7 == 0:
            cv2.circle(mm, (int(mw * 0.5), int(mh * 0.5)), ICON_R + 3, blue, 2)
        for k, ((icon, mask), (px, py), (vx, vy)) in enumerate(zip(others, other_pos, other_vel)):
            px, py = px + vx, py + vy
            if not 0.05 < px < 0.95: vx = -vx
            if not 0.05 < py < 0.95: vy = -vy
            other_pos[k], other_vel[k] = (px, py), (vx, vy)
            paste(mm, icon, mask, int(px * mw), int(py * mh))
        jx, jy = jungler_route(t)
        paste(mm, jungler, jmask, int(jx * mw), int(jy * mh))
        frame[my : my + mh, mx : mx + mw] = mm
        # Broadcast overlay covering the minimap for 2 seconds at t=50.
        if 50.0 <= t < 52.0:
            cv2.rectangle(frame, (0, 440), (400, 720), (10, 10, 10), -1)
            cv2.putText(frame, "REPLAY", (60, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        writer.write(frame)
        truth.append({"t": round(t, 3), "x": round(jx, 4), "y": round(jy, 4)})
    writer.release()

    with out.with_suffix(".truth.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t", "x", "y"])
        w.writeheader()
        w.writerows(truth)
    meta = {"minimap_box": list(MINIMAP), "icon_diameter_px": size, "fps": FPS}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {out}, truth CSV and meta JSON")


if __name__ == "__main__":
    main()
