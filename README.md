# DVDFlix

Self-hosted DVD ripping and media management system with both a standalone curses daemon and a web app.

## Components

- `scripts/auto_rip.py`: standalone curses daemon for drive monitoring and ripping.
- `scripts/auto_rip_test.py`: one-shot rip/identify test runner.
- `scripts/encode_library.py`: HandBrake x265 batch encoder.
- `scripts/rename_library.py`: library naming normalizer and extras classifier.
- `backend/`: Flask + SocketIO API for the Docker app.
- `frontend/`: React + Vite dashboard.
- `dvdflix_core/`: shared ripping/identification pipeline.

## Dockge And Portable Deployments

The default `docker-compose.yml` is portable and can run on any host, including systems without DVD drives.

- No host optical devices are hardcoded in the base stack.
- No host-specific bind mounts are required in the base stack.
- Runtime settings are provided at deploy time (Dockge env editor).

Deploy in Dockge:

1. Create a stack using `docker-compose.yml`.
2. Set env values in Dockge (`TMDB_API_KEY`, `OLLAMA_URL`, ports, image tag).
3. Deploy stack.

Ollama behavior:

- Base stack expects an external Ollama URL (default in `.env.example` points to host Ollama).
- Bundled Ollama is in a separate override file: `docker-compose.ollama.yml`.
- Include that file only when you intentionally want an in-stack Ollama container.
- This avoids accidental `11434` conflicts and reduces OOM risk on small hosts.

For ripping hosts with optical drives, add the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.ripper.yml up -d
```

In Dockge, include both files in the stack and set host path envs such as `HOST_MOVIES_PATH`, `HOST_TV_PATH`, and drive envs (`DRIVE_0..2`, `DRIVES`).

Tip: if `DRIVES` is left blank in setup/settings, the backend now auto-detects optical devices from `/dev/sr*` (and common aliases `/dev/cdrom`, `/dev/dvd`) that are visible inside the container.

## One-File Full Auto-Ripper (Dedicated Ripper Hosts)

If this machine is dedicated to ripping, use `docker-compose.full.yml` for a single-file deployment:

1. Copy `.env.example` to `.env`.
2. Set `TMDB_API_KEY` and host mounts (`HOST_MOVIES_PATH`, `HOST_TV_PATH`, `HOST_TEMP_RIP_PATH`).
3. Confirm optical drive mappings (`DRIVE_0..2`) and `DRIVES`.
4. Start stack:

```bash
docker compose -f docker-compose.full.yml up -d
```

Optional bundled Ollama:

```bash
docker compose -f docker-compose.full.yml --profile bundled-ollama up -d
```

Open:
- Frontend: `http://<host>:7273`
- Backend health: `http://<host>:7272/api/health`

### Dockge Troubleshooting

- If Dockge shows `inactive` while containers appear up, redeploy stack after pulling latest compose that includes healthchecks.
- Check backend setup endpoint directly: `http://<host>:7272/api/setup/status`.
- If frontend only shows `Loading setup status...`, verify `VITE_API_URL` and `VITE_SOCKET_URL` point to a browser-reachable backend URL (not `localhost` unless browsing from that same host).
- Keep bundled Ollama profile disabled unless intentionally used (`bundled-ollama`), especially when host Ollama already binds port `11434`.

## GitHub Container Publishing (GHCR) + Dockge Workflow

This is the recommended **zero-maintenance** deployment path for Dockge users.

### GitHub Actions (Automatic)

This repo includes a GitHub Actions workflow that builds and publishes:

- `ghcr.io/<owner>/dvdflix-backend:<tag>`
- `ghcr.io/<owner>/dvdflix-frontend:<tag>`

On every push to `main`:
- Images are tagged `latest`
- Commit SHA tags are also created for rollback

No manual build steps needed.

### Dockge Workflow (Simple Update Flow)

**One-time setup:**

1. Create a new stack in Dockge.
2. Paste `docker-compose.yml` (portable base stack).
3. In Dockge **Environment**, set only:
   - `TMDB_API_KEY=your_key_here`
   - `VITE_API_URL=http://your-dockge-host:7272` (frontend can reach backend)
   - `IMAGE_TAG=latest` (or pin to specific version)
   - `BACKEND_IMAGE=ghcr.io/<owner>/dvdflix-backend`
   - `FRONTEND_IMAGE=ghcr.io/<owner>/dvdflix-frontend`
