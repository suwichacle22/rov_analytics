"""Images and videos for checking results by eye."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .analytics import TrackRow


def heatmap_image(
    background: np.ndarray,
    grid: np.ndarray,
    blur: int = 21,
    scale: int = 2,
    title: str = "",
    subtitle: str = "",
    clip_percentile: float = 97.0,
) -> np.ndarray:
    """Temperature-style heatmap over the minimap.

    Uses the inferno ramp (dark purple -> orange -> yellow): it reads as heat, is ordered
    in lightness, and stays legible for colourblind viewers. Cells the hero never visited
    are fully transparent so the map shows through. Includes a colour bar and a title.
    """
    h, w = background.shape[:2]
    W, H = w * scale, h * scale
    bg = cv2.resize(background, (W, H), interpolation=cv2.INTER_CUBIC)
    # Dim and desaturate the map so the heat is the only strong colour.
    grey = cv2.cvtColor(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    base = (bg.astype(np.float32) * 0.35 + grey.astype(np.float32) * 0.25)

    heat = cv2.resize(grid, (W, H), interpolation=cv2.INTER_LINEAR)
    k = blur * scale
    k = k if k % 2 == 1 else k + 1
    heat = cv2.GaussianBlur(heat, (k, k), 0)
    if heat.max() > 0:
        # Clip at a high percentile of the visited cells so one long stand (a siege, waiting
        # in base) saturates instead of flattening the rest of the map, then sqrt so
        # mid-density areas stay visible.
        visited = heat[heat > 0]
        cap = float(np.percentile(visited, clip_percentile)) if visited.size else float(heat.max())
        heat = np.sqrt(np.clip(heat / max(cap, 1e-6), 0.0, 1.0))

    colour = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_INFERNO).astype(np.float32)
    alpha = np.clip(heat * 1.6, 0.0, 0.92)[..., None]
    body = base * (1 - alpha) + colour * alpha
    body = np.clip(body, 0, 255).astype(np.uint8)

    # Layout: title strip on top, colour bar on the right.
    top = 34 if (title or subtitle) else 0
    bar_w, pad = 18, 44
    canvas = np.full((H + top, W + bar_w + pad, 3), 16, dtype=np.uint8)
    canvas[top : top + H, :W] = body
    if title:
        cv2.putText(canvas, title, (6, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    if subtitle:
        cv2.putText(canvas, subtitle, (6, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1, cv2.LINE_AA)
    ramp = np.linspace(255, 0, H, dtype=np.uint8).reshape(-1, 1)
    bar = cv2.applyColorMap(np.repeat(ramp, bar_w, axis=1), cv2.COLORMAP_INFERNO)
    x0 = W + 10
    canvas[top : top + H, x0 : x0 + bar_w] = bar
    cv2.putText(canvas, "more", (x0 - 2, top + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(canvas, "less", (x0 - 2, top + H - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(canvas, "time", (x0 + bar_w + 3, top + H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1, cv2.LINE_AA)
    return canvas


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
