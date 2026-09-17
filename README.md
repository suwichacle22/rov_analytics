# rov_analytics

Track a pro Arena of Valor (RoV) player on the minimap from video, then build positioning analytics: heatmaps, path, zone dwell time, rotations.

No game API is needed. The program reads the minimap out of a broadcast VOD or a screen recording, finds one known hero icon in every frame, and writes a CSV of positions.

Research behind the design: `docs/research/moba-positioning-analytics-research.html`.

## Setup

Python 3.14 and uv. No ffmpeg needed.

```
python -m uv sync
python -m uv run rov --help
```

## Workflow for a real match

**1. Get the video.** Either paste a YouTube link or use your own recording.

Tournament VODs are often a whole broadcast day, many hours long. Do not download all of it. Find the game in the YouTube player, note when it starts and ends, and download only that range. ffmpeg is bundled, nothing to install.

```
python -m uv run rov download "https://www.youtube.com/watch?v=..." -o data/videos/rpl_g1.mp4 --from 1:23:40 --to 1:45:30
python -m uv run rov info data/videos/rpl_g1.mp4
```

Audio is skipped by default. A 20-minute 1080p game is roughly 300 to 600 MB. The clip may begin a few seconds before `--from` because the cut lands on a keyframe. Leave `--from` and `--to` off to download the whole video.

**2. Calibrate the source once per broadcast layout.** Opens a window. Drag a box around the minimap, then around one hero icon, then click one blue ring pixel and one red ring pixel. Saved as a JSON you reuse for every video from that tournament.

```
python -m uv run rov calibrate data/videos/rpl_g1.mp4 --name rpl2026 -o configs/sources/rpl2026.json --time 30
```

Check `configs/sources/rpl2026.minimap.png` to confirm the crop is right.

**3. Make a template for each hero you have not seen before.** Templates are keyed by hero, not player, because a hero's minimap face is the same in every game and on either side. Pick a video second where the hero stands alone (base at game start is ideal) and drag a box around the icon.

```
python -m uv run rov template data/videos/rpl_g1.mp4 --source configs/sources/rpl2026.json --hero zill --time 35
```

Saved as `templates/<source>/<hero>.png`. Over a season the folder fills up and new games need no new crops.

**4. Describe the game in a manifest.** One JSON per game, filled from the draft screen: who played which hero on which side, plus where the clock reads 0:00 in the clip.

```
python -m uv run rov match-init data/videos/rpl_g1.mp4 --source configs/sources/rpl2026.json --game-start 3 -o configs/matches/rpl_g1.json
```

Then edit the file:

```json
{"player": "FS Overone", "hero": "zill", "side": "blue", "role": "jungle"}
```

**5. Track by player name.** The tool resolves player to hero to template. If a template is missing it stops and names the hero you need to crop.

```
python -m uv run rov track --match configs/matches/rpl_g1.json --player "FS Overone" --debug-video data/tracks/rpl_g1_debug.mp4
python -m uv run rov track --match configs/matches/rpl_g1.json --all
```

You can still skip the manifest and pass everything by hand:

```
python -m uv run rov track data/videos/rpl_g1.mp4 --source configs/sources/rpl2026.json --hero zill --side blue --game-start 3
```

Outputs per hero:

- `data/tracks/<match>_<hero>.csv`, one row per half second: game time, x and y in 0..1, zone, match score, status.
- `data/tracks/<match>_<hero>.summary.json`: coverage, distance, zone changes per minute, dwell seconds per zone.
- `data/tracks/<match>_<hero>_heatmap.png` and `_path.png`.
- The debug video shows the minimap with a circle on the detected position. White circle means detected, red means held from the previous frame. Watch this first when something looks wrong.

**6. Re-render for a time window** without re-tracking:

```
python -m uv run rov heatmap data/tracks/rpl_g1_zill.csv --video data/videos/rpl_g1.mp4 --source configs/sources/rpl2026.json --min-sec 0 --max-sec 240
```

**7. Zones.** The default zone layout is geometric: bases by corner distance, side lanes as edge strips, mid lane as a band on the main diagonal, river as a band on the anti-diagonal, objective pits as circles, and the rest is jungle split into four quadrants. Check it over a real frame:

