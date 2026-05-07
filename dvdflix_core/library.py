from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .clients import TmdbClient
from .encoder import get_video_codec, get_video_resolution
from .nfo import _parse_folder_title_year

TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w300"


def _extract_encoding_specs(mkv_path: Path) -> dict[str, Any]:
    """Extract codec, resolution, and other encoding specs from MKV file."""
    specs = {
        "codec": None,
        "resolution": None,
        "encoded": False,
    }
    try:
        codec = get_video_codec(mkv_path)
        specs["codec"] = codec
        specs["encoded"] = codec and "hevc" in codec.lower() if codec else False
        
        width, height = get_video_resolution(mkv_path)
        if width and height:
            specs["resolution"] = f"{width}x{height}"
            # Detect if it's HD, Full HD, 4K, etc
            if height >= 2160:
                specs["quality_tier"] = "4K"
            elif height >= 1080:
                specs["quality_tier"] = "1080p"
            elif height >= 720:
                specs["quality_tier"] = "720p"
            else:
                specs["quality_tier"] = "SD"
    except Exception:
        pass
    return specs


def _needs_rename(name: str, path: Path | None = None, ollama_url: str = "", ollama_model: str = "qwen2.5:7b", ai_provider: str = "ollama", openrouter_api_key: str = "", openrouter_model: str = "google/gemini-2.0-flash-001") -> tuple[bool, str | None, str | None]:
    """Check if item needs renaming and return reason + AI suggestion."""
    # Check for bad characters/patterns
    if "__" in name or " _" in name or name.startswith("_") or name.endswith("_"):
        # Try to get AI suggestion
        suggestion = _get_ai_name_suggestion(
            current_name=name,
            file_samples=[str(p) for p in (path.iterdir() if path and path.is_dir() else [])],
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            ai_provider=ai_provider,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
        )
        return True, "Contains underscores or double underscores", suggestion
    if "." in name:
        suggestion = _get_ai_name_suggestion(
            current_name=name,
            file_samples=None,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            ai_provider=ai_provider,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
        )
        return True, "Contains dots (not standard naming)", suggestion
    if "  " in name:
        suggestion = _get_ai_name_suggestion(
            current_name=name,
            file_samples=None,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            ai_provider=ai_provider,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
        )
        return True, "Contains double spaces", suggestion
    
    # Check for generic ripper names (G1_t00, title_t00, etc.)
    if re.match(r"^[Gg]\d+_t\d+$|^title_t\d+$|^track_\d+$", name.lower()):
        suggestion = _get_ai_name_suggestion(
            current_name=name,
            file_samples=[str(p) for p in (path.iterdir() if path and path.is_dir() else [])],
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            ai_provider=ai_provider,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
        )
        return True, f"Generic ripper name: {name}", suggestion
    
    # Check for extras/specials folders that shouldn't be in main library
    name_lower = name.lower()
    EXTRA_KEYWORDS = ["extra", "bonus", "special", "feature", "trailer", "deleted scene"]
    if any(keyword in name_lower for keyword in EXTRA_KEYWORDS):
        return True, f"Appears to be extras/special features: {name}", None
    
    # Check if parent folder indicates this is in wrong location
    if path and path.parent:
        parent_name = path.parent.name.lower()
        if any(keyword in parent_name for keyword in EXTRA_KEYWORDS):
            return True, f"Parent folder suggests extras/specials: {path.parent.name}", None
    
    return False, None, None


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


def _needs_encode(mkv_paths: list[Path]) -> tuple[bool, str | None]:
    """Check if any video file needs encoding (MPEG-2, MPEG-4, VC-1, etc. - anything not HEVC)."""
    for path in mkv_paths:
        try:
            codec = get_video_codec(path)
            # If already HEVC/H.265, check if file is still too large
            if codec and codec.lower() in {"hevc", "h265", "x265"}:
                # Check file size - if > 5GB for movie or > 2GB for TV episode, still encode
                size_gb = path.stat().st_size / (1024**3)
                if size_gb > 5:  # Movies > 5GB or TV episodes > 2GB might benefit from re-encoding
                    return True, f"HEVC file still too large: {size_gb:.1f}GB"
                return False, None  # HEVC and reasonable size - no encode needed
            # Non-HEVC codecs need encoding
            if not codec or codec.lower() not in {"hevc", "h265", "x265"}:
                return True, f"Codec is {codec} (not HEVC)"
        except Exception:
            # If we can't determine codec, assume it needs encoding to be safe
            return True, "Error reading codec"
    return False, None


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
    
    # Check if this is a generic ripper name
    stem = path.name
    is_generic = bool(re.match(r"^[Gg]\d+$|^title$|^track_\d+$", stem))
    
    # If generic name, try to get AI suggestion
    suggested_name = None
    if is_generic or not title or title == stem:
        settings = _get_settings()
        if settings:
            suggested_name = _get_ai_name_suggestion(
                current_name=stem,
                file_samples=[p.name for p in mkv_paths[:5]],
                ollama_url=settings.ollama_url,
                ollama_model=settings.ollama_model,
                ai_provider=settings.ai_provider,
                openrouter_api_key=settings.openrouter_api_key,
                openrouter_model=settings.openrouter_model,
            )
            if suggested_name and suggested_name != stem:
                # Parse the AI suggestion
                title, year = _parse_folder_title_year(suggested_name)
    
    metadata = _fetch_tmdb_info(title, year, media_type, tmdb_api_key)
    
    # Get encoding specs from first MKV file
    encoding_specs = _extract_encoding_specs(mkv_paths[0])
    needs_encode, encode_reason = _needs_encode(mkv_paths)
    
    # Get settings for AI name suggestion
    settings = _get_settings()
    ollama_url = settings.ollama_url if settings else ""
    ollama_model = settings.ollama_model if settings else "qwen2.5:7b"
    ai_provider = settings.ai_provider if settings else "ollama"
    openrouter_api_key = settings.openrouter_api_key if settings else ""
    openrouter_model = settings.openrouter_model if settings else "google/gemini-2.0-flash-001"
    
    needs_rename, rename_reason, ai_suggestion = _needs_rename(
        path.name, path, ollama_url, ollama_model, ai_provider, openrouter_api_key, openrouter_model
    )
    
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
        "needs_encode": needs_encode,
        "encode_reason": encode_reason,
        "needs_rename": needs_rename,
        "rename_reason": rename_reason or (f"Generic ripper name: {stem}" if is_generic else None),
        "suggested_name": suggested_name if suggested_name and suggested_name != stem else (ai_suggestion if ai_suggestion and ai_suggestion != stem else None),
        "file_count": len(mkv_paths),
        "item_type": "folder",
        "encoding_specs": encoding_specs,
    }
    return item


