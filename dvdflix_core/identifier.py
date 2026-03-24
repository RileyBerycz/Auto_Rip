from __future__ import annotations

from .clients import OllamaClient, TmdbClient
from .disc_cache import DiscCache
from .heuristics import is_probable_tv_disc, pick_feature_track_runtime
from .models import DiscInfo, IdentificationResult


class DiscIdentifier:
    def __init__(self, cache: DiscCache, ollama: OllamaClient, tmdb: TmdbClient, runtime_tolerance: int = 8) -> None:
        self.cache = cache
        self.ollama = ollama
        self.tmdb = tmdb
        self.runtime_tolerance = runtime_tolerance

    def identify(self, disc: DiscInfo) -> IdentificationResult:
        cached = self.cache.get(disc.label)
        if cached:
            return cached

        is_tv, episodes = is_probable_tv_disc(disc)
        if is_tv:
            result = IdentificationResult(
                media_type="tv",
                title=disc.label.replace("_", " ").strip(),
                year=None,
                confidence=0.65,
                season=1,
                episodes=episodes,
            )
            self.cache.set(disc.label, result)
            return result

        runtime = pick_feature_track_runtime(disc)
        languages = sorted({lang for t in disc.tracks for lang in t.audio_languages})
        llm_guess = self.ollama.identify_from_disc(disc.label, runtime, languages)

        tmdb_results = self.tmdb.search_movie(llm_guess["title"])
        year = llm_guess.get("year")
        confidence = float(llm_guess.get("confidence", 0.4))

        if tmdb_results:
            top = tmdb_results[0]
            title = top.get("title", llm_guess["title"])
            release = top.get("release_date", "")
            year = year or (int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None)
            # Slight confidence boost once TMDB confirms title presence.
            confidence = min(1.0, confidence + 0.2)
        else:
            title = llm_guess["title"]

        result = IdentificationResult(
            media_type="movie",
            title=title,
            year=year,
            confidence=confidence,
        )
        self.cache.set(disc.label, result)
        return result