```
python -m uv run rov zones-preview data/videos/rpl_g1.mp4 --source configs/sources/rpl2026.json -o data/zones_preview.png
```

To tune it, write a JSON object with any of the parameters in `GeometricZones` (for example `{"mid_band": 0.06, "pit_radius": 0.09}`) and pass it with `--zones`. For fully hand-drawn regions, `rov zones-init` exports polygons that override the geometry where they exist.

Changing zones does not require re-tracking. Re-label existing CSVs and rewrite their summaries:

```
python -m uv run rov rezone data/tracks/rpl_g1_*.csv --zones configs/zones/mine.json
```

## How detection works

- Crop the minimap using the calibrated box.
- Slide the hero template over the crop and score similarity at every position (OpenCV normalised cross-correlation).
- Only accept positions where enough team-ring-coloured pixels are present, which rules out the enemy team and most of the map.
- Take the best score above `--min-score` (default 0.55).
- A tracker rejects jumps larger than a hero can walk in one sample, holds the last position for up to 3 seconds when the icon is hidden, and re-acquires after a recall or teleport when the new position repeats for 3 frames.
- Pixel position divided by crop size gives map coordinates in 0..1, then a point-in-polygon lookup gives the zone.

## Synthetic self-test

Generates a fake broadcast with a scripted jungler route, a ping distractor, nine other heroes, a recall teleport and a 2-second overlay covering the minimap. Then tracks it and scores against ground truth.

```
python -m uv run python scripts/make_synthetic_video.py data/synthetic/game.mp4 --seconds 60
python -m uv run rov calibrate data/synthetic/game.mp4 --name synthetic -o configs/sources/synthetic.json --time 0.1 --box 20,480,220,220 --icon-diameter 20
python -m uv run rov template data/synthetic/game.mp4 --source configs/sources/synthetic.json --hero TestJungler --time 0.1 --box 12,188,20,20
python -m uv run rov track data/synthetic/game.mp4 --source configs/sources/synthetic.json --hero TestJungler --side blue --debug-video data/synthetic/debug.mp4
python -m uv run python scripts/eval_synthetic.py data/tracks/game_testjungler.csv data/synthetic/game.truth.csv
```

Expected: median error under 1 px, misses only during the teleport and the overlay.

## Tuning when a real video misbehaves

- Circle never appears: ring colour range is wrong. Re-run `calibrate` and click carefully on the ring, or edit `ring_ranges` in the source JSON.
- Circle jumps to a teammate in fights: raise `--min-score` to 0.65 or lower `max_speed_norm_per_sec` in `track.py`.
- Circle lost after recall: lower `reacquire_frames` in `track.py`.
- Broadcast cuts to a replay or a face cam: those frames show as held or gap. Coverage in the summary tells you how much of the game was usable.

## Layout

```
src/rov_analytics/
  config.py     source config: minimap box, icon size, ring colours
  video.py      yt-dlp download, frame iterator
  calibrate.py  interactive box and colour pickers, template saving
  detect.py     template match gated by ring colour
  track.py      jump rejection, hold, re-acquire
  zones.py      zone polygons and lookup, default AoV layout
  analytics.py  CSV I/O, heatmap grid, summary stats
  render.py     heatmap and path images, debug video
  pipeline.py   glue
  match.py      match manifest: video, source, who played which hero
  cli.py        `rov` commands
scripts/        synthetic video generator and evaluator
configs/        source configs, match manifests, zone files
templates/      hero icon templates per source
data/           videos and outputs (ignored by git)
```

## Next steps

- Track all ten heroes in one pass and compute team metrics: within-team distance, convex hull, jungle proximity.
- Read the game clock by OCR so `--start` is found automatically.
- Detect when the minimap is covered by an overlay instead of relying on low scores.
- Swap template matching for a small YOLO trained on synthetic minimaps once real broadcasts show its limits.
- Web dashboard (TanStack Start plus Convex) with a timeline scrubber, heatmap filters and two-player comparison.
