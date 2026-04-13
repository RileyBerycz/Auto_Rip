from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .clients import TmdbClient


def _escape(text: str | None) -> str:
    if text is None:
        return ""
    return html.escape(text.strip())


def _parse_folder_title_year(folder_name: str) -> tuple[str, int | None]:
    match = re.match(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$", folder_name)
    if match:
        return match.group("title").strip(), int(match.group("year"))
    return folder_name.strip(), None


def _build_movie_nfo(movie_info: dict[str, Any]) -> str:
    tmdb_id = movie_info.get("tmdb_id")
    imdb_id = movie_info.get("imdb_id")
    genres = movie_info.get("genres") or []
    runtime = movie_info.get("runtime") or 0

    lines = ["<?xml version=\"1.0\" encoding=\"utf-8\"?>", "<movie>"]
    lines.append(f"  <title>{_escape(movie_info.get('title'))}</title>")
    lines.append(f"  <originaltitle>{_escape(movie_info.get('original_title') or movie_info.get('title'))}</originaltitle>")
    if movie_info.get("year"):
        lines.append(f"  <year>{movie_info['year']}</year>")
    if movie_info.get("tagline"):
        lines.append(f"  <tagline>{_escape(movie_info['tagline'])}</tagline>")
    if movie_info.get("plot"):
        lines.append(f"  <plot>{_escape(movie_info['plot'])}</plot>")
    if runtime:
        lines.append(f"  <runtime>{int(runtime)}</runtime>")
    for genre in genres[:5]:
        if genre:
            lines.append(f"  <genre>{_escape(genre)}</genre>")
    if movie_info.get("rating") is not None:
        lines.append(f"  <rating>{movie_info['rating']}</rating>")
    if movie_info.get("studio"):
        lines.append(f"  <studio>{_escape(movie_info['studio'])}</studio>")
    if imdb_id:
        lines.append(f"  <imdbid>{_escape(imdb_id)}</imdbid>")
        lines.append(f"  <urlimdb>https://www.imdb.com/title/{_escape(imdb_id)}/</urlimdb>")
    if tmdb_id:
        lines.append(f"  <uniqueid type=\"tmdb\">{_escape(str(tmdb_id))}</uniqueid>")
    lines.append("</movie>")
    return "\n".join(lines)


def _build_tvshow_nfo(show_info: dict[str, Any]) -> str:
    tmdb_id = show_info.get("tmdb_id")
    imdb_id = show_info.get("imdb_id")
    genres = show_info.get("genres") or []
    runtime = show_info.get("episode_run_time") or []
    lines = ["<?xml version=\"1.0\" encoding=\"utf-8\"?>", "<tvshow>"]
    lines.append(f"  <title>{_escape(show_info.get('name'))}</title>")
    if show_info.get("first_air_date"):
        year = show_info.get("first_air_date")[:4]
        if year.isdigit():
            lines.append(f"  <year>{year}</year>")
    if show_info.get("overview"):
        lines.append(f"  <plot>{_escape(show_info.get('overview'))}</plot>")
    if genres:
        for genre in genres[:5]:
            if genre:
                lines.append(f"  <genre>{_escape(genre)}</genre>")
    if runtime:
        lines.append(f"  <runtime>{int(runtime[0])}</runtime>")
    if imdb_id:
        lines.append(f"  <imdbid>{_escape(imdb_id)}</imdbid>")
    if tmdb_id:
        lines.append(f"  <uniqueid type=\"tmdb\">{_escape(str(tmdb_id))}</uniqueid>")
    lines.append("</tvshow>")
    return "\n".join(lines)


def _fetch_movie_info(title: str, year: int | None, tmdb_api_key: str) -> dict[str, Any] | None:
    if not tmdb_api_key:
        return None
    client = TmdbClient(tmdb_api_key)
    candidates = client.search_movie(title)
    if not candidates:
        return None
    if year is not None:
        for candidate in candidates:
            if str(candidate.get("release_date", ""))[:4] == str(year):
                return candidate
    return candidates[0]


def _fetch_tv_info(title: str, year: int | None, tmdb_api_key: str) -> dict[str, Any] | None:
    if not tmdb_api_key:
        return None
    client = TmdbClient(tmdb_api_key)
    candidates = client.search_tv(title)
    if not candidates:
        return None
    if year is not None:
        for candidate in candidates:
            if str(candidate.get("first_air_date", ""))[:4] == str(year):
                return candidate
    return candidates[0]


def create_movie_nfo(output_dir: Path, title: str, year: int | None, tmdb_api_key: str) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = output_dir / "movie.nfo"
    if nfo_path.exists():
        return False

    movie_info = {
        "title": title,
        "year": year,
        "plot": "",
    }
    candidate = _fetch_movie_info(title, year, tmdb_api_key)
    if candidate is not None:
        details = TmdbClient(tmdb_api_key).movie_details(int(candidate["id"]))
        if details:
            movie_info = {
                "title": details.get("title", title),
                "original_title": details.get("original_title", details.get("title", title)),
                "year": int(str(details.get("release_date", ""))[:4]) if details.get("release_date") else year,
                "plot": details.get("overview", ""),
                "tagline": details.get("tagline", ""),
                "runtime": details.get("runtime", 0),
                "genres": [g.get("name") for g in details.get("genres", []) if g.get("name")],
                "rating": details.get("vote_average"),
                "studio": (details.get("production_companies") or [{}])[0].get("name", ""),
                "tmdb_id": details.get("id"),
                "imdb_id": details.get("imdb_id", ""),
            }
    else:
        movie_info["tmdb_id"] = None
        movie_info["imdb_id"] = ""

    try:
        nfo_path.write_text(_build_movie_nfo(movie_info), encoding="utf-8")
        return True
    except OSError:
        return False


def create_tvshow_nfo(output_dir: Path, title: str, year: int | None, tmdb_api_key: str) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = output_dir / "tvshow.nfo"
    if nfo_path.exists():
        return False

    show_info = {"name": title, "first_air_date": f"{year}-01-01" if year else "", "overview": ""}
    candidate = _fetch_tv_info(title, year, tmdb_api_key)
    if candidate is not None:
        details = TmdbClient(tmdb_api_key).tv_details(int(candidate["id"]))
        if details:
            show_info = {
                "name": details.get("name", title),
                "first_air_date": details.get("first_air_date", ""),
                "overview": details.get("overview", ""),
                "genres": [g.get("name") for g in details.get("genres", []) if g.get("name")],
                "episode_run_time": details.get("episode_run_time", []),
                "tmdb_id": details.get("id"),
                "imdb_id": details.get("external_ids", {}).get("imdb_id", "") if details.get("external_ids") else "",
            }
    else:
        show_info["tmdb_id"] = None
        show_info["imdb_id"] = ""

    try:
        nfo_path.write_text(_build_tvshow_nfo(show_info), encoding="utf-8")
        return True
    except OSError:
        return False


def create_nfo_for_job(output_dir: Path, title: str, media_type: str, year: int | None, tmdb_api_key: str) -> bool:
    if media_type == "tv":
        return create_tvshow_nfo(output_dir, title, year, tmdb_api_key)
    return create_movie_nfo(output_dir, title, year, tmdb_api_key)


def create_nfo_for_library(root: Path, tmdb_api_key: str) -> int:
    generated = 0
    if not root.exists():
        return generated

    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue

        movie_files = list(folder.glob("*.mkv"))
        if movie_files:
            title, year = _parse_folder_title_year(folder.name)
            if create_movie_nfo(folder, title, year, tmdb_api_key):
                generated += 1
            continue

        tv_root = False
        for child in folder.iterdir():
            if child.is_dir() and any(child.glob("*.mkv")):
                tv_root = True
                break
        if tv_root:
            title, year = _parse_folder_title_year(folder.name)
            if create_tvshow_nfo(folder, title, year, tmdb_api_key):
                generated += 1

    return generated
