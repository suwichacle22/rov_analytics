"""Matches from a list of broadcast links.

`data/links.txt` holds one link per line: a broadcast video or a playlist of them. Every match a
broadcast holds is read from its chapter titles ("KOG vs BRU เริ่มดราฟเกม 1"), so nobody has to
type the teams, the date or the time of each match. A line `stage: leg1`, `bestof: 5` or
`tournament: rpl-2026-winter` applies to the links below it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import refdata, source, store
from .grab import CHAPTER_RE
from .models import STAGES, SeriesCreate
from .paths import data_dir

DIRECTIVE_RE = re.compile(r"^(stage|bestof|tournament)\s*[:=]\s*(\S+)$", re.IGNORECASE)


def links_path() -> Path:
    return data_dir() / "links.txt"


@dataclass
class Link:
    url: str
    line: int
    stage: str = "regular"
    best_of: int = 5
    tournament: str = ""


@dataclass
class Found:
    """One match named in the chapters of a broadcast."""
    team_a: str
    team_b: str
    start: float          # seconds into the video where its first draft starts
    games: int
    unknown: list[str] = field(default_factory=list)  # chapter names that are no team id


def read_links(path: Path) -> list[Link]:
    """Links with the settings in force at their line. A bad directive raises ValueError."""
    tournaments = [t["id"] for t in refdata.tournaments()]
    stage, best_of, tournament = "regular", 5, tournaments[0] if tournaments else ""
    out: list[Link] = []
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = DIRECTIVE_RE.match(line)
        if m:
            key, value = m.group(1).lower(), m.group(2)
            if key == "stage":
                if value not in {s["id"] for s in STAGES}:
                    raise ValueError(f"line {no}: stage must be one of {', '.join(s['id'] for s in STAGES)}")
                stage = value
            elif key == "bestof":
                if not value.isdigit() or int(value) not in (1, 3, 5, 7):
                    raise ValueError(f"line {no}: bestof must be 1, 3, 5 or 7")
                best_of = int(value)
            else:
                if value not in tournaments:
                    raise ValueError(f"line {no}: tournament must be one of {', '.join(tournaments)}")
                tournament = value
            continue
        if not re.match(r"https?://", line):
            raise ValueError(f"line {no}: not a link: {line}")
        out.append(Link(line, no, stage, best_of, tournament))
    return out


def matches_in(info: dict[str, Any]) -> list[Found]:
    """Every team pair named in the chapters, in the order the matches were played."""
    ids = {t["id"].upper(): t["id"] for t in refdata.teams()}
    found: dict[frozenset[str], Found] = {}
    for c in info.get("chapters") or []:
        m = CHAPTER_RE.match(c.get("title") or "")
        if not m:
            continue
        a, b, game = m.group(1).upper(), m.group(2).upper(), int(m.group(4))
        key = frozenset((a, b))
        if key not in found:
            found[key] = Found(ids.get(a, a), ids.get(b, b), float(c["start_time"]), game, [x for x in (a, b) if x not in ids])
        f = found[key]
        f.start, f.games = min(f.start, float(c["start_time"])), max(f.games, game)
    return sorted(found.values(), key=lambda f: f.start)


def video_link(info: dict[str, Any], start: float) -> str:
    """A clean link to the video, opening where the match starts."""
    vid = info.get("id") or parse_qs(urlparse(info.get("webpage_url") or info.get("original_url") or "").query).get("v", [""])[0]
    return f"https://www.youtube.com/watch?v={vid}&t={int(start)}s" if vid else info.get("webpage_url") or ""


def existing(date: str, team_a: str, team_b: str) -> str | None:
    """Id of the match on disk with these teams on this day, if any."""
    for s in store.list_series():
        if s["date"] == date and {s["teamA"], s["teamB"]} == {team_a, team_b}:
            return s["seriesId"]
    return None


def import_links(path: Path | None = None, grab: bool = False, dry_run: bool = False,
                 say: Callable[[str], None] = lambda line: print(line, flush=True)) -> int:
    """Create every match the linked broadcasts hold that is not on disk yet. With `grab`, take the
    screenshots of every match found, new or old; games that have theirs are skipped by grab itself.
    Returns the number of problems."""
    path = path or links_path()
    if not path.exists():
        say(f"{path} does not exist. Put one broadcast or playlist link per line in it.")
        return 1
    try:
        links = read_links(path)
    except ValueError as e:
        say(f"{path.name}: {e}")
        return 1
    if not links:
        say(f"{path.name} holds no link.")
        return 1
    problems, created, todo = 0, 0, []
    for link in links:
        videos = source.video_links(link.url)
        if not videos:
            say(f"line {link.line}: cannot read {link.url}")
            problems += 1
            continue
        for url in videos:
            info = source.video_info(url)
            date = source.video_day(info) if info else None
            if not info or not date:
                say(f"line {link.line}: cannot read {url}")
                problems += 1
                continue
            found = matches_in(info)
            say(f"{date}  {info.get('title') or url}")
            if not found:
                say("      no match chapters in this video")
                continue
            for f in found:
                label = f"{f.team_a} vs {f.team_b}"
                if f.unknown:
                    say(f"      {label}: unknown team {', '.join(f.unknown)}, add it to data/ref/teams.json")
                    problems += 1
                    continue
                sid = existing(date, f.team_a, f.team_b)
                if sid:
                    say(f"      {label}: already there as {sid}")
                    todo.append(sid)
                    continue
                s = SeriesCreate(tournament=link.tournament, stage=link.stage, bestOf=link.best_of, date=date,
                                 teamA=f.team_a, teamB=f.team_b, homeTeam=f.team_a, vodUrl=video_link(info, f.start))
                if dry_run:
                    say(f"      {label}: would create {store.series_id_for(s)}, {f.games} games, {_stage_name(link.stage)} Bo{link.best_of}")
                    continue
                series = store.create_series(s)
                created += 1
                todo.append(series.seriesId)
                say(f"      {label}: created {series.seriesId}, {f.games} games, {_stage_name(link.stage)} Bo{link.best_of}")
    say(f"{created} match{'es' if created != 1 else ''} created")
    if grab and not dry_run:
        from .grab import grab as grab_match

        for sid in todo:
            say("")
            problems += grab_match(sid, say=say)
    return problems


def _stage_name(stage: str) -> str:
    return next((s["short"] for s in STAGES if s["id"] == stage), stage)
