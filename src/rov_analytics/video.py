"""Video input: download from YouTube and iterate frames at a target sample rate.

ffmpeg is not required. OpenCV reads the container directly.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def download(
    url: str,
    out_path: str | Path,
    max_height: int = 1080,
    start_sec: float | None = None,
    end_sec: float | None = None,
    video_only: bool = True,
) -> Path:
    """Download a video with yt-dlp into a single mp4 file at up to `max_height`.

    Give `start_sec` and `end_sec` to fetch only that part of a long VOD. The cut lands on
    the nearest keyframe before `start_sec`, so the clip may begin a few seconds early.
    Audio is skipped by default because the tracker never uses it.
    """
    import os

    import yt_dlp  # imported lazily so the rest of the package works offline
    from yt_dlp.utils import download_range_func

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


def read_frame_at(path: str | Path, video_sec: float) -> np.ndarray:
    """Return the single frame nearest to `video_sec`."""
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
            crops.append(crop_box(read_frame_at(path, float(t)), box))
        except ValueError:
            continue
    if not crops:
        raise ValueError(f"could not read any frame from {path}")
    return np.median(np.stack(crops), axis=0).astype(np.uint8)


def crop_box(img: np.ndarray, box: list[int]) -> np.ndarray:
    x, y, w, h = box
    return img[y : y + h, x : x + w]
