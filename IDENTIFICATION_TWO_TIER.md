# Two-Tier Identification & LLM Arbitration

## Overview

Your suspicion was spot-on: pure numeric scoring breaks down on noisy/ambiguous disc metadata. The system now implements **LLM-as-arbitration** with an optional escalation path for borderline cases.

## How It Works

### Tier 1: Fast Cross-Check (Default)

1. **LLM proposes** title/year from disc label + runtime + audio languages.
2. **TMDB hydration**: Search for candidates, fetch their runtimes.
3. **Cross-check scoring**:
   - Runtime match (tolerance ±8 min by default)
   - Label overlap (disc label shares keywords with candidate title)
   - Optional OMDb/TVDB corroboration (if keys provided)
   - Multi-source agreement counting

4. **Decision**:
   - Score ≥ 80 (IDENTIFY_MIN_CONFIDENCE): **Accept** → cache & move to rip
   - Score 60–80: **Escalate** (if enabled)
   - Score < 60: **Fallback** to conservative LLM naming

### Tier 2: Escalation with Search Context (Borderline)

When score is 60–80, `_escalated_identification()` is triggered:

1. **Gather expanded context**:
   - IMDB quick search (if `ENABLE_WEB_SEARCH=true`)
   - DuckDuckGo movie search (if `ENABLE_WEB_SEARCH=true`)
   - OpenSubtitles subtitle matches (if `OPENSUBTITLES_API_KEY` provided)

2. **Re-prompt Ollama with full context**:
   ```
   Disc Label: P9105DVD
   Runtime: 117 minutes
   Initial LLM guess: Some Movie (2020)
   
   Top candidates from TMDB:
   1. Another Movie (2019) - runtime 115m
   2. Actual Movie (2021) - runtime 120m
   
   IMDB search result:
   Title: Actual Movie
   Runtime: 119m
   Year: 2021
   
   Web search results:
   - Actual Movie Wikipedia: A film released in 2021...
   - IMDB: Highly rated thriller...
   
   Final judgment:
   ```

3. **LLM decides**: Given all evidence, which title is likeliest?
   - If confidence ≥ 70: **Accept and use**
   - Otherwise: **Fallback** to borderline score

## Why This Is Better Than Pure Scoring

| Scenario                     | Pure Scoring | LLM Arbitration |
|------------------------------|--------------|-----------------|
| Generic title match (e.g., "The Matrix") | High score, possible false match | LLM sees 3+ sources + runtime confirm → **correct** |
| Borderline runtime (±8 min off) | Score penalized but not rejected | LLM sees "close call" + web context → **correct decision** |
| Disc label = trash (e.g., "DVD_001") | Very low score | LLM + search finds real movie despite label → **recovers** |
| Ambiguous disc (multiple similar options) | Picks first acceptable option | LLM weighs all evidence + sources → **ties go to strongest consensus** |

## Ollama Context Window Note

✅ **Context persists within a single LLM call.**  
Within the escalation prompt, all accumulated context (candidates + search results) is bundled into one request, so Ollama can reason over everything simultaneously.

## Configuration

### Required (unchanged)
```env
TMDB_API_KEY=your_key
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
```

### Tier 1 Tuning
```env
IDENTIFY_MIN_CONFIDENCE=80          # Raise to 85+ for stricter tier 1
RUNTIME_TOLERANCE_MINUTES=8         # Widen to ±10 for older DVDs
OMDB_API_KEY=optional_key           # Adds extra runtime corroboration
TVDB_API_KEY=optional_key           # Adds title corroboration
TVDB_PIN=optional_pin
```

### Tier 2 (Escalation) Options
```env
ENABLE_WEB_SEARCH=true              # Triggers IMDB + DuckDuckGo searches
OPENSUBTITLES_API_KEY=optional      # Subtitle dialogue matching
```

## Example Log Output

```
[sr0] Pass 1: deterministic precheck from label/runtime
[sr0] Cross-check score: 61 (runtime_ok=True, sources=2)
[sr0] Score in escalation range (60-80), triggering Tier 2...
[sr0] Escalation: gathering IMDB + web context...
[sr0] Re-prompting Ollama with expanded context...
[sr0] Ollama final judgment: "Actual Movie" (2021), confidence=92
[sr0] Escalation accepted, proceeding with identification
```

## Implementation Files

- **`dvdflix_core/search.py`**: Web searcher, subtitle extractor, OpenSubtitles integration
- **`dvdflix_core/identifier.py`**: `_escalated_identification()` method; Tier 1 → Tier 2 logic
- **`dvdflix_core/clients.py`**: `identify_from_disc_with_context()` for re-prompting Ollama
- **`dvdflix_core/config.py`**: New settings fields + override handling
- **Backend API**: Exposes new settings in setup/settings endpoints
- **Frontend**: UI fields for enabling escalation features

## Next Steps

1. **Test with borderline DVDs**: Raise `IDENTIFY_MIN_CONFIDENCE` to 85–90 and see how many fall through to escalation.
2. **Optional: Add OpenSubtitles**: If subtitle dialogue matching is useful, register for API access.
3. **Optional: Enable web search**: If you want richer context, set `ENABLE_WEB_SEARCH=true` (requires `duckduckgo_search` pip package).
4. **Monitor escalation rate**: If too many hits escalation path, lower `IDENTIFY_MIN_CONFIDENCE` slightly (cost-benefit trade-off).