4. **Deploy** stack.
5. Open `http://your-dockge-host:7273` → Complete first-run setup wizard.

**Future updates (all automatic):**

1. GitHub Actions automatically publishes new images when you push code.
2. In Dockge, redeploy the stack (Dockge pulls latest images).
3. Frontend auto-migrates on login; no settings lost.

### Setting New Searxng & Handbrake Features (Web UI Only)

Once deployed, **all** settings—including new ones—are configured via the dashboard:

1. **Searxng Integration**:
   - Setup tab → Set `SEARXNG_URL=http://searxng:8888` (if using bundled).
   - Or leave blank to use DuckDuckGo fallback.
   - No compose file edit needed.

2. **Handbrake Encoding Preset**:
   - Settings tab → Set `HANDBRAKE_PRESET` to:
     - `default` (all tracks, bonus features)
     - `standard` (main feature only)
   - No compose file edit needed.

3. **All Other Settings**:
   - OMDB_API_KEY, TVDB_API_KEY, confidence thresholds, etc.
   - All editable from Settings tab.
   - Saved in backend SQLite (persists across redeploys).

**Key Point**: After first-run setup via web UI, you never edit `.env` or compose environment variables again. Just redeploy the stack in Dockge when images update, and all settings carry forward.

### Using Bundled Searxng (Optional)

If you want Searxng bundled in the same stack:

```yaml
# In Dockge, edit the compose file to add searxng service or use docker-compose.full.yml
services:
  searxng:
    image: searxng/searxng:latest
    ports:
      - "8888:8888"
```

Set `SEARXNG_URL=http://searxng:8888` in Settings tab, and escalation search will use it.

### Image Tagging Strategy

- `latest` - Always pulls newest from main branch (good for test instances).
- `v1.2.3` - Pin to release tags for stable production.
- Commit SHAs - Available if you need exact rollback.

In Dockge, change `IMAGE_TAG` to switch versions without rebuilding.

### GHCR Pull Limits

GitHub's public registry allows ~6000 pulls/hour per IP (generous for small teams). If you hit limits, consider setting up authentication in Dockge:

```
GHCR_USERNAME=<your-github-username>
GHCR_TOKEN=<personal-access-token>
```

