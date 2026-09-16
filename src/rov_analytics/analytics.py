"""Analytics on a track: heatmap grid, zone dwell time, distance, rotations."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .track import TrackPoint
from .zones import ZoneIndex

CSV_FIELDS = ["match_id", "game_sec", "video_sec", "side", "hero", "player", "x_norm", "y_norm", "zone", "score", "status"]


@dataclass
class TrackRow:
    match_id: str
    game_sec: float
    video_sec: float
    side: str
    hero: str
    player: str
    x_norm: float | None
    y_norm: float | None
    zone: str
    score: float
    status: str


def rows_from_track(
    points: list[TrackPoint], zones: ZoneIndex, match_id: str, side: str, hero: str, player: str
) -> list[TrackRow]:
    return [
        TrackRow(
            match_id, round(p.game_sec, 3), round(p.video_sec, 3), side, hero, player,
            None if p.x_norm is None else round(p.x_norm, 4),
            None if p.y_norm is None else round(p.y_norm, 4),
            zones.lookup(p.x_norm, p.y_norm), round(p.score, 4), p.status,
        )
        for p in points
    ]


def write_csv(rows: list[TrackRow], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            d["x_norm"] = "" if d["x_norm"] is None else d["x_norm"]
            d["y_norm"] = "" if d["y_norm"] is None else d["y_norm"]
            w.writerow(d)


def read_csv(path: str | Path) -> list[TrackRow]:
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            rows.append(
                TrackRow(
                    d["match_id"], float(d["game_sec"]), float(d["video_sec"]), d["side"], d["hero"], d["player"],
                    float(d["x_norm"]) if d["x_norm"] else None,
                    float(d["y_norm"]) if d["y_norm"] else None,
                    d["zone"], float(d["score"]), d["status"],
                )
            )
    return rows


def _valid(rows: list[TrackRow], min_sec: float | None = None, max_sec: float | None = None) -> list[TrackRow]:
    out = []
    for r in rows:
        if r.x_norm is None or r.y_norm is None:
            continue
        if min_sec is not None and r.game_sec < min_sec:
            continue
        if max_sec is not None and r.game_sec > max_sec:
            continue
        out.append(r)
    return out


def heatmap_grid(rows: list[TrackRow], bins: int = 64, min_sec: float | None = None, max_sec: float | None = None) -> np.ndarray:
    """Counts per cell, shape (bins, bins), indexed [row=y, col=x]."""
    grid = np.zeros((bins, bins), dtype=np.float32)
    for r in _valid(rows, min_sec, max_sec):
        cx = min(bins - 1, max(0, int(r.x_norm * bins)))
        cy = min(bins - 1, max(0, int(r.y_norm * bins)))
        grid[cy, cx] += 1
    return grid


def summarize(rows: list[TrackRow], sample_fps: float) -> dict:
    valid = _valid(rows)
    dt = 1.0 / sample_fps
    dwell: dict[str, float] = {}
    for r in valid:
        dwell[r.zone] = dwell.get(r.zone, 0.0) + dt

    distance = 0.0
    zone_changes = 0
    prev = None
    for r in valid:
        if prev is not None:
            distance += ((r.x_norm - prev.x_norm) ** 2 + (r.y_norm - prev.y_norm) ** 2) ** 0.5
            if r.zone != prev.zone and r.zone and prev.zone:
                zone_changes += 1
        prev = r

    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    tracked_sec = len(valid) * dt
    minutes = tracked_sec / 60.0 if tracked_sec else 0.0
    return {
        "samples": len(rows),
        "tracked_seconds": round(tracked_sec, 1),
        "coverage": round(len(valid) / len(rows), 3) if rows else 0.0,
        "status_counts": status_counts,
        "distance_map_units": round(distance, 3),
        "zone_changes": zone_changes,
        "zone_changes_per_min": round(zone_changes / minutes, 2) if minutes else 0.0,
        "dwell_seconds": {k: round(v, 1) for k, v in sorted(dwell.items(), key=lambda kv: -kv[1])},
    }


def write_summary(summary: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
