from __future__ import annotations

import re
from collections import Counter
from typing import Any

import requests


def _normalize_title(title: str) -> str:
    text = (title or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_eq(a: str, b: str) -> bool:
    na = _normalize_title(a)
    nb = _normalize_title(b)
    return bool(na and nb and na == nb)


def _label_title_overlap(label: str, title: str) -> bool:
    if not label or not title:
        return False
    lset = set(_normalize_title(label).split())
    tset = set(_normalize_title(title).split())
    if not lset or not tset:
        return False
    return len(lset & tset) >= 2


def _runtime_match(candidate_runtime: int, disc_runtime: float) -> tuple[bool, int, float]:
    if not candidate_runtime or not disc_runtime:
        return False, -20, 999.0

    diff = abs(int(candidate_runtime) - float(disc_runtime))
    if diff <= 3:
        return True, 35, diff
    if diff <= 6:
        return True, 28, diff
    if diff <= 10:
        return True, 18, diff
    if diff <= 15:
        return True, 8, diff
    return False, -40, diff


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(value))))


def _extract_subtitle_titles(results: list[str]) -> Counter:
    titles: list[str] = []
    for block in results:
        for line in block.splitlines():
            matched = re.search(r"\*\s*(?:\d{4}\s*[-:]\s*)?(.+?)\s*\((\d{4})\)", line)
            if matched:
                titles.append(matched.group(1).strip())
                continue
            matched_no_year = re.search(r"\*\s*(?:\d{4}\s*[-:]\s*)?(.+)$", line)
            if matched_no_year:
                titles.append(matched_no_year.group(1).strip())
    return Counter(titles)


class MetadataCrossChecker:
    def __init__(self, omdb_api_key: str = "", tvdb_api_key: str = "", tvdb_pin: str = "") -> None:
        self.omdb_api_key = omdb_api_key
        self.tvdb_api_key = tvdb_api_key
        self.tvdb_pin = tvdb_pin

    def _omdb_lookup(self, title: str) -> dict[str, Any] | None:
        if not self.omdb_api_key:
            return None
        try:
            resp = requests.get(
                "http://www.omdbapi.com/",
                params={"apikey": self.omdb_api_key, "t": title},
                timeout=10,
            )
            data = resp.json()
            if data.get("Response") != "True":
                return None
            runtime_token = str(data.get("Runtime", "0")).split()[0]
            return {
                "title": data.get("Title", ""),
                "year": str(data.get("Year", ""))[:4],
                "runtime": int(runtime_token) if runtime_token.isdigit() else 0,
            }
        except Exception:
            return None

    def _tvdb_lookup(self, title: str) -> dict[str, Any] | None:
        if not self.tvdb_api_key:
            return None

        try:
            payload: dict[str, str] = {"apikey": self.tvdb_api_key}
            if self.tvdb_pin:
                payload["pin"] = self.tvdb_pin

            auth = requests.post("https://api4.thetvdb.com/v4/login", json=payload, timeout=10)
            token = (auth.json().get("data") or {}).get("token")
            if not token:
                return None

            resp = requests.get(
                "https://api4.thetvdb.com/v4/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"query": title, "type": "movie"},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            entries = resp.json().get("data") or []
            if not entries:
                return None
            top = entries[0]
            tvdb_title = top.get("name") or ""
            if not tvdb_title:
                aliases = top.get("aliases") or []
                if isinstance(aliases, list) and aliases:
                    tvdb_title = str(aliases[0])
            return {
                "title": tvdb_title,
                "year": str(top.get("year") or "")[:4],
            }
        except Exception:
            return None

    def score_candidates(
        self,
        disc_label: str,
        duration_mins: float,
        tmdb_candidates: list[dict[str, Any]],
        subtitle_results: list[str] | None = None,
    ) -> dict[str, Any]:
        counts = _extract_subtitle_titles(subtitle_results or [])
        best_sub, best_sub_votes = counts.most_common(1)[0] if counts else (None, 0)

        scored: list[dict[str, Any]] = []
        for tmdb in tmdb_candidates:
            title = str(tmdb.get("title") or "").strip()
            if not title:
                continue
            year = str(tmdb.get("year") or tmdb.get("release_date") or "")[:4]
            runtime = int(tmdb.get("runtime") or 0)

            runtime_ok, runtime_score, runtime_diff = _runtime_match(runtime, duration_mins)
            omdb = self._omdb_lookup(title)
            tvdb = self._tvdb_lookup(title)

            subs_match = bool(best_sub and _title_eq(best_sub, title))
            label_match = _label_title_overlap(disc_label, title)
            omdb_title_match = bool(omdb and _title_eq(str(omdb.get("title") or ""), title))
            omdb_runtime_ok, _, _ = _runtime_match(int((omdb or {}).get("runtime") or 0), duration_mins)
            tvdb_title_match = bool(tvdb and _title_eq(str(tvdb.get("title") or ""), title))

            source_agreements = 1
            if subs_match:
                source_agreements += 1
            if omdb_title_match:
                source_agreements += 1
            if tvdb_title_match:
                source_agreements += 1

            score = 25
            score += runtime_score
            if subs_match:
                score += 20 + min(12, best_sub_votes * 4)
            if label_match:
                score += 8
            if omdb_title_match:
                score += 12
            if omdb_runtime_ok:
                score += 10
            if tvdb_title_match:
                score += 8
            if source_agreements >= 3:
                score += 10

            if not runtime_ok:
                score = min(score, 69)
            if source_agreements < 2:
                score = min(score, 74)

            scored.append(
                {
                    "title": title,
                    "year": int(year) if year.isdigit() else None,
                    "score": _clamp(score),
                    "runtime_ok": runtime_ok,
                    "runtime_diff": round(runtime_diff, 1),
                    "subs_match": subs_match,
                    "subtitle_votes": best_sub_votes if subs_match else 0,
                    "label_match": label_match,
                    "omdb_title_match": omdb_title_match,
                    "omdb_runtime_ok": omdb_runtime_ok,
                    "tvdb_title_match": tvdb_title_match,
                    "source_agreements": source_agreements,
                }
            )

        if not scored:
            return {
                "title": "",
                "year": None,
                "confidence": 0,
                "source_agreements": 1,
                "details": {},
            }

        best = sorted(scored, key=lambda x: x["score"], reverse=True)[0]
        return {
            "title": best["title"],
            "year": best["year"],
            "confidence": best["score"],
            "source_agreements": best["source_agreements"],
            "details": best,
        }
