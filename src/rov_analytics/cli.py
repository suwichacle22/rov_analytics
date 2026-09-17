"""Command line entry point: `rov <command> ...`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

from . import analytics, pipeline, render
from .calibrate import calibrate_interactive, crop_template_interactive, save_template
from .config import SourceConfig
from .match import MatchManifest, example_manifest
from .video import ClipMeta, crop_box, download, parse_timestamp, probe, read_frame_at
from .zones import default_polygons, load_zones, save_zones

DEFAULT_TEMPLATES = "templates"


def cmd_download(a: argparse.Namespace) -> None:
    start = parse_timestamp(a.start) if a.start else None
    end = parse_timestamp(a.end) if a.end else None
    if (start is not None) != (end is not None):
        raise ValueError("give both --from and --to, or neither")
    out = download(a.url, a.out, max_height=a.max_height, start_sec=start, end_sec=end, video_only=not a.audio)
    info = probe(out)
    print(f"saved {out}  ({info.width}x{info.height}, {info.fps:.2f} fps, {info.duration_sec/60:.1f} min)")
    meta = ClipMeta.load(out)
    if meta is not None:
        print(f"clip begins {meta.start_offset:.1f} s before the requested start. "
              f"If --from was the moment the clock read 0:00, track with --start 0 --game-start {meta.start_offset:.1f}")


def cmd_info(a: argparse.Namespace) -> None:
    info = probe(a.video)
    print(json.dumps({"path": str(info.path), "width": info.width, "height": info.height, "fps": info.fps,
                      "frames": info.frame_count, "duration_sec": round(info.duration_sec, 1)}, indent=2))


def cmd_calibrate(a: argparse.Namespace) -> None:
    frame = read_frame_at(a.video, a.time)
    if a.box:
        x, y, w, h = (int(v) for v in a.box.split(","))
        cfg = SourceConfig(name=a.name, minimap_box=[x, y, w, h], icon_diameter_px=a.icon_diameter)
    else:
        cfg = calibrate_interactive(frame, a.name, sample_rings=not a.default_rings)
    cfg.save(a.out)
    preview = crop_box(frame, cfg.minimap_box)
    preview_path = Path(a.out).with_suffix(".minimap.png")
    cv2.imwrite(str(preview_path), preview)
    print(f"saved {a.out}\nminimap preview: {preview_path}\n{cfg.to_json()}")


def cmd_template(a: argparse.Namespace) -> None:
    src = SourceConfig.load(a.source)
    frame = read_frame_at(a.video, a.time)
    minimap = crop_box(frame, src.minimap_box)
    if a.box:
        x, y, w, h = (int(v) for v in a.box.split(","))
        tpl = minimap[y : y + h, x : x + w].copy()
    else:
        tpl = crop_template_interactive(minimap)
    out = save_template(tpl, a.templates, a.hero, src.name)
    print(f"saved template {out}  ({tpl.shape[1]}x{tpl.shape[0]} px)")


def cmd_match_init(a: argparse.Namespace) -> None:
    m = example_manifest(Path(a.out).stem, a.video, a.source)
    m.game_start = a.game_start
    m.save(a.out)
    print(f"wrote {a.out}. Fill in player and hero names from the draft screen, then: rov track --match {a.out} --player <name>")


def _track_one(a: argparse.Namespace, video: str, src: SourceConfig, hero: str, side: str, player: str,
               match_id: str, game_start: float | None, end: float | None) -> None:
    out_csv = Path(a.out) if a.out else Path("data/tracks") / f"{match_id}_{hero.lower()}.csv"
    print(f"tracking {player or hero} as {hero} ({side}) in {video} at {a.fps} fps ...")
    rows, summary = pipeline.track_video(
        video, src, hero, side, a.templates, out_csv,
        match_id=match_id, player=player, sample_fps=a.fps,
        start_sec=a.start, end_sec=end, game_start_sec=game_start,
        zones_path=a.zones, min_score=a.min_score, debug_video=a.debug_video,
    )
    print(f"wrote {out_csv}")
    print(json.dumps(summary, indent=2))
    if not a.no_images:
        outs = pipeline.render_outputs(rows, video, src, out_csv.parent, background_sec=a.start, stem=out_csv.stem)
        for k, p in outs.items():
            print(f"{k}: {p}")


def cmd_track(a: argparse.Namespace) -> None:
    if a.match:
        m = MatchManifest.load(a.match)
        src = SourceConfig.load(m.source)
        end = a.end if a.end is not None else m.end
        game_start = a.game_start if a.game_start is not None else m.game_start
        if a.all:
            entries = list(m.players)
        elif a.player:
            entries = [m.find_player(a.player)]
        elif a.hero:
            entries = [m.find_hero(a.hero)]
        else:
            raise ValueError("with --match, give --player, --hero, or --all")
        if a.out and len(entries) > 1:
            raise ValueError("--out only works for a single hero")
        for e in entries:
            _track_one(a, m.video, src, e.hero, e.side, e.player, m.match_id, game_start, end)
        return

    if not (a.video and a.source and a.hero and a.side):
        raise ValueError("without --match, give VIDEO --source --hero --side")
    src = SourceConfig.load(a.source)
    match_id = a.match_id or Path(a.video).stem
    _track_one(a, a.video, src, a.hero, a.side, a.player, match_id, a.game_start, a.end)


def cmd_heatmap(a: argparse.Namespace) -> None:
    src = SourceConfig.load(a.source)
    rows = analytics.read_csv(a.track)
    if a.min_sec is not None or a.max_sec is not None:
        rows = [r for r in rows if (a.min_sec is None or r.game_sec >= a.min_sec) and (a.max_sec is None or r.game_sec <= a.max_sec)]
    outs = pipeline.render_outputs(rows, a.video, src, a.out_dir, background_sec=a.background_time, bins=a.bins)
    for k, p in outs.items():
        print(f"{k}: {p}")
    print(json.dumps(analytics.summarize(rows, a.fps), indent=2))


def cmd_phases(a: argparse.Namespace) -> None:
    src = SourceConfig.load(a.source)
    rows = analytics.read_csv(a.track)
    phases = pipeline.parse_phases(a.phases) if a.phases else None
    result = pipeline.render_phases(rows, a.video, src, a.out_dir, phases=phases, bins=a.bins, sample_fps=a.fps)
    print(f"sheet: {result['sheet']}")
    print(json.dumps(result["stats"], indent=2))


def cmd_rezone(a: argparse.Namespace) -> None:
    zones = load_zones(a.zones)
    for track in a.tracks:
        rows = analytics.read_csv(track)
        for r in rows:
            r.zone = zones.lookup(r.x_norm, r.y_norm)
        analytics.write_csv(rows, track)
        summary = analytics.summarize(rows, a.fps)
        analytics.write_summary(summary, Path(track).with_suffix(".summary.json"))
        top = list(summary["dwell_seconds"].items())[:4]
        print(f"{track}: {top}")


def cmd_zones_preview(a: argparse.Namespace) -> None:
    src = SourceConfig.load(a.source)
    minimap = crop_box(read_frame_at(a.video, a.time), src.minimap_box)
    zones = load_zones(a.zones)
    scale = 3
    big = cv2.resize(minimap, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    out = zones.draw(big, step=3)
    cv2.imwrite(a.out, out)
    print(f"wrote {a.out}")


def cmd_zones_init(a: argparse.Namespace) -> None:
    save_zones(default_polygons(), a.out)
    print(f"wrote default zones to {a.out}. Edit the polygons, then check with `rov zones-preview`.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rov", description="Arena of Valor minimap tracking and positioning analytics.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("download", help="download a video with yt-dlp")
    s.add_argument("url")
    s.add_argument("-o", "--out", required=True, help="output path, e.g. data/videos/rpl_g1.mp4")
    s.add_argument("--max-height", type=int, default=1080)
    s.add_argument("--from", dest="start", default=None, help="clip start in the VOD, e.g. 1:23:45 (use with --to)")
    s.add_argument("--to", dest="end", default=None, help="clip end in the VOD, e.g. 1:45:00")
    s.add_argument("--audio", action="store_true", help="keep audio (off by default, the tracker does not need it)")
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("info", help="print video resolution, fps and duration")
    s.add_argument("video")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("calibrate", help="pick the minimap box and ring colours for a video source")
    s.add_argument("video")
    s.add_argument("--name", required=True, help="source name, e.g. rpl2026")
    s.add_argument("-o", "--out", required=True, help="config path, e.g. configs/sources/rpl2026.json")
    s.add_argument("--time", type=float, default=10.0, help="video second to grab the frame from")
    s.add_argument("--box", help="non-interactive: minimap box as x,y,w,h in full-frame pixels")
    s.add_argument("--icon-diameter", type=int, default=22, help="used with --box")
    s.add_argument("--default-rings", action="store_true", help="skip ring colour sampling, keep defaults")
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("template", help="crop a hero icon from the minimap and save it as a template (keyed by hero)")
    s.add_argument("video")
    s.add_argument("--source", required=True)
    s.add_argument("--hero", required=True, help="hero name, e.g. zill. Same file serves both sides and every game.")
    s.add_argument("--time", type=float, default=10.0, help="video second where the hero is clearly visible")
    s.add_argument("--box", help="non-interactive: icon box as x,y,w,h in minimap-crop pixels")
    s.add_argument("--templates", default=DEFAULT_TEMPLATES)
    s.set_defaults(func=cmd_template)

    s = sub.add_parser("match-init", help="write a blank match manifest to fill in from the draft screen")
    s.add_argument("video")
    s.add_argument("--source", required=True)
    s.add_argument("--game-start", type=float, default=0.0, help="video second where the clock reads 0:00")
    s.add_argument("-o", "--out", required=True, help="e.g. configs/matches/rpl_g1.json")
    s.set_defaults(func=cmd_match_init)

    s = sub.add_parser("track", help="track a hero through a video and write a CSV")
    s.add_argument("video", nargs="?", default=None, help="video path (not needed with --match)")
    s.add_argument("--match", default=None, help="match manifest JSON; then choose --player, --hero, or --all")
    s.add_argument("--all", action="store_true", help="with --match: track every player in the manifest")
    s.add_argument("--source", default=None)
    s.add_argument("--hero", default=None)
    s.add_argument("--side", default=None, choices=["blue", "red"])
    s.add_argument("--player", default="")
    s.add_argument("--match-id", default="")
    s.add_argument("--fps", type=float, default=2.0, help="samples per second")
    s.add_argument("--start", type=float, default=0.0, help="video second to start at")
    s.add_argument("--end", type=float, default=None, help="video second to stop at")
    s.add_argument("--game-start", type=float, default=None, help="video second where the game clock is 0:00 (default: --start)")
    s.add_argument("--zones", default=None, help="zones JSON (default: built-in AoV layout)")
    s.add_argument("--min-score", type=float, default=0.55)
    s.add_argument("--templates", default=DEFAULT_TEMPLATES)
    s.add_argument("--debug-video", default=None, help="write an mp4 of the minimap with the detection drawn")
    s.add_argument("--no-images", action="store_true")
    s.add_argument("-o", "--out", default=None, help="CSV path (default: data/tracks/<video>_<hero>_<side>.csv)")
    s.set_defaults(func=cmd_track)

    s = sub.add_parser("heatmap", help="render heatmap and path images from an existing track CSV")
    s.add_argument("track")
    s.add_argument("--video", required=True, help="video to take the minimap background from")
    s.add_argument("--source", required=True)
    s.add_argument("--out-dir", default="data/tracks")
    s.add_argument("--bins", type=int, default=64)
    s.add_argument("--fps", type=float, default=2.0, help="sample rate the track was made with")
    s.add_argument("--min-sec", type=float, default=None, help="only game seconds >= this")
    s.add_argument("--max-sec", type=float, default=None, help="only game seconds <= this")
    s.add_argument("--background-time", type=float, default=0.0)
    s.set_defaults(func=cmd_heatmap)

    s = sub.add_parser("phases", help="one heatmap per game phase plus a combined sheet")
    s.add_argument("track")
    s.add_argument("--video", required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--phases", default=None, help="minutes, e.g. '0-4,4-8,8-15,15-' (default). Open end with a trailing dash.")
    s.add_argument("--out-dir", default="data/tracks/phases")
    s.add_argument("--bins", type=int, default=64)
    s.add_argument("--fps", type=float, default=2.0)
    s.set_defaults(func=cmd_phases)

    s = sub.add_parser("rezone", help="re-label the zone column of existing track CSVs and rewrite their summaries")
    s.add_argument("tracks", nargs="+", help="track CSV files")
    s.add_argument("--zones", default=None, help="zones JSON (default: built-in geometric layout)")
    s.add_argument("--fps", type=float, default=2.0, help="sample rate the tracks were made with")
    s.set_defaults(func=cmd_rezone)

    s = sub.add_parser("zones-init", help="write the default zone polygons to a JSON file for editing")
    s.add_argument("-o", "--out", default="configs/zones/aov.json")
    s.set_defaults(func=cmd_zones_init)

    s = sub.add_parser("zones-preview", help="draw zone polygons over a real minimap frame")
    s.add_argument("video")
    s.add_argument("--source", required=True)
    s.add_argument("--zones", default=None)
    s.add_argument("--time", type=float, default=10.0)
    s.add_argument("-o", "--out", default="data/zones_preview.png")
    s.set_defaults(func=cmd_zones_preview)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
