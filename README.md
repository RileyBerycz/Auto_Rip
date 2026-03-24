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

For ripping hosts with optical drives, add the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.ripper.yml up -d
```

In Dockge, include both files in the stack and set host path envs such as `HOST_MOVIES_PATH`, `HOST_TV_PATH`, and drive envs (`DRIVE_0..2`, `DRIVES`).

Open:
- Frontend: `http://<host>:7273`
- Backend health: `http://<host>:7272/api/health`

## GitHub Container Publishing (GHCR)

This repo includes a GitHub Actions workflow that builds and publishes:

- `ghcr.io/<owner>/dvdflix-backend:<tag>`
- `ghcr.io/<owner>/dvdflix-frontend:<tag>`

On push to `main`, images are pushed with `latest` and commit-SHA tags.

Required GitHub setup:

1. Create repo (for example `rileyberycz/dvdflix`).
2. Push this project to the repo.
3. Ensure GitHub Actions is enabled.
4. Use `GITHUB_TOKEN` package permissions (already configured in workflow).

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

- `lsdvd` scans drive and metadata.
- TV heuristics detect clustered track durations.
- Ollama + TMDB identify movie title/year with cache.
- Rip uses `makemkvcon mkv all` and writes to movies/tv path.
- Identification is serialized; ripping remains parallel per drive.

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
