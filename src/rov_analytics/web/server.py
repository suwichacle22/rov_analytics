"""FastAPI server for the live heatmap app.

Run with `rov-web` (or `python -m rov_analytics.web.server`) and open http://127.0.0.1:8000.

Jobs run in background threads. The browser subscribes to a job's Server-Sent Events
stream and receives the live minimap, the growing heatmap, and stats as each frame is
processed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import analytics, pipeline, render
from ..calibrate import save_template, template_path
from ..config import SourceConfig
from ..video import clean_background, crop_box, download, parse_timestamp, probe, read_frame_at
from ..zones import load_zones

ROOT = Path.cwd()
DATA = ROOT / "data"
VIDEOS = DATA / "videos"
TRACKS = DATA / "tracks"
SOURCES = ROOT / "configs" / "sources"
TEMPLATES = ROOT / "templates"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="rov_analytics live heatmap")


# ----------------------------------------------------------------------------- jobs

@dataclass
class Job:
    id: str
    kind: str
    params: dict
    status: str = "queued"
    error: str = ""
    result: dict = field(default_factory=dict)
    last: dict = field(default_factory=dict)          # last event of each type, for late subscribers
    subscribers: list[queue.Queue] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, event: str, data: dict) -> None:
        msg = {"event": event, "data": data}
        with self.lock:
            self.last[event] = data
            for q in list(self.subscribers):
                q.put(msg)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            for event, data in self.last.items():
                q.put({"event": event, "data": data})
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)


JOBS: dict[str, Job] = {}


def _jpeg_b64(img: np.ndarray, quality: int = 80) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _video_path_for(url: str, start: float | None, end: float | None) -> Path:
    key = hashlib.sha1(f"{url}|{start}|{end}".encode()).hexdigest()[:10]
    return VIDEOS / f"web_{key}.mp4"


def _ensure_video(job: Job, url: str, start: float | None, end: float | None) -> Path:
    """Download the clip once; reuse it on later runs with the same link and range."""
    if url and not url.startswith("http"):
        p = Path(url)
        if not p.exists():
            raise FileNotFoundError(f"video file not found: {url}")
        return p
    out = _video_path_for(url, start, end)
    if out.exists() and out.stat().st_size > 0:
        job.emit("status", {"stage": "download", "message": "using cached clip", "video": str(out)})
        return out
    job.emit("status", {"stage": "download", "message": "downloading clip ...", "video": str(out)})
    download(url, out, start_sec=start, end_sec=end)
    job.emit("status", {"stage": "download", "message": "download complete", "video": str(out)})
    return out


def _run_download_job(job: Job) -> None:
    p = job.params
    try:
        job.status = "running"
        video = _ensure_video(job, p["url"], p.get("start"), p.get("end"))
        info = probe(video)
        job.result = {"video": str(video), "width": info.width, "height": info.height,
                      "fps": info.fps, "duration_sec": round(info.duration_sec, 1)}
        job.status = "done"
        job.emit("done", job.result)
    except Exception as e:  # noqa: BLE001
        job.status, job.error = "error", str(e)
        job.emit("error", {"message": str(e)})


def _run_track_job(job: Job) -> None:
    p = job.params
    try:
        job.status = "running"
        video = _ensure_video(job, p["url"], p.get("start"), p.get("end"))
        source = SourceConfig.load(SOURCES / f"{p['source']}.json")
        hero, side, player = p["hero"], p["side"], p.get("player", "")
        fps = float(p.get("fps", 2.0))
        game_start = float(p.get("game_start", 0.0))
        match_id = p.get("match_id") or video.stem
        template_path(TEMPLATES, hero, source.name, side)  # raises with a helpful message if missing

        job.emit("status", {"stage": "prepare", "message": "building clean minimap background ..."})
        background = clean_background(video, source.minimap_box)
        info = probe(video)
        total = info.duration_sec
        zones = load_zones(None)
        bins = 64
        grid = np.zeros((bins, bins), dtype=np.float32)
        points = []
        dwell: dict[str, float] = {}
        n_valid = 0
        t_last_heat = 0.0
        job.emit("status", {"stage": "track", "message": "tracking ..."})

        for i, (minimap, pt) in enumerate(pipeline.iter_track(
            video, source, hero, side, TEMPLATES, fps, 0.0, None, game_start, float(p.get("min_score", 0.55)),
        )):
            points.append(pt)
            zone = ""
            if pt.x_norm is not None:
                n_valid += 1
                cx = min(bins - 1, max(0, int(pt.x_norm * bins)))
                cy = min(bins - 1, max(0, int(pt.y_norm * bins)))
                grid[cy, cx] += 1
                zone = zones.lookup(pt.x_norm, pt.y_norm)
                dwell[zone] = dwell.get(zone, 0.0) + 1.0 / fps

            # Live minimap with the detection circle, every frame.
            live = cv2.resize(minimap, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            if pt.x_norm is not None:
                colour = (255, 255, 255) if pt.status == "detected" else (58, 69, 255)
                cv2.circle(live, (int(pt.x_norm * live.shape[1]), int(pt.y_norm * live.shape[0])), 18, colour, 2, cv2.LINE_AA)
            top = sorted(dwell.items(), key=lambda kv: -kv[1])[:6]
            job.emit("frame", {
                "minimap": _jpeg_b64(live, 70),
                "game_sec": round(pt.game_sec, 1),
                "video_sec": round(pt.video_sec, 1),
                "progress": min(1.0, pt.video_sec / total) if total else 0.0,
                "status": pt.status,
                "score": round(pt.score, 2),
                "zone": zone,
                "tracked_sec": round(n_valid / fps, 1),
                "coverage": round(n_valid / len(points), 3),
                "top_zones": [{"zone": z, "sec": round(s, 1)} for z, s in top],
            })
            # Heatmap once per second of game time.
            if pt.game_sec - t_last_heat >= 1.0 or i == 0:
                t_last_heat = pt.game_sec
                title = f"{player or hero}  ({hero}, {side})"
                sub = f"{match_id}   up to {int(max(0, pt.game_sec))//60}:{int(max(0, pt.game_sec))%60:02d}   {n_valid/fps:.0f}s tracked"
                heat = render.heatmap_image(background, grid, title=title, subtitle=sub)
                job.emit("heatmap", {"image": _jpeg_b64(heat, 85)})

        # Finalise: CSV, summary, images, phases.
        job.emit("status", {"stage": "finalise", "message": "writing outputs ..."})
        rows = analytics.rows_from_track(points, zones, match_id, side, hero, player)
        out_csv = TRACKS / f"{match_id}_{hero.lower()}.csv"
        analytics.write_csv(rows, out_csv)
        summary = analytics.summarize(rows, fps)
        analytics.write_summary(summary, out_csv.with_suffix(".summary.json"))
        outs = pipeline.render_outputs(rows, video, source, TRACKS, stem=out_csv.stem, background=background)
        phases = pipeline.render_phases(rows, video, source, TRACKS / "phases", sample_fps=fps, background=background)
        rel = lambda pth: "/files/" + Path(pth).resolve().relative_to(DATA.resolve()).as_posix()  # noqa: E731
        job.result = {
            "csv": rel(out_csv),
            "summary": summary,
            "heatmap": rel(outs["heatmap"]),
            "path": rel(outs["path"]),
            "phases_sheet": rel(phases["sheet"]),
            "phases": phases["stats"],
        }
        job.status = "done"
        job.emit("done", job.result)
    except Exception as e:  # noqa: BLE001
        job.status, job.error = "error", str(e)
        job.emit("error", {"message": str(e)})


def _start(kind: str, params: dict) -> Job:
    job = Job(id=uuid.uuid4().hex[:8], kind=kind, params=params)
    JOBS[job.id] = job
    target = _run_track_job if kind == "track" else _run_download_job
    threading.Thread(target=target, args=(job,), daemon=True).start()
    return job


# ----------------------------------------------------------------------------- api

class DownloadReq(BaseModel):
    url: str
    start: str | None = None
    end: str | None = None


class TrackReq(BaseModel):
    url: str
    start: str | None = None
    end: str | None = None
    source: str
    hero: str
    side: str
    player: str = ""
    game_start: float = 0.0
    fps: float = 2.0
    min_score: float = 0.55
    match_id: str = ""


class TemplateReq(BaseModel):
    video: str
    source: str
    hero: str
    t: float
    x: float   # click position in the enlarged minimap image
    y: float
    scale: int = 3


def _range(req: DownloadReq | TrackReq) -> tuple[float | None, float | None]:
    s = parse_timestamp(req.start) if req.start else None
    e = parse_timestamp(req.end) if req.end else None
    if (s is None) != (e is None):
        raise HTTPException(400, "give both start and end, or neither")
    if s is not None and e is not None and e <= s:
        raise HTTPException(400, "end must be after start")
    return s, e


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/sources")
def list_sources() -> list[dict]:
    out = []
    for p in sorted(SOURCES.glob("*.json")):
        cfg = SourceConfig.load(p)
        out.append({"name": cfg.name, "file": p.name, "minimap_box": cfg.minimap_box, "notes": cfg.notes})
    return out


@app.get("/api/templates")
def list_templates(source: str) -> list[str]:
    d = TEMPLATES / source
    return sorted(p.stem for p in d.glob("*.png")) if d.exists() else []


@app.get("/api/videos")
def list_videos() -> list[dict]:
    out = []
    for p in sorted(VIDEOS.glob("*.mp4"), key=lambda p: -p.stat().st_mtime):
        out.append({"path": str(p), "name": p.name, "mb": round(p.stat().st_size / 1e6)})
    return out


@app.post("/api/download")
def start_download(req: DownloadReq) -> dict:
    s, e = _range(req)
    job = _start("download", {"url": req.url, "start": s, "end": e})
    return {"job_id": job.id}


@app.post("/api/track")
def start_track(req: TrackReq) -> dict:
    s, e = _range(req)
    if not (SOURCES / f"{req.source}.json").exists():
        raise HTTPException(400, f"unknown source '{req.source}'")
    try:
        template_path(TEMPLATES, req.hero, req.source, req.side)
    except FileNotFoundError as ex:
        raise HTTPException(400, str(ex)) from ex
    params = req.model_dump()
    params["start"], params["end"] = s, e
    job = _start("track", params)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_state(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return {"id": job.id, "kind": job.kind, "status": job.status, "error": job.error, "result": job.result}


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    def gen():
        q = job.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                if msg["event"] in ("done", "error"):
                    break
        finally:
            job.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/frame")
def minimap_frame(video: str, t: float, source: str, scale: int = 3) -> Response:
    """Enlarged minimap crop at video second t, for picking a template by clicking."""
    cfg = SourceConfig.load(SOURCES / f"{source}.json")
    try:
        frame = read_frame_at(video, t)
    except (FileNotFoundError, ValueError) as ex:
        raise HTTPException(400, str(ex)) from ex
    mm = crop_box(frame, cfg.minimap_box)
    big = cv2.resize(mm, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", big)
    return Response(content=buf.tobytes(), media_type="image/png")


@app.post("/api/template")
def make_template(req: TemplateReq) -> dict:
    cfg = SourceConfig.load(SOURCES / f"{req.source}.json")
    frame = read_frame_at(req.video, req.t)
    mm = crop_box(frame, cfg.minimap_box)
    cx, cy = int(req.x / req.scale), int(req.y / req.scale)
    half = max(6, int(cfg.icon_diameter_px * 0.36))  # face only, ring excluded
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(mm.shape[1], cx + half), min(mm.shape[0], cy + half)
    tpl = mm[y0:y1, x0:x1].copy()
    if tpl.size == 0:
        raise HTTPException(400, "click landed outside the minimap")
    out = save_template(tpl, TEMPLATES, req.hero, cfg.name)
    ok, buf = cv2.imencode(".png", cv2.resize(tpl, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    return {"saved": str(out), "preview": "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii"),
            "size": [tpl.shape[1], tpl.shape[0]]}


DATA.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(DATA)), name="files")


def main() -> None:
    import uvicorn

    print("rov_analytics live heatmap: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
