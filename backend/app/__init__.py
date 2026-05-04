from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory, render_template_string, jsonify, make_response
from flask_cors import CORS

from .routes.api import api_bp
from .services.job_manager import JobManager
from .services.sse_manager import SSEManager
from .services.state_store import StateStore


def create_app() -> Flask:
    # Determine static folder paths (dist root and assets subfolder)
    static_root = Path(__file__).parent.parent / "static"
    static_assets = static_root / "assets"
    # If the build produced an 'assets' directory, serve it at /assets; otherwise
    # fall back to serving the static root directory directly.
    assets_folder = static_assets if static_assets.exists() else static_root

    app = Flask(__name__, static_folder=str(assets_folder), static_url_path="/assets")
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    app.config["BACKEND_HOST"] = "0.0.0.0"
    app.config["BACKEND_PORT"] = 7272

    store = StateStore()
    settings_keys = [
        "MOVIES_PATH",
        "TV_PATH",
        "TEMP_RIP_PATH",
        "DRIVES",
        "TMDB_API_KEY",
        "OMDB_API_KEY",
        "TVDB_API_KEY",
        "TVDB_PIN",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "RUNTIME_TOLERANCE_MINUTES",
        "IDENTIFY_MIN_CONFIDENCE",
        "MAX_IDENTIFY_WORKERS",
        "DISC_CACHE_DB",
        "OPENSUBTITLES_API_KEY",
        "ENABLE_WEB_SEARCH",
        "SEARXNG_URL",
        "HANDBRAKE_PRESET",
        "MAKEMKVCON_PATH",
    ]
    saved = store.get_settings(settings_keys)

    sse_manager = SSEManager()
    manager = JobManager(sse_manager, settings_overrides=saved)
    app.extensions["job_manager"] = manager
    app.extensions["state_store"] = store
    app.extensions["sse_manager"] = sse_manager

    app.register_blueprint(api_bp, url_prefix="/api")

    # Serve static files and SPA
    @app.route("/")
    def index():
        index_path = static_root / "index.html"
        if index_path.exists():
            # Inject a tiny runtime snippet to set the frontend API URL in localStorage
            # if the user hasn't already configured it. This avoids needing to rebuild
            # the frontend when the backend URL is the same origin.
            content = index_path.read_text(encoding="utf-8")
            injection = (
                "<script>try{if(!localStorage.getItem('dvdflix_api_url')){localStorage.setItem('dvdflix_api_url',window.location.origin);} }catch(e){};</script>"
            )
            if "</head>" in content:
                content = content.replace("</head>", injection + "</head>", 1)
            elif "</body>" in content:
                content = content.replace("</body>", injection + "</body>", 1)
            resp = make_response(content)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp
        else:
            return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head><title>DvDRip</title></head>
                <body style="background: #f0f0f0; padding: 20px; font-family: sans-serif;">
                    <h1>Application Starting...</h1>
                    <p>Frontend assets are being loaded. Please refresh in a moment.</p>
                </body>
                </html>
            """), 503

    @app.route("/<path:path>")
    def serve_static(path):
        # Skip API routes (should not reach here due to blueprint)
        if path.startswith("api/"):
            return jsonify({"ok": False, "error": "not found"}), 404
        
        # Try to serve as a static file first (check both root and assets)
        root_file = static_root / path
        if root_file.exists() and root_file.is_file():
            return send_from_directory(str(static_root), path)

        # If the path references the assets folder (or assets folder is separate),
        # attempt to serve from static_assets. Normalize the filename when needed.
        asset_candidate = static_assets / (path[len("assets/"): ] if path.startswith("assets/") else path)
        if asset_candidate.exists() and asset_candidate.is_file():
            filename = path[len("assets/"): ] if path.startswith("assets/") else path
            return send_from_directory(str(static_assets), filename)
        
        # If not found, serve index.html for SPA routing (inject runtime config)
        index_path = static_root / "index.html"
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")
            injection = (
                "<script>try{if(!localStorage.getItem('dvdflix_api_url')){localStorage.setItem('dvdflix_api_url',window.location.origin);} }catch(e){};</script>"
            )
            if "</head>" in content:
                content = content.replace("</head>", injection + "</head>", 1)
            elif "</body>" in content:
                content = content.replace("</body>", injection + "</body>", 1)
            resp = make_response(content)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp
        else:
            return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head><title>DvDRip</title></head>
                <body style="background: #f0f0f0; padding: 20px; font-family: sans-serif;">
                    <h1>Application Starting...</h1>
                    <p>Frontend assets are being loaded. Please refresh in a moment.</p>
                </body>
                </html>
            """), 503

    return app
