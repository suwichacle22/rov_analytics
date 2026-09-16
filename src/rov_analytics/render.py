"""Images and videos for checking results by eye."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .analytics import TrackRow


def heatmap_image(background: np.ndarray, grid: np.ndarray, blur: int = 9, alpha: float = 0.85) -> np.ndarray:
    """Overlay a brightness heatmap on a minimap crop. Grey background, white where the hero was."""
    h, w = background.shape[:2]
    heat = cv2.resize(grid, (w, h), interpolation=cv2.INTER_LINEAR)
    if blur > 0:
        k = blur if blur % 2 == 1 else blur + 1
        heat = cv2.GaussianBlur(heat, (k, k), 0)
    if heat.max() > 0:
        heat = heat / heat.max()
    base = cv2.cvtColor(cv2.cvtColor(background, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR).astype(np.float32) * 0.45
    glow = np.stack([heat * 255] * 3, axis=-1)
    out = base * (1 - alpha * heat[..., None]) + glow * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def path_image(background: np.ndarray, rows: list[TrackRow]) -> np.ndarray:
    """Draw the track as a polyline that brightens over time."""
    out = cv2.cvtColor(cv2.cvtColor(background, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    out = (out.astype(np.float32) * 0.45).astype(np.uint8)
    h, w = out.shape[:2]
    kept = [r for r in rows if r.x_norm is not None]
    pts = [(int(r.x_norm * w), int(r.y_norm * h)) for r in kept]
    n = len(pts)
    for i in range(1, n):
        if kept[i].status == "reacquired":
            continue  # a teleport or recall, not a walk
        shade = int(80 + 175 * i / max(1, n - 1))
        cv2.line(out, pts[i - 1], pts[i], (shade, shade, shade), 1, cv2.LINE_AA)
    if pts:
        cv2.circle(out, pts[0], 4, (138, 138, 138), -1, cv2.LINE_AA)
        cv2.circle(out, pts[-1], 4, (255, 255, 255), -1, cv2.LINE_AA)
    return out


class DebugVideo:
    """Writes the minimap crop, upscaled, with the detection drawn on it."""

    def __init__(self, path: str | Path, crop_size: tuple[int, int], fps: float, scale: int = 3) -> None:
        w, h = crop_size
        self.scale = scale
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w * scale, h * scale))

    def write(self, minimap: np.ndarray, x_norm: float | None, y_norm: float | None, score: float, status: str, game_sec: float) -> None:
        h, w = minimap.shape[:2]
        frame = cv2.resize(minimap, (w * self.scale, h * self.scale), interpolation=cv2.INTER_NEAREST)
        if x_norm is not None and y_norm is not None:
            cx, cy = int(x_norm * w * self.scale), int(y_norm * h * self.scale)
            colour = (255, 255, 255) if status == "detected" else (58, 69, 255)  # BGR: white or red
            cv2.circle(frame, (cx, cy), 14, colour, 2, cv2.LINE_AA)
        text = f"{int(game_sec // 60):02d}:{int(game_sec % 60):02d}  {status}  {score:.2f}"
        cv2.putText(frame, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.writer.write(frame)

    def close(self) -> None:
        self.writer.release()