def _scan_file_item(path: Path, root: Path, media_type: str, tmdb_api_key: str) -> dict[str, Any] | None:
    if path.suffix.lower() != ".mkv":
        return None

    # Check if this is a generic ripper name (G1_t00, title_t00, etc.)
    stem = path.stem
    is_generic = bool(re.match(r"^[Gg]\d+_t\d+$|^title_t\d+$|^track_\d+$", stem))
    
    title, year = _parse_folder_title_year(stem)
    
    # If generic name or parse failed, try to get AI suggestion
    suggested_name = None
    if is_generic or not title or title == stem:
        settings = _get_settings()
        if settings:
            suggested_name = _get_ai_name_suggestion(
                current_name=stem,
                file_samples=[path.name],
                ollama_url=settings.ollama_url,
                ollama_model=settings.ollama_model,
                ai_provider=settings.ai_provider,
                openrouter_api_key=settings.openrouter_api_key,
                openrouter_model=settings.openrouter_model,
            )
            if suggested_name and suggested_name != stem:
                # Parse the AI suggestion
                title, year = _parse_folder_title_year(suggested_name)
    
    metadata = _fetch_tmdb_info(title, year, media_type, tmdb_api_key)
    
    # Get encoding specs from this MKV file
    encoding_specs = _extract_encoding_specs(path)
    needs_encode, encode_reason = _needs_encode([path])
    
    # Get settings for AI name suggestion
    settings = _get_settings()
    ollama_url = settings.ollama_url if settings else ""
    ollama_model = settings.ollama_model if settings else "qwen2.5:7b"
    ai_provider = settings.ai_provider if settings else "ollama"
    openrouter_api_key = settings.openrouter_api_key if settings else ""
    openrouter_model = settings.openrouter_model if settings else "google/gemini-2.0-flash-001"
    
    needs_rename, rename_reason, ai_suggestion = _needs_rename(
        path.name, path, ollama_url, ollama_model, ai_provider, openrouter_api_key, openrouter_model
    )
    
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
        "needs_encode": needs_encode,
        "encode_reason": encode_reason,
        "needs_rename": needs_rename,
        "rename_reason": rename_reason or (f"Generic ripper name: {stem}" if is_generic else None),
        "suggested_name": suggested_name if suggested_name and suggested_name != stem else (ai_suggestion if ai_suggestion and ai_suggestion != stem else None),
        "file_count": 1,
        "item_type": "file",
        "encoding_specs": encoding_specs,
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


def _get_settings() -> Settings | None:
    """Get settings from environment or config."""
    try:
        from .config import Settings
        return Settings()
    except Exception:
        return None


def _get_ai_name_suggestion(
    current_name: str,
    file_samples: list[str] = None,
    ollama_url: str = "",
    ollama_model: str = "qwen2.5:7b",
    ai_provider: str = "ollama",
    openrouter_api_key: str = "",
    openrouter_model: str = "google/gemini-2.0-flash-001",
) -> str | None:
    """Use AI to suggest a clean folder name. Supports Ollama and OpenRouter."""
    
    prompt = (
        "You are a folder renaming assistant for a movie/TV library. "
        "Given the current folder name and optional file samples, suggest a clean folder name. "
        "Return ONLY the suggested folder name in format: 'Title (Year)' if year is detectable, otherwise just 'Title'. "
        "Remove underscores, dots, extra spaces. Make it clean and readable. "
        f"Current folder name: {current_name}. "
    )
    if file_samples:
        prompt += f"Sample files: {', '.join(file_samples[:5])}. "
    prompt += "Return only the suggested name, nothing else."

    try:
        if ai_provider == "openrouter" and openrouter_api_key:
            # Use OpenRouter API (OpenAI-compatible)
            import requests
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dvdflix.local",
                    "X-Title": "DvDflix",
                },
                json={
                    "model": openrouter_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 100,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        else:
            # Default to Ollama
            if not ollama_url:
                return None
            import requests
            response = requests.post(
                f"{ollama_url.rstrip('/')}/api/generate",
                json={"model": ollama_model, "prompt": prompt, "stream": False},
                timeout=30,
            )
            response.raise_for_status()
            text = response.json().get("response", "").strip()
    except Exception:
        return None

    # Clean up the response
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        suggestion = lines[0]
        # Remove quotes if AI added them
        suggestion = suggestion.strip("'\"")
        return suggestion if suggestion else None
    return None
