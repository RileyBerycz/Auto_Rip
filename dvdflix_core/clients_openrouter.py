"""
OpenRouter client for AI-powered title identification.
OpenRouter provides access to many models via OpenAI-compatible API.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """OpenAI-compatible client for OpenRouter API."""

    def __init__(self, api_key: str, model: str = "google/gemini-2.0-flash-001", base_url: str = "https://openrouter.ai/api/v1") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://dvdflix.local",  # OpenRouter requires referer
            "X-Title": "DvDflix",
        })

    def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512) -> str:
        """Generate text using OpenRouter API (OpenAI-compatible format)."""
        if not self.api_key:
            logger.warning("OpenRouter API key not configured")
            return ""

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = self.session.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI-compatible response format
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                return message.get("content", "")
            return ""
        except requests.exceptions.RequestException as e:
            logger.error("OpenRouter request failed: %s", e)
            return ""
        except (KeyError, IndexError, ValueError) as e:
            logger.error("OpenRouter response parsing failed: %s", e)
            return ""

    def guess_title(self, disc_label: str, lsdvd_summary: dict[str, Any], runtime_minutes: int) -> dict[str, Any]:
        """Use OpenRouter to guess the movie/show title from disc info."""
        if not self.api_key:
            return {"title": None, "year": None, "confidence": 0.0, "raw": ""}

        prompt = self._build_identification_prompt(disc_label, lsdvd_summary, runtime_minutes)
        raw = self.generate(prompt)
        return self._parse_title_guess(raw, disc_label)

    def suggest_name(self, current_name: str, file_samples: list[str] = None) -> str | None:
        """Use OpenRouter to suggest a clean name for a file or folder."""
        if not self.api_key:
            return None

        prompt = f"""You are helping rename files in a media library.
Current name: "{current_name}"
{f"File samples: {file_samples}" if file_samples else ""}

Return ONLY the suggested clean name in the format "Title (Year)" for movies or "Show Name (Year)" for TV shows.
Do not include quotes, explanations, or extra text. Just the name.
If the current name is already good, return it unchanged.
"""
        result = self.generate(prompt, temperature=0.1, max_tokens=100)
        return result.strip() if result else None

    def _build_identification_prompt(self, disc_label: str, lsdvd_summary: dict[str, Any], runtime_minutes: int) -> str:
        """Build the prompt for title identification."""
        tracks = lsdvd_summary.get("tracks", [])
        num_tracks = len(tracks)
        longest_track = max((t.get("length", 0) for t in tracks), default=0)

        return f"""You are helping identify a DVD/Blu-ray disc.
Disc label: "{disc_label}"
Runtime: {runtime_minutes} minutes
Number of tracks: {num_tracks}
Longest track: {longest_track} seconds

Based on this information, what is the most likely movie or TV show title?
Return a JSON object with keys: "title", "year", "confidence" (0.0 to 1.0), "media_type" ("movie" or "tv").
Only return the JSON, no other text.
"""

    def _parse_title_guess(self, raw: str, disc_label: str) -> dict[str, Any]:
        """Parse the LLM response into a structured guess."""
        default = {"title": None, "year": None, "confidence": 0.0, "raw": raw}

        if not raw:
            return default

        # Try to extract JSON from response
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return {
                    "title": parsed.get("title") or None,
                    "year": str(parsed.get("year") or "")[:4] or None,
                    "confidence": float(parsed.get("confidence", 0.0)),
                    "media_type": parsed.get("media_type", "movie"),
                    "raw": raw,
                }
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Fallback: try to extract title from non-JSON response
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        if lines:
            title = lines[0].strip('"').strip("'")
            return {
                "title": title,
                "year": None,
                "confidence": 0.3,
                "media_type": "movie",
                "raw": raw,
            }

        return default
