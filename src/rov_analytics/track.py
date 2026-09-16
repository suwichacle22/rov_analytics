"""Turn per-frame detections into a clean track.

Two rules do most of the work of a Kalman filter for this problem:
1. Reject a detection that is farther from the last accepted position than a hero can
   move in one sample interval. If the same far-away position repeats for a few frames
   (recall, teleport, or we simply lost them), accept it and re-acquire.
2. When nothing is found, carry the last position forward for a short while, then leave
   a gap rather than inventing data.
"""

from __future__ import annotations

from dataclasses import dataclass

from .detect import Detection


@dataclass
class TrackPoint:
    game_sec: float
    video_sec: float
    x_norm: float | None
    y_norm: float | None
    score: float
    status: str  # "detected", "held", "reacquired", "gap"


class Tracker:
    def __init__(
        self,
        sample_fps: float,
        max_speed_norm_per_sec: float = 0.20,
        hold_seconds: float = 3.0,
        reacquire_frames: int = 3,
    ) -> None:
        self.max_jump = max_speed_norm_per_sec / sample_fps
        self.max_hold = int(round(hold_seconds * sample_fps))
        self.reacquire_frames = reacquire_frames
        self.last: tuple[float, float] | None = None
        self.held_for = 0
        self.pending: list[tuple[float, float]] = []

    def update(self, det: Detection, game_sec: float, video_sec: float) -> TrackPoint:
        if det.found:
            pos = (det.x_norm, det.y_norm)
            if self.last is None:
                self.last, self.held_for, self.pending = pos, 0, []
                return TrackPoint(game_sec, video_sec, *pos, det.score, "detected")

            jump = ((pos[0] - self.last[0]) ** 2 + (pos[1] - self.last[1]) ** 2) ** 0.5
            if jump <= self.max_jump * (1 + self.held_for):
                self.last, self.held_for, self.pending = pos, 0, []
                return TrackPoint(game_sec, video_sec, *pos, det.score, "detected")

            # Too far to be a normal step. Remember it; accept once it repeats.
            self.pending.append(pos)
            if len(self.pending) >= self.reacquire_frames and _cluster_tight(self.pending, self.max_jump * 2):
                self.last, self.held_for, self.pending = pos, 0, []
                return TrackPoint(game_sec, video_sec, *pos, det.score, "reacquired")
            # Otherwise treat this frame like a miss.

        if self.last is not None and self.held_for < self.max_hold:
            self.held_for += 1
            return TrackPoint(game_sec, video_sec, *self.last, det.score, "held")

        return TrackPoint(game_sec, video_sec, None, None, det.score, "gap")


def _cluster_tight(points: list[tuple[float, float]], radius: float) -> bool:
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return all(((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 <= radius for p in points)
