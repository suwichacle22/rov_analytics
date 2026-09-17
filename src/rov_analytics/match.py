"""Match manifest: which video, which source layout, and who played which hero.

One JSON per game, filled in from the draft screen. Lets you ask for a player by name
and have the tool resolve player -> hero -> template.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PlayerEntry:
    player: str
    hero: str
    side: str            # "blue" or "red"
    role: str = ""       # free text: jungle, mid, dark slayer lane, abyssal dragon lane, roam


@dataclass
class MatchManifest:
    match_id: str
    video: str
    source: str                      # path to the SourceConfig JSON
    game_start: float = 0.0          # video second where the in-game clock reads 0:00
    end: float | None = None         # video second to stop at (default: end of file)
    players: list[PlayerEntry] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> MatchManifest:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        players = [PlayerEntry(**p) for p in data.get("players", [])]
        return cls(
            match_id=data.get("match_id") or Path(path).stem,
            video=data["video"],
            source=data["source"],
            game_start=float(data.get("game_start", 0.0)),
            end=data.get("end"),
            players=players,
            notes=data.get("notes", ""),
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def find_player(self, name: str) -> PlayerEntry:
        wanted = name.strip().lower()
        for p in self.players:
            if p.player.lower() == wanted or p.player.lower().endswith(wanted):
                return p
        raise ValueError(f"player '{name}' not in manifest. Known: {[p.player for p in self.players]}")

    def find_hero(self, hero: str) -> PlayerEntry:
        wanted = hero.strip().lower()
        for p in self.players:
            if p.hero.lower() == wanted:
                return p
        raise ValueError(f"hero '{hero}' not in manifest. Known: {[p.hero for p in self.players]}")


def example_manifest(match_id: str, video: str, source: str) -> MatchManifest:
    roles = ["dark slayer lane", "jungle", "mid", "abyssal dragon lane", "roam"]
    players = [PlayerEntry(f"BLUE player {i+1}", f"hero{i+1}", "blue", r) for i, r in enumerate(roles)]
    players += [PlayerEntry(f"RED player {i+1}", f"hero{i+6}", "red", r) for i, r in enumerate(roles)]
    return MatchManifest(match_id, video, source, players=players, notes="Fill in player names and hero names from the draft screen.")
