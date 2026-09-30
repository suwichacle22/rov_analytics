"""The video a match was taken from. The screenshots carry no date, so the day of the match is
read from the source link."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# A broadcast that starts in the evening is already the next day in UTC for some leagues, so the
# day is taken where the league plays. RPL is broadcast from Thailand.
BROADCAST_TZ = timezone(timedelta(hours=7))

_dates: dict[str, str] = {}


class _Silent:
    def debug(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def video_date(url: str) -> str | None:
    """Day the video went live or was published, as YYYY-MM-DD, or None when it cannot be read."""
    url = (url or "").strip()
    if not url:
        return None
    if url not in _dates:
        try:
            from yt_dlp import YoutubeDL

            with YoutubeDL({"quiet": True, "no_warnings": True, "logger": _Silent(), "skip_download": True, "noplaylist": True, "socket_timeout": 15}) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
        except Exception:  # noqa: BLE001
            return None
        stamp = info.get("release_timestamp") or info.get("timestamp")
        day = info.get("release_date") or info.get("upload_date")
        if stamp:
            _dates[url] = datetime.fromtimestamp(stamp, BROADCAST_TZ).date().isoformat()
        elif day and len(day) == 8:
            _dates[url] = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        else:
            return None
    return _dates[url]
