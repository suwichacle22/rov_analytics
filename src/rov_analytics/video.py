"""Video input: download from YouTube and iterate frames at a target sample rate.

Frame reads go through the bundled ffmpeg (GPU decode when available) with an OpenCV fallback.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


def parse_timestamp(text: str) -> float:
    """'1:23:45', '23:45', '45', or '5025.5' -> seconds."""
    parts = text.strip().split(":")
    if len(parts) > 3:
        raise ValueError(f"bad timestamp: {text}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def ffmpeg_path() -> str:
    """Directory holding an `ffmpeg` binary, so users do not need to install ffmpeg.

    imageio-ffmpeg ships the binary under a versioned name. yt-dlp only recognises a file
    called `ffmpeg`, so copy it once into a cache directory under that name.
    """
    import shutil

    import imageio_ffmpeg

    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    cache = Path.home() / ".cache" / "rov_analytics" / "ffmpeg"
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / ("ffmpeg.exe" if src.suffix.lower() == ".exe" else "ffmpeg")
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copyfile(src, dst)
        dst.chmod(0o755)
    return str(cache)


_JS_RUNTIMES = {"deno": {"path": None}, "node": {"path": None}, "bun": {"path": None}}


@dataclass
class ClipMeta:
    """What was actually fetched for a time range. Saved next to the clip as `<clip>.meta.json`."""

    url: str
    format_id: str
    requested_start: float
    requested_end: float
    actual_start: float     # the clip's first frame is at this VOD second (a segment boundary <= requested)
    actual_end: float

    @property
    def start_offset(self) -> float:
        """Seconds into the clip where the requested start lands."""
        return self.requested_start - self.actual_start

    def save(self, clip: Path) -> None:
        clip.with_suffix(".meta.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, clip: str | Path) -> "ClipMeta | None":
        p = Path(clip).with_suffix(".meta.json")
        if not p.exists():
            return None
        return cls(**json.loads(p.read_text(encoding="utf-8")))


def download(
    url: str,
    out_path: str | Path,
    max_height: int = 1080,
    start_sec: float | None = None,
    end_sec: float | None = None,
    video_only: bool = True,
    progress: "callable | None" = None,
) -> Path:
    """Download a video with yt-dlp into a single mp4 file at up to `max_height`.

    With `start_sec` and `end_sec`, only that part of the VOD is fetched. YouTube mp4
    streams carry a segment index, so the exact bytes for the range are pulled with several
    parallel connections (about 10x faster than streaming through ffmpeg, which YouTube
    throttles). The clip starts at the segment boundary at or before `start_sec`; the exact
    offset is written to `<clip>.meta.json`. Falls back to yt-dlp's ffmpeg section download
    when the fast path is not possible. Audio is skipped by default.
    """
    import os

    import yt_dlp  # imported lazily so the rest of the package works offline
    from yt_dlp.utils import download_range_func

    out_path = Path(out_path)
    if start_sec is not None and end_sec is not None and url.startswith("http"):
        try:
            return _download_range_fast(url, out_path, start_sec, end_sec, max_height, progress)
        except Exception as e:  # noqa: BLE001
            print(f"fast range download not possible ({e}); falling back to ffmpeg section download")

    # yt-dlp's range downloader checks PATH for ffmpeg, not only `ffmpeg_location`.
    ffdir = ffmpeg_path()
    if ffdir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffdir + os.pathsep + os.environ.get("PATH", "")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if video_only:
        fmt = f"bestvideo[height<={max_height}][ext=mp4]/bestvideo[height<={max_height}]/best[height<={max_height}]"
    else:
        fmt = f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={max_height}][ext=mp4]/best"
    opts = {
        "format": fmt,
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "ffmpeg_location": ffdir,
        # yt-dlp needs a JavaScript runtime for YouTube's challenge; accept any installed one.
        "js_runtimes": _JS_RUNTIMES,
    }
    if start_sec is not None or end_sec is not None:
        s = start_sec or 0.0
        e = end_sec if end_sec is not None else float("inf")
        if e <= s:
            raise ValueError("--to must be after --from")
        opts["download_ranges"] = download_range_func(None, [(s, e)])
        opts["force_keyframes_at_cuts"] = False
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    final = out_path.with_suffix(".mp4")
    if not final.exists():
        candidates = list(out_path.parent.glob(out_path.stem + ".*"))
        if not candidates:
            raise FileNotFoundError(f"yt-dlp finished but no file found for {out_path}")
        final = candidates[0]
    return final


def _parse_sidx(head: bytes) -> tuple[int, int, int, list[tuple[int, int]]] | None:
    """Find the sidx box in the first bytes of a DASH mp4.

    Returns (timescale, earliest_presentation_time, first_segment_byte_offset, [(size, duration), ...]).
    """
    import struct

    pos = 0
    while pos + 8 <= len(head):
        size, typ = struct.unpack(">I4s", head[pos : pos + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", head[pos + 8 : pos + 16])[0]
            hdr = 16
        if size == 0:
            return None
        if typ == b"sidx":
            if pos + size > len(head):
                return None
            body = head[pos + hdr : pos + size]
            version = body[0]
            timescale = struct.unpack(">I", body[8:12])[0]
            if version == 0:
                ept, first_offset = struct.unpack(">II", body[12:20])
                q = 20
            else:
                ept, first_offset = struct.unpack(">QQ", body[12:28])
                q = 28
            ref_count = struct.unpack(">H", body[q + 2 : q + 4])[0]
            q += 4
            segs = []
            for _ in range(ref_count):
                a, dur, _sap = struct.unpack(">III", body[q : q + 12])
                q += 12
                segs.append((a & 0x7FFFFFFF, dur))
            return timescale, ept, pos + size + first_offset, segs
        pos += size
    return None


def _download_range_fast(url: str, out_path: Path, start_sec: float, end_sec: float,
                         max_height: int, progress: "callable | None") -> Path:
    """Fetch exactly the segments covering [start, end] of a YouTube DASH mp4 stream, in parallel."""
    import os
    import subprocess
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "js_runtimes": _JS_RUNTIMES}) as ydl:
        info = ydl.extract_info(url, download=False)
    cands = [
        f for f in info.get("formats", [])
        if f.get("vcodec") not in (None, "none") and f.get("acodec") in (None, "none")
        and f.get("ext") == "mp4" and f.get("protocol") in ("https", "http")
        and (f.get("height") or 0) <= max_height and f.get("url")
    ]
    if not cands:
        raise RuntimeError("no video-only mp4 stream available")
    # Tallest first, then the cheapest bitrate at that height (AV1 < H.264 for the same picture).
    best_h = max(f["height"] for f in cands)
    fmt = min((f for f in cands if f["height"] == best_h), key=lambda f: f.get("tbr") or 1e9)
    stream_url, headers = fmt["url"], dict(fmt.get("http_headers") or {})

    def fetch(a: int, b: int) -> bytes:
        req = urllib.request.Request(stream_url, headers={**headers, "Range": f"bytes={a}-{b}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    head = fetch(0, 1_000_000)
    parsed = _parse_sidx(head)
    if parsed is None:
        raise RuntimeError("stream has no segment index")
    timescale, ept, seg_base, segs = parsed
    init_end = seg_base  # ftyp + moov + sidx (+ any padding before the first fragment)

    t = ept / timescale
    off = seg_base
    chosen: list[tuple[int, int, float, float]] = []
    for size, dur in segs:
        ts, te = t, t + dur / timescale
        if te > start_sec and ts < end_sec:
            chosen.append((off, off + size, ts, te))
        t, off = te, off + size
    if not chosen:
        raise RuntimeError("requested range is outside the video")
    b0, b1 = chosen[0][0], chosen[-1][1]
    actual_start, actual_end = chosen[0][2], chosen[-1][3]

    chunk = 4_000_000
    ranges = [(a, min(a + chunk - 1, b1 - 1)) for a in range(b0, b1, chunk)]
    total = b1 - b0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_suffix(".raw.mp4")
    done = 0
    with raw.open("wb") as fh:
        fh.write(head[:init_end] if init_end <= len(head) else fetch(0, init_end - 1))
        fh.truncate(init_end + total)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for (a, b), data in zip(ranges, ex.map(lambda r: fetch(*r), ranges)):
                fh.seek(init_end + (a - b0))
                fh.write(data)
                done += len(data)
                if progress:
                    progress(done, total)

    # Remux so the clip is a normal mp4 whose timestamps start at 0.
    exe = os.path.join(ffmpeg_path(), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    final = out_path.with_suffix(".mp4")
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(raw),
                    "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    raw.unlink(missing_ok=True)
    ClipMeta(url, str(fmt.get("format_id")), float(start_sec), float(end_sec), actual_start, actual_end).save(final)
    return final


@dataclass
class Frame:
    index: int          # frame index in the source video
    video_sec: float    # seconds from the start of the video file
    game_sec: float     # seconds from the game start (video_sec - start offset)
    image: np.ndarray   # full BGR frame


@dataclass
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_sec(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


def probe(path: str | Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    info = VideoInfo(
        path=Path(path),
        fps=cap.get(cv2.CAP_PROP_FPS) or 30.0,
        frame_count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    cap.release()
    return info


def read_frame_at(path: str | Path, video_sec: float, crop: list[int] | None = None) -> np.ndarray:
    """Return the single frame nearest to `video_sec` (optionally just the `crop` region).

    Uses an ffmpeg seek when available: OpenCV seeks can take several seconds on long
    60 fps files, ffmpeg's keyframe seek plus a short decode takes a fraction of that.
    """
    if _ffmpeg_available():
        img = _read_frame_ffmpeg(path, video_sec, crop)
        if img is not None:
            return img
    img = _read_frame_opencv(path, video_sec)
    return crop_box(img, crop) if crop else img


def _read_frame_ffmpeg(path: str | Path, video_sec: float, crop: list[int] | None) -> np.ndarray | None:
    import os
    import subprocess

    info = probe(path)
    w, h = (crop[2], crop[3]) if crop else (info.width, info.height)
    exe = os.path.join(ffmpeg_path(), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if isinstance(_HWACCEL, str):
        cmd += ["-hwaccel", _HWACCEL]
    cmd += ["-ss", f"{max(0.0, video_sec):.3f}", "-i", str(path), "-frames:v", "1"]
    if crop:
        cmd += ["-vf", f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}"]
    cmd += ["-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=60).stdout
    if len(out) < w * h * 3:
        return None
    return np.frombuffer(out[: w * h * 3], dtype=np.uint8).reshape(h, w, 3).copy()


def _read_frame_opencv(path: str | Path, video_sec: float) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, video_sec) * 1000.0)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"could not read a frame at {video_sec:.2f}s from {path}")
    return img


def iter_frames(
    path: str | Path,
    sample_fps: float = 2.0,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    game_start_sec: float | None = None,
    crop: list[int] | None = None,
    backend: str = "auto",
) -> Iterator[Frame]:
    """Yield frames every 1/sample_fps seconds between start_sec and end_sec.

    `game_start_sec` is the video time at which the in-game clock reads 0:00. Defaults
    to `start_sec`, so game_sec is 0 at the first yielded frame.

    `crop` = [x, y, w, h] makes the frame image just that region. With the ffmpeg
    backend the crop and the frame-rate drop happen inside ffmpeg, which decodes on all
    cores, so this is several times faster than OpenCV on 1080p60 broadcast video.
    """
    if game_start_sec is None:
        game_start_sec = start_sec
    if backend == "auto":
        backend = "ffmpeg" if _ffmpeg_available() else "opencv"
    if backend == "ffmpeg":
        yield from _iter_frames_ffmpeg(path, sample_fps, start_sec, end_sec, game_start_sec, crop)
        return

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(native_fps / sample_fps)))

    start_index = int(round(start_sec * native_fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_index)
    index = start_index
    try:
        while True:
            if end_sec is not None and index / native_fps > end_sec:
                break
            # grab() decodes cheaply; retrieve() only when we keep the frame.
            if not cap.grab():
                break
            if (index - start_index) % step == 0:
                ok, img = cap.retrieve()
                if not ok:
                    break
                video_sec = index / native_fps
                if crop is not None:
                    img = crop_box(img, crop)
                yield Frame(index=index, video_sec=video_sec, game_sec=video_sec - game_start_sec, image=img)
            index += 1
    finally:
        cap.release()


def _ffmpeg_available() -> bool:
    try:
        return Path(ffmpeg_path()).exists()
    except Exception:  # noqa: BLE001
        return False


def _iter_frames_ffmpeg(
    path: str | Path,
    sample_fps: float,
    start_sec: float,
    end_sec: float | None,
    game_start_sec: float,
    crop: list[int] | None,
) -> Iterator[Frame]:
    """Decode with ffmpeg, crop and drop frame rate inside ffmpeg, read raw BGR from a pipe.

    Tries GPU decoding first (CUDA, then D3D11VA on Windows) and falls back to software.
    The first working choice is remembered for the rest of the process.
    """
    import os
    import subprocess

    info = probe(path)
    w, h = (crop[2], crop[3]) if crop else (info.width, info.height)
    filters = []
    if crop:
        filters.append(f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}")
    filters.append(f"fps={sample_fps}")
    exe = os.path.join(ffmpeg_path(), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    frame_bytes = w * h * 3

    def build(hwaccel: str | None) -> list[str]:
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if hwaccel:
            cmd += ["-hwaccel", hwaccel]
        if start_sec > 0:
            cmd += ["-ss", f"{start_sec:.3f}"]
        cmd += ["-i", str(path)]
        if end_sec is not None:
            cmd += ["-t", f"{max(0.0, end_sec - start_sec):.3f}"]
        cmd += ["-vf", ",".join(filters), "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        return cmd

    global _HWACCEL
    candidates = [_HWACCEL] if _HWACCEL is not _UNSET else (["cuda", "d3d11va", None] if os.name == "nt" else ["cuda", None])
    for hwaccel in candidates:
        proc = subprocess.Popen(build(hwaccel), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_bytes * 4)
        first = proc.stdout.read(frame_bytes)
        if len(first) < frame_bytes:
            # This decoder produced nothing; try the next one (unless the clip is truly empty).
            proc.stdout.close()
            proc.kill()
            if hwaccel is None or _HWACCEL is not _UNSET:
                return
            continue
        _HWACCEL = hwaccel
        try:
            k = 0
            buf = first
            while True:
                img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
                video_sec = start_sec + k / sample_fps
                index = int(round(video_sec * info.fps))
                yield Frame(index=index, video_sec=video_sec, game_sec=video_sec - game_start_sec, image=img)
                k += 1
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
        finally:
            try:
                proc.stdout.close()
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return


_UNSET = object()
_HWACCEL: str | None | object = _UNSET


def clean_background(path: str | Path, box: list[int], samples: int = 15,
                     start_sec: float = 0.0, end_sec: float | None = None) -> np.ndarray:
    """Minimap with the moving icons removed: per-pixel median of frames spread over the game."""
    info = probe(path)
    end = end_sec if end_sec is not None else info.duration_sec
    # The reported duration can overshoot the last decodable frame, so stay a few seconds
    # short of it and skip any read that still fails.
    times = np.linspace(start_sec, max(start_sec, end - 3), samples)
    crops = []
    for t in times:
        try:
            crops.append(read_frame_at(path, float(t), crop=box))
        except ValueError:
            continue
    if not crops:
        raise ValueError(f"could not read any frame from {path}")
    return np.median(np.stack(crops), axis=0).astype(np.uint8)


def crop_box(img: np.ndarray, box: list[int]) -> np.ndarray:
    x, y, w, h = box
    return img[y : y + h, x : x + w]
