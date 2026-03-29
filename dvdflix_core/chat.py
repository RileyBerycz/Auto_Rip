from __future__ import annotations

from typing import Any


class OllamaChatSession:
    """
    Maintains persistent conversation state with Ollama for multi-turn identification.
    Keeps full message history internally; caller never sees the conversation.
    Uses Ollama's /api/chat endpoint for true conversation context.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.messages: list[dict[str, str]] = []
        self.system_prompt = (
            "You are an expert DVD/Blu-ray title identifier. "
            "You have access to disc metadata (label, runtime, audio languages, track information). "
            "You also receive search results from TMDB, IMDB, OMDb, and web sources. "
            "Your job is to identify the most likely title and year. "
            "Always respond with JSON containing: {\"title\": \"...\", \"year\": 20XX or null, \"confidence\": 0-100, \"reasoning\": \"...\"}"
        )

    def add_context(self, label: str, runtime: int, languages: list[str], track_count: int) -> None:
        """Initialize session with disc metadata."""
        initial_context = (
            f"I have a DVD with the following metadata:\n"
            f"- Disc Label: {label}\n"
            f"- Runtime: {runtime} minutes\n"
            f"- Audio Languages: {', '.join(languages) if languages else 'unknown'}\n"
            f"- Track Count: {track_count}\n\n"
            f"Please make an initial guess at the title and year based on this information."
        )
        self.messages.append({"role": "user", "content": initial_context})

    def add_candidates(self, candidates: list[dict[str, Any]]) -> None:
        """Feed TMDB candidates into conversation."""
        candidate_text = "I found these candidates on TMDB:\n"
        for i, cand in enumerate(candidates[:7]):
            candidate_text += f"{i+1}. {cand.get('title', 'Unknown')} ({cand.get('year', 'N/A')}) - Runtime: {cand.get('runtime', '?')}m\n"

        candidate_text += "\nWhich of these best matches the disc metadata? Respond with updated confidence."
        self.messages.append({"role": "user", "content": candidate_text})

    def add_search_results(self, search_context: str) -> None:
        """Feed web/IMDB/OMDb search results."""
        self.messages.append(
            {
                "role": "user",
                "content": f"I found additional search results. Please reconsider: {search_context}",
            }
        )

    def add_evidence(self, evidence: str) -> None:
        """Generic evidence presentation (subtitle matches, runtime corroboration, etc.)."""
        self.messages.append({"role": "user", "content": f"New evidence: {evidence}"})

    def get_final_judgment(self, client: Any) -> dict[str, Any]:
        """
        Send full conversation to Ollama and get final judgment.
        client is an OllamaClient instance with chat_with_history method.
        """
        return client.chat_with_history(
            self.system_prompt, self.messages, self.model
        )

    def add_assistant_response(self, response: str) -> None:
        """Track Ollama's responses in conversation history."""
        self.messages.append({"role": "assistant", "content": response})