(Not required for initial setup unless you're in a corporate environment with shared IP.)

## GitHub Container Publishing

Then in Dockge set:

- `BACKEND_IMAGE=ghcr.io/<owner>/dvdflix-backend`
- `FRONTEND_IMAGE=ghcr.io/<owner>/dvdflix-frontend`
- `IMAGE_TAG=latest` (or pin to a release tag)

## Standalone Daemon

Run directly on the Ubuntu host where optical drives are present:

```bash
python scripts/auto_rip.py
```

One-shot test mode for a single drive:

```bash
python scripts/auto_rip_test.py --drive /dev/sr1
```

## Backend API

- Public:
	- `GET /api/setup/status`
	- `POST /api/setup/initialize`
	- `POST /api/auth/login`
- Authenticated (Bearer token):
	- `GET /api/health`
	- `GET /api/jobs`
	- `POST /api/jobs/start` with JSON `{ "drive": "/dev/sr1" }`
	- `POST /api/jobs/start-all`
	- `GET /api/library`
	- `GET /api/settings`
	- `POST /api/settings`
	- `GET /api/capabilities`

Socket events:

- `job_update`: emitted whenever a rip job state changes.

## Shared Pipeline Behavior

### lsdvd & Track Detection
- `lsdvd` scans drive for disc label, track metadata, and audio languages.
- TV heuristics detect clustered track durations (e.g., 3 episodes on same disc).
- Track count and total duration used for disc deduplication (fingerprinting).

### Multi-Tier Identification & LLM Arbitration
- **Tier 1 (Fast)**: Ollama proposes title/year → TMDB search + runtime matching → cross-check scoring (runtime ± tolerance + label overlap + optional OMDB/TVDB).
  - If score ≥ `IDENTIFY_MIN_CONFIDENCE` (default 80%), accept immediately.
- **Tier 2 (Escalation)**: If score 60–80%, escalate with richer context:
  - Searxng metasearch (or DuckDuckGo fallback) for web results + IMDB quick lookup.
  - OpenSubtitles dialogue matching (optional).
  - Re-prompt Ollama with all evidence as context for final judgment.
- **Fallback**: If < 60%, use conservative LLM naming to avoid false positives.

### Ripping & Selective Encoding
- Rip uses `makemkvcon mkv all` and writes to movies/tv paths.
- `HANDBRAKE_PRESET` controls encoding:
  - `default` (all tracks): Includes bonus content, special features, all audio tracks.
  - `standard` (main feature only): Extracts primary title/episodes, skips extras (requires post-processing).
- Identification is serialized per drive; ripping remains parallel.

### Deduplication & Re-Insertion Detection
- Disc hash computed from label + track count + duration via SHA256.
- Stored in `disc_history` SQLite table to detect re-inserted discs.
- If disc already ripped, skip identification and mark job as duplicate.

### TV Show Handling
- TV heuristics identify shows with clustered track durations (multiple episodes on disc).
- System tracks episode numbers/groupings; allows selective ripping instead of rip-all.
- Dashboard allows filtering by episode range before final commit.

Cross-check & Escalation Tuning:

- `IDENTIFY_MIN_CONFIDENCE` (default `80`) - minimum score before auto-accept.
- `OMDB_API_KEY` (optional) - runtime/title corroboration.
- `TVDB_API_KEY` + `TVDB_PIN` (optional) - secondary TV title corroboration.
- `OPENSUBTITLES_API_KEY` (optional) - subtitle dialogue matching during escalation.
- `ENABLE_WEB_SEARCH` (default `false`) - use legacy DuckDuckGo search fallback.
- `SEARXNG_URL` (optional) - superior metasearch for escalation (replaces DuckDuckGo).
- `HANDBRAKE_PRESET` (default `default`) - encoding profile (all tracks vs. main feature only).

## Script-Free Docker Workflow (Complete Replacement)

You no longer need `auto_rip.py`, `auto_rip_test.py`, or manual scripts. The Docker web interface replaces all script functionality:

### Dashboard Features
1. **Real-Time Monitoring**: View active jobs, states (pending → identifying → ripping → complete/failed).
2. **Quick Actions**: Start all drives or individual drives directly from dashboard.
3. **Manual Title Override**: If identification fails or gives wrong result:
   - Click job → "Search" button
   - Search TMDB for correct title/year
   - Override manually via dashboard (no terminal, no editing config files)
4. **Library Browser**: Browse all ripped movies/TV shows with counts.
5. **Ripper Health**: Check tool status (lsdvd, makemkvcon, eject) and drive visibility.

### Workflow: From Disc Insertion to Finished Rip
1. Insert disc into drive.
2. Dashboard detects drive activity.
3. System auto-identifies title (Tier 1 fast, Tier 2 escalation if needed).
4. If confident, rips automatically to movies/tvshows folder.
5. If uncertain (60–80 score), marks as "pending override":
   - You search & correct title via dashboard search UI.
   - Once corrected, system continues rip with correct metadata.
6. If very low confidence (< 60), ejects disc to `/media/tmp` and alerts user.
7. Finished MKV appears in library with correct title.

### No More Scripts Needed
- ❌ Don't use `scripts/auto_rip.py` anymore.
- ❌ Don't use `scripts/auto_rip_test.py` for testing.
- ❌ Don't edit environment variables in shell scripts.
- ✅ Use Docker web dashboard for everything.

### Bundled Searxng
For superior web search during escalation:
```bash
docker compose -f docker-compose.full.yml --profile bundled-searxng up -d
```
Then set `SEARXNG_URL=http://searxng:8888` in `.env` before initializing setup.

## First-Run Setup Model

- On first load, the frontend opens a setup wizard.
- Wizard creates an admin account and stores runtime settings in backend SQLite state.
- Runtime settings are applied immediately without editing compose files.
- Docker host permissions are still set outside the app (Dockge/Compose):
	- Device mappings (for `/dev/sr*`)
	- Host bind mounts for media paths

## Notes

- Runtime tolerance defaults to `+-8` minutes (PAL speed compensation).
- Identification workers default to `1` to avoid Ollama GPU contention.
- Ripping runs in parallel across drives.
- Uses `makemkvcon mkv all` to avoid title index mismatch between `lsdvd` and `makemkvcon`.
