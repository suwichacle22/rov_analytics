"""The video a match was taken from. The screenshots carry no date, so the day of the match is
read from the source link, and the chapter list of a broadcast says which matches it holds."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# A broadcast that starts in the evening is already the next day in UTC for some leagues, so the
# day is taken where the league plays. RPL is broadcast from Thailand.
BROADCAST_TZ = timezone(timedelta(hours=7))

_infos: dict[str, dict[str, Any]] = {}


class _Silent:
    def debug(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def video_info(url: str) -> dict[str, Any] | None:
    """Title, date and chapters of a video, or the entries of a playlist, without the stream list.
    None when the link cannot be read."""
    url = (url or "").strip()
    if not url:
        return None
    if url not in _infos:
        try:
            from yt_dlp import YoutubeDL

            with YoutubeDL({"quiet": True, "no_warnings": True, "logger": _Silent(), "skip_download": True, "noplaylist": True,
                            "extract_flat": "in_playlist", "socket_timeout": 15}) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
                if info and info.get("_type") in ("playlist", "multi_video"):
                    info = ydl.process_ie_result(info, download=False)
        except Exception:  # noqa: BLE001
            return None
        if not info:
            return None
        _infos[url] = info
    return _infos[url]


def video_day(info: dict[str, Any]) -> str | None:
    stamp = info.get("release_timestamp") or info.get("timestamp")
    day = info.get("release_date") or info.get("upload_date")
    if stamp:
        return datetime.fromtimestamp(stamp, BROADCAST_TZ).date().isoformat()
    if day and len(day) == 8:
        return f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return None


def video_date(url: str) -> str | None:
    """Day the video went live or was published, as YYYY-MM-DD, or None when it cannot be read."""
    info = video_info(url)
    return video_day(info) if info else None


def video_links(url: str) -> list[str]:
    """The link itself, or every video of a playlist link."""
    info = video_info(url)
    if not info:
        return []
    if info.get("_type") in ("playlist", "multi_video"):
        out = []
        for e in info.get("entries") or []:
            if e and (e.get("url") or e.get("id")):
                out.append(e.get("url") or f"https://www.youtube.com/watch?v={e['id']}")
        return out
    return [url]
