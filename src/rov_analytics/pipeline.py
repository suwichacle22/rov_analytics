"""End-to-end: video + source config + hero template -> track rows, summary, images."""

from __future__ import annotations

from pathlib import Path

import cv2

from . import analytics, render
from .calibrate import template_path
from .config import SourceConfig
from .detect import IconDetector, load_template
from .track import Tracker
from .video import clean_background, crop_box, iter_frames, read_frame_at
from .zones import load_zones


def track_video(
    video: str | Path,
    source: SourceConfig,
    hero: str,
    side: str,
    templates_dir: str | Path,
    out_csv: str | Path,
    match_id: str = "",
    player: str = "",
    sample_fps: float = 2.0,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    game_start_sec: float | None = None,
    zones_path: str | Path | None = None,
    min_score: float = 0.55,
    debug_video: str | Path | None = None,
    progress: bool = True,
) -> tuple[list[analytics.TrackRow], dict]:
    tpl_path = template_path(templates_dir, hero, source.name, side)
    template = load_template(tpl_path)
    detector = IconDetector(template, source, side, min_score=min_score)
    tracker = Tracker(sample_fps=sample_fps)
    zones = load_zones(zones_path)
    match_id = match_id or Path(video).stem

    debug = render.DebugVideo(debug_video, source.crop_size, sample_fps) if debug_video else None
    points = []
    n = 0
    for frame in iter_frames(video, sample_fps, start_sec, end_sec, game_start_sec):
        minimap = crop_box(frame.image, source.minimap_box)
        det = detector.detect(minimap)
        pt = tracker.update(det, frame.game_sec, frame.video_sec)
        points.append(pt)
        if debug:
            debug.write(minimap, pt.x_norm, pt.y_norm, pt.score, pt.status, pt.game_sec)
        n += 1
        if progress and n % 100 == 0:
            print(f"  {n} samples, game time {pt.game_sec:6.1f}s, last status {pt.status}")
    if debug:
        debug.close()

    rows = analytics.rows_from_track(points, zones, match_id, side, hero, player)
    analytics.write_csv(rows, out_csv)
    summary = analytics.summarize(rows, sample_fps)
    analytics.write_summary(summary, Path(out_csv).with_suffix(".summary.json"))
    return rows, summary


DEFAULT_PHASES: list[tuple[float, float | None]] = [(0, 240), (240, 480), (480, 900), (900, None)]


def parse_phases(text: str) -> list[tuple[float, float | None]]:
    """'0-4,4-8,8-15,15-' in minutes -> [(0,240),(240,480),(480,900),(900,None)]."""
    out = []
    for part in text.split(","):
        a, b = part.strip().split("-")
        out.append((float(a) * 60, float(b) * 60 if b.strip() else None))
    return out


def render_phases(
    rows: list[analytics.TrackRow],
    video: str | Path,
    source: SourceConfig,
    out_dir: str | Path,
    phases: list[tuple[float, float | None]] | None = None,
    bins: int = 64,
    sample_fps: float = 2.0,
) -> dict:
    """One temperature heatmap per game-time window, plus a combined sheet and per-phase stats."""
    import numpy as np

    phases = phases or DEFAULT_PHASES
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    valid_rows = [r for r in rows if r.x_norm is not None]
    if not valid_rows:
        raise ValueError("track has no positions")
    v0, v1 = min(r.video_sec for r in valid_rows), max(r.video_sec for r in valid_rows)
    background = clean_background(video, source.minimap_box, start_sec=v0, end_sec=v1)
    stem = f"{rows[0].match_id}_{rows[0].hero.lower()}"
    who = rows[0].player or rows[0].hero
    game_end = max(r.game_sec for r in rows)

    images, stats = [], {}
    for lo, hi in phases:
        hi_eff = hi if hi is not None else game_end
        sel = [r for r in rows if lo <= r.game_sec < hi_eff + 1e-6]
        label = f"{int(lo)//60}:{int(lo)%60:02d} - {int(hi_eff)//60}:{int(hi_eff)%60:02d}"
        grid = analytics.heatmap_grid(sel, bins=bins)
        tracked = sum(1 for r in sel if r.x_norm is not None) / sample_fps
        img = render.heatmap_image(background, grid, title=f"{who}  {label}", subtitle=f"{rows[0].match_id}   {tracked:.0f}s tracked")
        name = f"{stem}_phase_{int(lo)//60:02d}-{int(hi_eff)//60:02d}.png"
        cv2.imwrite(str(out_dir / name), img)
        images.append(img)
        s = analytics.summarize(sel, sample_fps)
        stats[label] = {"tracked_seconds": s["tracked_seconds"], "zone_changes_per_min": s["zone_changes_per_min"],
                        "top_zones": dict(list(s["dwell_seconds"].items())[:5])}

    # 2-column sheet
    h = max(i.shape[0] for i in images)
    w = max(i.shape[1] for i in images)
    padded = [cv2.copyMakeBorder(i, 0, h - i.shape[0], 0, w - i.shape[1], cv2.BORDER_CONSTANT, value=(16, 16, 16)) for i in images]
    while len(padded) % 2:
        padded.append(np.full((h, w, 3), 16, dtype=np.uint8))
    sheet_rows = [np.hstack(padded[i : i + 2]) for i in range(0, len(padded), 2)]
    sheet = np.vstack(sheet_rows)
    sheet_path = out_dir / f"{stem}_phases.png"
    cv2.imwrite(str(sheet_path), sheet)
    return {"sheet": sheet_path, "stats": stats}


def render_outputs(
    rows: list[analytics.TrackRow],
    video: str | Path,
    source: SourceConfig,
    out_dir: str | Path,
    background_sec: float = 0.0,
    bins: int = 64,
    stem: str | None = None,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    valid_rows = [r for r in rows if r.x_norm is not None]
    if valid_rows:
        v0, v1 = min(r.video_sec for r in valid_rows), max(r.video_sec for r in valid_rows)
        background = clean_background(video, source.minimap_box, start_sec=max(background_sec, v0), end_sec=v1)
    else:
        background = crop_box(read_frame_at(video, background_sec), source.minimap_box)
    grid = analytics.heatmap_grid(rows, bins=bins)
    valid = [r for r in rows if r.x_norm is not None]
    if rows:
        who = rows[0].player or rows[0].hero
        t0, t1 = min(r.game_sec for r in rows), max(r.game_sec for r in rows)
        title = f"{who}  ({rows[0].hero}, {rows[0].side})"
        subtitle = f"{rows[0].match_id}   {int(t0)//60}:{int(t0)%60:02d} - {int(t1)//60}:{int(t1)%60:02d}   {len(valid)/2:.0f}s tracked"
    else:
        title = subtitle = ""
    heat = render.heatmap_image(background, grid, title=title, subtitle=subtitle)
    path = render.path_image(background, rows)
    if stem is None:
        stem = f"{rows[0].match_id}_{rows[0].hero.lower()}" if rows else Path(video).stem
    outputs = {
        "heatmap": out_dir / f"{stem}_heatmap.png",
        "path": out_dir / f"{stem}_path.png",
    }
    cv2.imwrite(str(outputs["heatmap"]), heat)
    cv2.imwrite(str(outputs["path"]), path)
    return outputs
