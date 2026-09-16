"""Video input: download from YouTube and iterate frames at a target sample rate.

ffmpeg is not required. OpenCV reads the container directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


def download(url: str, out_path: str | Path, max_height: int = 1080) -> Path:
    """Download a video with yt-dlp into a single mp4 file at up to `max_height`."""
    import yt_dlp  # imported lazily so the rest of the package works offline

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={max_height}][ext=mp4]/best",
        "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
    }
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
) -> Iterator[Frame]:
    """Yield frames every 1/sample_fps seconds between start_sec and end_sec.

    `game_start_sec` is the video time at which the in-game clock reads 0:00. Defaults
    to `start_sec`, so game_sec is 0 at the first yielded frame.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(native_fps / sample_fps)))
    if game_start_sec is None:
        game_start_sec = start_sec

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
                yield Frame(index=index, video_sec=video_sec, game_sec=video_sec - game_start_sec, image=img)
            index += 1
    finally:
        cap.release()


def crop_box(img: np.ndarray, box: list[int]) -> np.ndarray:
    x, y, w, h = box
    return img[y : y + h, x : x + w]
