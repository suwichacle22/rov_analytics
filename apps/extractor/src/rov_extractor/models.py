from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# The match type of a series. "regular" stays valid for series entered before legs were recorded.
STAGES = [
    {"id": "regular", "name": "Regular season", "short": "Regular"},
    {"id": "leg1", "name": "Leg 1", "short": "Leg 1"},
    {"id": "leg2", "name": "Leg 2", "short": "Leg 2"},
    {"id": "playoffs", "name": "Playoff", "short": "Playoff"},
    {"id": "final", "name": "Final", "short": "Final"},
]
Stage = Literal["regular", "leg1", "leg2", "playoffs", "final"]


class Series(BaseModel):
    seriesId: str
    tournament: str
    stage: Stage = "regular"
    bestOf: int = 5
    date: str
    dateManual: bool = False  # typed by hand, so Recognise leaves it alone
    patch: str = ""
    teamA: str
    teamB: str
    homeTeam: str
    vodUrl: str = ""
    layout: str = "rpl2026"
    notes: str = ""
    winner: Optional[str] = None


class SeriesCreate(BaseModel):
    tournament: str
    stage: Stage = "regular"
    bestOf: int = 5
    date: str
    dateManual: bool = False
    patch: str = ""
    teamA: str
    teamB: str
    homeTeam: str
    vodUrl: str = ""
    notes: str = ""


class BanEntry(BaseModel):
    hero: Optional[str] = None
    form: Optional[str] = None
    confirmed: bool = False  # chosen by hand or confirmed by the user, so review.py leaves it alone


class PickEntry(BaseModel):
    hero: Optional[str] = None
    player: Optional[str] = None
    confirmed: bool = False


class Slots(BaseModel):
    blueBans: list[BanEntry] = Field(default_factory=lambda: [BanEntry() for _ in range(4)])
    redBans: list[BanEntry] = Field(default_factory=lambda: [BanEntry() for _ in range(4)])
    bluePicks: list[PickEntry] = Field(default_factory=lambda: [PickEntry() for _ in range(5)])
    redPicks: list[PickEntry] = Field(default_factory=lambda: [PickEntry() for _ in range(5)])


class PlayerRow(BaseModel):
    team: str
    player: Optional[str] = None
    hero: Optional[str] = None
    lane: Optional[str] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    dmgDealt: Optional[int] = None
    dmgTaken: Optional[int] = None
    items: list[str] = Field(default_factory=list)
    confirmed: bool = False  # the player name was typed or confirmed by the user


class TeamStat(BaseModel):
    kills: Optional[int] = None
    gold: Optional[int] = None
    towers: Optional[int] = None
    dragons: Optional[int] = None
    slayers: Optional[int] = None


class GameInput(BaseModel):
    """What the form sends. The server derives the sequence and writes the game JSON."""

    gameNo: int
    blueTeam: str
    winner: Optional[str] = None
    durationS: Optional[int] = None
    patch: Optional[str] = None
    slots: Slots = Field(default_factory=Slots)
    players: list[PlayerRow] = Field(default_factory=list)
    teamStats: dict[str, TeamStat] = Field(default_factory=dict)
    images: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    field: Optional[str] = None
