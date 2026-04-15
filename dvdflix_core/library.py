from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .clients import TmdbClient
from .encoder import get_video_codec, get_video_resolution
from .nfo import _parse_folder_title_year

TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w300"


def _normalize_name(name: str) -> str:
    return re.sub(r"[_.]+", " ", name).strip()


def _needs_rename(name: str) -> bool:
    if "__" in name or " _" in name or "_" in name or "." in name:
        return True
    if "  " in name:
        return True
    return False


EXTRA_FOLDER_NAMES = {
    "extras",
    "extra",
    "bonus features",
    "bonus",
    "special features",
    "special feature",
    "deleted scenes",
    "deleted scene",
    "behind the scenes",
    "featurettes",
    "trailer",
    "trailers",
}


def _is_extra_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return any(part.lower() in EXTRA_FOLDER_NAMES for part in rel.parts)


def _is_h265_encoded(src: Path) -> bool:
    if src.name.lower().endswith(".x265.mkv"):
        return True
    try:
        codec = get_video_codec(src)
        return codec in {"hevc", "h265", "x265"}
    except Exception:
        return False


def _needs_encode(mkv_paths: list[Path]) -> bool:
    for path in mkv_paths:
        if _is_h265_encoded(path):
            continue
        try:
            _, height = get_video_resolution(path)
            if height <= 720:
                continue
        except Exception:
            return True
        return True
    return False


def _build_poster_url(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return f"{TMDB_POSTER_BASE}{poster_path}"


def _fetch_tmdb_info(title: str, year: int | None, media_type: str, tmdb_api_key: str) -> dict[str, Any]:
    if not tmdb_api_key:
        return {}

    client = TmdbClient(tmdb_api_key)
    if media_type == "tv":
        candidates = client.search_tv(title)
    else:
        candidates = client.search_movie(title)

    if not candidates:
        return {}

    candidate = candidates[0]
    if year is not None:
        for item in candidates:
            release_year = str(item.get("first_air_date", ""))[:4] if media_type == "tv" else str(item.get("release_date", ""))[:4]
            if release_year == str(year):
                candidate = item
                break

    details = None
    if media_type == "tv":
        details = client.tv_details(int(candidate["id"]))
    else:
        details = client.movie_details(int(candidate["id"]))

    if not details:
        details = candidate

    return {
        "title": details.get("name") if media_type == "tv" else details.get("title", title),
        "year": int(str(details.get("first_air_date", ""))[:4]) if media_type == "tv" else int(str(details.get("release_date", ""))[:4]) if details.get("release_date") else year,
        "overview": details.get("overview", ""),
        "poster": _build_poster_url(details.get("poster_path")),
        "genres": [g.get("name") for g in details.get("genres", []) if g.get("name")],
        "rating": details.get("vote_average"),
        "tmdb_id": details.get("id"),
        "tmdb_type": media_type,
    }


def _scan_folder_item(path: Path, root: Path, media_type: str, tmdb_api_key: str) -> dict[str, Any] | None:
    mkv_paths = sorted(p for p in path.rglob("*.mkv") if not _is_extra_path(p, path))
    if not mkv_paths:
        return None

    title, year = _parse_folder_title_year(path.name)
    metadata = _fetch_tmdb_info(title, year, media_type, tmdb_api_key)
    item = {
        "path": str(path.relative_to(root)),
        "media_type": media_type,
        "title": metadata.get("title", title),
        "year": metadata.get("year", year),
        "overview": metadata.get("overview", ""),
        "poster": metadata.get("poster"),
        "genres": metadata.get("genres", []),
        "rating": metadata.get("rating"),
        "tmdb_id": metadata.get("tmdb_id"),
        "needs_encode": _needs_encode(mkv_paths),
        "needs_rename": _needs_rename(path.name),
        "file_count": len(mkv_paths),
        "item_type": "folder",
    }
    return item


def _scan_file_item(path: Path, root: Path, media_type: str, tmdb_api_key: str) -> dict[str, Any] | None:
    if path.suffix.lower() != ".mkv":
        return None

    title, year = _parse_folder_title_year(path.stem)
    metadata = _fetch_tmdb_info(title, year, media_type, tmdb_api_key)
    item = {
        "path": str(path.relative_to(root)),
        "media_type": media_type,
        "title": metadata.get("title", title),
        "year": metadata.get("year", year),
        "overview": metadata.get("overview", ""),
        "poster": metadata.get("poster"),
        "genres": metadata.get("genres", []),
        "rating": metadata.get("rating"),
        "tmdb_id": metadata.get("tmdb_id"),
        "needs_encode": not path.name.lower().endswith(".x265.mkv"),
        "needs_rename": _needs_rename(path.name),
        "file_count": 1,
        "item_type": "file",
    }
    return item


def discover_media_items(root: Path, media_type: str, tmdb_api_key: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            item = _scan_folder_item(child, root, media_type, tmdb_api_key)
            if item:
                items.append(item)
        elif child.is_file() and child.suffix.lower() == ".mkv":
            item = _scan_file_item(child, root, media_type, tmdb_api_key)
            if item:
                items.append(item)

    return items
