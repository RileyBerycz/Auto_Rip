from __future__ import annotations

import re
from typing import Any

import requests


class WebSearcher:
    """Aggregates web search results (Searxng or DuckDuckGo) to enrich confidence for LLM re-judgment."""

    def __init__(self, searxng_url: str = "", enable_legacy_ddgs: bool = False) -> None:
        """
        Initialize web searcher.
        Args:
            searxng_url: URL to Searxng instance (e.g., http://localhost:8888). If set, Searxng is preferred.
            enable_legacy_ddgs: Fall back to DuckDuckGo if Searxng not available.
        """
        self.searxng_url = searxng_url.rstrip("/") if searxng_url else ""
        self.enable_legacy_ddgs = enable_legacy_ddgs
        self._ddgs = None
        
        if enable_legacy_ddgs:
            try:
                from duckduckgo_search import DDGS
                self._ddgs = DDGS()
            except ImportError:
                pass

    def search_searxng(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Search using Searxng instance. Requires SEARXNG_URL to be configured."""
        if not self.searxng_url:
            return []
        try:
            resp = requests.get(
                f"{self.searxng_url}/search",
                params={"q": query, "format": "json"},
                timeout=10
            )
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            results = []
            for result in data.get("results", [])[:max_results]:
                results.append({
                    "title": result.get("title", ""),
                    "body": result.get("content", ""),
                    "url": result.get("url", "")
                })
            return results
        except Exception:
            return []

    def search_duckduckgo(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Legacy DuckDuckGo search. Used only if Searxng unavailable and enable_legacy_ddgs=True."""
        if not self._ddgs:
            return []
        try:
            results = self._ddgs.text(query, max_results=max_results)
            return [{"title": r.get("title", ""), "body": r.get("body", "")} for r in results]
        except Exception:
            return []
    
    def search_web(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Smart web search: tries Searxng first, falls back to DuckDuckGo."""
        if self.searxng_url:
            results = self.search_searxng(query, max_results)
            if results:
                return results
        return self.search_duckduckgo(query, max_results)

    def search_imdb(self, query: str) -> dict[str, Any] | None:
        """Quick IMDB title + runtime lookup. Returns best match or None."""
        try:
            search_url = "https://www.imdb.com/find"
            resp = requests.get(
                search_url, params={"q": query, "s": "tt"}, timeout=10
            )
            if resp.status_code != 200:
                return None

            match = re.search(r"href=\"(/title/(tt\d+)/)", resp.text)
            if not match:
                return None

            title_id = match.group(2)
            title_url = f"https://www.imdb.com/title/{title_id}/"
            resp = requests.get(title_url, timeout=10)

            title_match = re.search(r"<h1[^>]*>([^<]+)</h1>", resp.text)
            runtime_match = re.search(r">(\d+)\s*min<", resp.text)
            year_match = re.search(r"<span>(\d{4})</span>", resp.text)

            return {
                "title": title_match.group(1).strip() if title_match else query,
                "runtime": int(runtime_match.group(1)) if runtime_match else None,
                "year": year_match.group(1) if year_match else None,
                "imdb_id": title_id,
            }
        except Exception:
            return None


class SubtitleExtractor:
    """Extracts dialogue from subtitle files for search/matching."""

    @staticmethod
    def extract_dialogue_chunks(srt_content: str, chunk_minutes: int = 10) -> list[str]:
        """
        Parse SRT subtitle content and extract dialogue chunks by time duration.
        Returns list of text chunks, each roughly `chunk_minutes` long.
        """
        chunks: list[str] = []
        lines: list[str] = []
        chunk_start_ms = 0
        chunk_end_ms = chunk_minutes * 60 * 1000

        for raw_line in srt_content.split("\n"):
            line = raw_line.strip()
            if not line or line.isdigit():
                continue

            time_match = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*", line)
            if time_match:
                h, m, s, ms = map(int, time_match.groups())
                current_ms = h * 3600000 + m * 60000 + s * 1000 + ms

                if current_ms >= chunk_end_ms and lines:
                    chunks.append(" ".join(lines))
                    lines = []
                    chunk_start_ms = current_ms
                    chunk_end_ms = current_ms + chunk_minutes * 60 * 1000
            else:
                if line and not re.match(r"^\d+:\d+:\d+", line):
                    lines.append(line)

        if lines:
            chunks.append(" ".join(lines))

        return chunks

    @staticmethod
    def normalize_text(text: str) -> str:
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.lower()


class OpenSubtitlesSearcher:
    """
    Matches subtitle dialogue against OpenSubtitles API to find likely films.
    Requires an OpenSubtitles API account and authorization token.
    """

    def __init__(self, api_key: str = "", username: str = "", password: str = "") -> None:
        self.api_key = api_key
        self.username = username
        self.password = password
        self.token: str | None = None

    def _get_token(self) -> str | None:
        if self.token:
            return self.token
        if not self.api_key and not (self.username and self.password):
            return None

        try:
            headers = {}
            if self.api_key:
                headers["Api-Key"] = self.api_key

            auth_data = {}
            if self.username and self.password:
                auth_data = {"username": self.username, "password": self.password}

            resp = requests.post(
                "https://api.opensubtitles.com/api/v1/login",
                json=auth_data,
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return None

            self.token = resp.json().get("token")
            return self.token
        except Exception:
            return None

    def search_by_dialogue(self, dialogue_fragment: str, language: str = "en") -> list[dict[str, Any]]:
        """
        Search OpenSubtitles for films matching a dialogue fragment.
        Returns list of matching films with metadata.
        """
        token = self._get_token()
        if not token:
            return []

        try:
            headers = {
                "Api-Key": self.api_key or "",
                "Authorization": f"Bearer {token}",
            }

            query = dialogue_fragment[:100]
            resp = requests.get(
                "https://api.opensubtitles.com/api/v1/subtitles",
                params={"query": query, "languages": language},
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            data = resp.json().get("data", [])
            results: list[dict[str, Any]] = []
            seen_imdb: set[str] = set()

            for entry in data[:10]:
                attrs = entry.get("attributes", {})
                imdb_id = str(attrs.get("imdb_id") or "")
                if imdb_id and imdb_id not in seen_imdb:
                    seen_imdb.add(imdb_id)
                    results.append(
                        {
                            "imdb_id": imdb_id,
                            "title": attrs.get("title") or "Unknown",
                            "year": attrs.get("year"),
                            "language": attrs.get("language"),
                            "release_name": attrs.get("release") or "",
                        }
                    )

            return results
        except Exception:
            return []
