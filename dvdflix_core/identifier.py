from __future__ import annotations

from pathlib import Path

from .clients import OllamaClient, TmdbClient
from .crosscheck import MetadataCrossChecker
from .disc_cache import DiscCache
from .heuristics import is_probable_tv_disc, pick_feature_track_runtime
from .models import DiscInfo, IdentificationResult
from .search import OpenSubtitlesSearcher, SubtitleExtractor, WebSearcher


class DiscIdentifier:
    def __init__(
        self,
        cache: DiscCache,
        ollama: OllamaClient,
        tmdb: TmdbClient,
        runtime_tolerance: int = 8,
        omdb_api_key: str = "",
        tvdb_api_key: str = "",
        tvdb_pin: str = "",
        identify_min_confidence: int = 80,
        opensubtitles_api_key: str = "",
        enable_web_search: bool = False,
        searxng_url: str = "",
    ) -> None:
        self.cache = cache
        self.ollama = ollama
        self.tmdb = tmdb
        self.runtime_tolerance = runtime_tolerance
        self.identify_min_confidence = identify_min_confidence
        self.crosscheck = MetadataCrossChecker(
            omdb_api_key=omdb_api_key,
            tvdb_api_key=tvdb_api_key,
            tvdb_pin=tvdb_pin,
        )
        self.searcher = WebSearcher(searxng_url=searxng_url, enable_legacy_ddgs=enable_web_search)
        self.os_searcher = OpenSubtitlesSearcher(api_key=opensubtitles_api_key)

    def _build_tmdb_candidates(self, llm_title: str, disc_label: str) -> list[dict]:
        candidates: list[dict] = []
        seen_ids: set[int] = set()
        queries = [q for q in [llm_title, disc_label.replace("_", " ").strip()] if q]

        for query in queries:
            for item in self.tmdb.search_movie(query)[:5]:
                movie_id = item.get("id")
                if not movie_id or movie_id in seen_ids:
                    continue
                seen_ids.add(movie_id)

                details = self.tmdb.movie_details(int(movie_id)) or {}
                candidates.append(
                    {
                        "title": item.get("title") or item.get("name") or llm_title,
                        "release_date": item.get("release_date") or "",
                        "year": (item.get("release_date") or "")[:4],
                        "runtime": int(details.get("runtime") or 0),
                    }
                )

        return candidates

    def _escalated_identification(
        self,
        disc: DiscInfo,
        runtime: int,
        initial_candidates: list[dict],
        llm_guess: dict,
    ) -> IdentificationResult | None:
        """
        Escalated two-pass identification: extract subtitles/search results,
        re-prompt Ollama with expanded context for final judgment.
        Returns None if escalation finds nothing; caller falls back to standard logic.
        """
        context_parts: list[str] = []

        context_parts.append(f"Disc Label: {disc.label}")
        context_parts.append(f"Runtime: {runtime} minutes")
        context_parts.append(f"Initial LLM guess: {llm_guess.get('title', 'unknown')} ({llm_guess.get('year', 'unknown')})")
        context_parts.append("")

        if initial_candidates:
            context_parts.append("Top candidates from TMDB:")
            for i, cand in enumerate(initial_candidates[:5]):
                context_parts.append(
                    f"  {i+1}. {cand.get('title', 'Unknown')} ({cand.get('year', 'N/A')}) - runtime {cand.get('runtime', '?')}m"
                )
            context_parts.append("")

        try:
            imdb_result = self.searcher.search_imdb(llm_guess.get("title", ""))
            if imdb_result:
                context_parts.append("IMDB search result:")
                context_parts.append(f"  Title: {imdb_result.get('title')}")
                context_parts.append(f"  Runtime: {imdb_result.get('runtime')}m")
                context_parts.append(f"  Year: {imdb_result.get('year')}")
                context_parts.append("")
        except Exception:
            pass

        try:
            web_results = self.searcher.search_duckduckgo(f"{llm_guess.get('title', '')} movie", max_results=2)
            if web_results:
                context_parts.append("Web search results:")
                for res in web_results:
                    context_parts.append(f"  - {res.get('title', 'Unknown')}: {res.get('body', '')[:100]}")
                context_parts.append("")
        except Exception:
            pass

        escalation_prompt = (
            "You are a DVD title identifier. Based on the following evidence, determine the most likely movie title and year.\n"
            "Respond with JSON only: {\"title\": \"...\", \"year\": 20XX or null, \"confidence\": 0-100, \"reasoning\": \"...\"}\n\n"
            + "\n".join(context_parts)
            + "\n\nFinal judgment:"
        )

        try:
            response = self.ollama.identify_from_disc_with_context(escalation_prompt)
            if response.get("title") and int(response.get("confidence", 0)) >= 70:
                year = response.get("year")
                if isinstance(year, str) and year.isdigit():
                    year = int(year)
                elif not isinstance(year, int):
                    year = None

                return IdentificationResult(
                    media_type="movie",
                    title=response.get("title", disc.label),
                    year=year,
                    confidence=min(0.99, int(response.get("confidence", 70)) / 100.0),
                )
        except Exception:
            pass

        return None

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
        try:
            llm_guess = self.ollama.identify_from_disc(disc.label, runtime, languages)
        except Exception:  # noqa: BLE001
            # Keep pipeline running when Ollama is unavailable; TMDB + fallback label still work.
            llm_guess = {
                "media_type": "movie",
                "title": disc.label.replace("_", " ").strip(),
                "year": None,
                "confidence": 0.25,
            }

        tmdb_candidates = self._build_tmdb_candidates(str(llm_guess.get("title") or ""), disc.label)
        scored = self.crosscheck.score_candidates(
            disc_label=disc.label,
            duration_mins=runtime,
            tmdb_candidates=tmdb_candidates,
        )

        fallback_title = str(llm_guess.get("title") or disc.label.replace("_", " ").strip())
        fallback_year = llm_guess.get("year")
        if isinstance(fallback_year, str) and fallback_year.isdigit():
            fallback_year = int(fallback_year)
        if not isinstance(fallback_year, int):
            fallback_year = None

        scored_confidence = int(scored.get("confidence") or 0)

        # Tier 1: Fast path - numeric scores
        if scored_confidence >= self.identify_min_confidence:
            title = str(scored.get("title") or fallback_title)
            year = scored.get("year") if isinstance(scored.get("year"), int) else fallback_year
            confidence = min(0.99, scored_confidence / 100.0)
        # Tier 2: Escalation path - if borderline, use LLM arbitration with search context
        elif 60 <= scored_confidence < self.identify_min_confidence:
            escalated = self._escalated_identification(
                disc=disc,
                runtime=runtime,
                initial_candidates=tmdb_candidates,
                llm_guess=llm_guess,
            )
            if escalated:
                result = escalated
                self.cache.set(disc.label, result)
                return result

            # Escalation didn't help; use borderline score fallback
            title = str(scored.get("title") or fallback_title)
            year = scored.get("year") if isinstance(scored.get("year"), int) else fallback_year
            confidence = max(0.35, scored_confidence / 100.0)
        else:
            title = fallback_title
            year = fallback_year
            confidence = max(0.25, float(llm_guess.get("confidence", 0.4)))


        result = IdentificationResult(
            media_type="movie",
            title=title,
            year=year,
            confidence=confidence,
        )
        self.cache.set(disc.label, result)
        return result
