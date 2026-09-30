from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("ROV_DATA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "ref").is_dir():
            return parent
    return Path.cwd()


def data_dir() -> Path:
    return repo_root() / "data"


def ref_dir() -> Path:
    return data_dir() / "ref"


def series_dir() -> Path:
    d = data_dir() / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d
