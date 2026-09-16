"""End-to-end: video + source config + hero template -> track rows, summary, images."""

from __future__ import annotations

from pathlib import Path

import cv2

from . import analytics, render
from .calibrate import template_path
from .config import SourceConfig
from .detect import IconDetector, load_template
from .track import Tracker
from .video import crop_box, iter_frames, read_frame_at
from .zones import ZoneIndex, load_zones


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
    tpl_path = template_path(templates_dir, hero, side, source.name)
    template = load_template(tpl_path)
    detector = IconDetector(template, source, side, min_score=min_score)
    tracker = Tracker(sample_fps=sample_fps)
    zones = ZoneIndex(load_zones(zones_path))
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


def render_outputs(
    rows: list[analytics.TrackRow],
    video: str | Path,
    source: SourceConfig,
    out_dir: str | Path,
    background_sec: float = 0.0,
    bins: int = 64,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    background = crop_box(read_frame_at(video, background_sec), source.minimap_box)
    grid = analytics.heatmap_grid(rows, bins=bins)
    heat = render.heatmap_image(background, grid)
    path = render.path_image(background, rows)
    stem = rows[0].match_id if rows else Path(video).stem
    outputs = {
        "heatmap": out_dir / f"{stem}_heatmap.png",
        "path": out_dir / f"{stem}_path.png",
    }
    cv2.imwrite(str(outputs["heatmap"]), heat)
    cv2.imwrite(str(outputs["path"]), path)
    return outputs
