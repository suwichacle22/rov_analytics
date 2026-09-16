"""Source configuration: where the minimap sits on screen and what the team rings look like.

One SourceConfig describes one video source (a tournament broadcast layout, a phone
recording layout, ...). It is created once with `rov calibrate` and reused for every
video from that source.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class HsvRange:
    """Inclusive HSV bounds in OpenCV scale: H 0-179, S 0-255, V 0-255."""

    low: list[int]
    high: list[int]


# OpenCV hue for red wraps around 0, so red needs two ranges.
DEFAULT_RING_RANGES: dict[str, list[HsvRange]] = {
    "blue": [HsvRange([95, 90, 90], [130, 255, 255])],
    "red": [HsvRange([0, 90, 90], [10, 255, 255]), HsvRange([170, 90, 90], [179, 255, 255])],
}


@dataclass
class SourceConfig:
    name: str
    # Minimap bounding box in full-frame pixels: x, y, width, height.
    minimap_box: list[int]
    # Approximate hero icon diameter in minimap pixels (ring included).
    icon_diameter_px: int = 22
    ring_ranges: dict[str, list[HsvRange]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_RING_RANGES.items()}
    )
    notes: str = ""

    @property
    def crop_size(self) -> tuple[int, int]:
        return self.minimap_box[2], self.minimap_box[3]

    def to_json(self) -> str:
        data = asdict(self)
        return json.dumps(data, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> SourceConfig:
        ranges = {
            side: [HsvRange(r["low"], r["high"]) for r in rs]
            for side, rs in data.get("ring_ranges", {}).items()
        }
        if not ranges:
            ranges = {k: list(v) for k, v in DEFAULT_RING_RANGES.items()}
        return cls(
            name=data["name"],
            minimap_box=list(data["minimap_box"]),
            icon_diameter_px=int(data.get("icon_diameter_px", 22)),
            ring_ranges=ranges,
            notes=data.get("notes", ""),
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> SourceConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
