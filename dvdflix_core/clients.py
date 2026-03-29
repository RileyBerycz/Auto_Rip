from __future__ import annotations

import re
from typing import Any

import requests


class TmdbClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    def search_movie(self, query: str) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        response = requests.get(
            f"{self.base_url}/search/movie",
            params={"api_key": self.api_key, "query": query},
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("results", [])

    def movie_details(self, movie_id: int) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        response = requests.get(
            f"{self.base_url}/movie/{movie_id}",
            params={"api_key": self.api_key},
            timeout=15,
        )
        if response.status_code != 200:
            return None
        return response.json()


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def identify_from_disc(self, label: str, runtime_minutes: int, languages: list[str]) -> dict[str, Any]:
        prompt = (
            "Identify this DVD content and answer JSON only with fields "
            "media_type (movie|tv), title, year, confidence (0-1). "
            f"Disc label: {label}. Runtime minutes: {runtime_minutes}. "
            f"Audio languages: {', '.join(languages) if languages else 'unknown'}."
        )
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=45,
        )
        response.raise_for_status()
        text = response.json().get("response", "{}").strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"media_type": "movie", "title": label, "year": None, "confidence": 0.25}

        try:
            parsed = requests.models.complexjson.loads(match.group(0))
        except ValueError:
            parsed = {"media_type": "movie", "title": label, "year": None, "confidence": 0.25}

        return {
            "media_type": parsed.get("media_type", "movie"),
            "title": parsed.get("title", label),
            "year": parsed.get("year"),
            "confidence": float(parsed.get("confidence", 0.25)),
        }

    def identify_from_disc_with_context(self, prompt: str) -> dict[str, Any]:
        """
        Multi-turn LLM judgment using expanded context (search results, metadata).
        Useful for escalated/borderline identifications.
        """
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        text = response.json().get("response", "{}").strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"title": "", "year": None, "confidence": 0}

        try:
            parsed = requests.models.complexjson.loads(match.group(0))
        except ValueError:
            return {"title": "", "year": None, "confidence": 0}

        return {
            "title": parsed.get("title") or "",
            "year": parsed.get("year"),
            "confidence": int(parsed.get("confidence", 0)) or 0,
            "reasoning": parsed.get("reasoning", ""),
        }

    def chat_with_history(
        self, system_prompt: str, messages: list[dict[str, str]], model: str | None = None
    ) -> dict[str, Any]:
        """
        Multi-turn conversation using Ollama's /api/chat endpoint.
        Maintains full conversation history for contextual reasoning.
        """
        model = model or self.model
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
        }
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        text = response.json().get("message", {}).get("content", "{}").strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {"title": "", "year": None, "confidence": 0}

        try:
            parsed = requests.models.complexjson.loads(match.group(0))
        except ValueError:
            return {"title": "", "year": None, "confidence": 0}

        return {
            "title": parsed.get("title") or "",
            "year": parsed.get("year"),
            "confidence": int(parsed.get("confidence", 0)) or 0,
            "reasoning": parsed.get("reasoning", ""),
        }

