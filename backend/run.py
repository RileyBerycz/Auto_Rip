import logging

from flask import request

from backend.app import create_app, socketio

app = create_app()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@app.before_request
def _log_requests() -> None:
    # Keep request visibility in container logs for Dockge troubleshooting.
    app.logger.info("%s %s", request.method, request.path)


if __name__ == "__main__":
    host = app.config["BACKEND_HOST"]
    port = app.config["BACKEND_PORT"]
    print(f"DVDFlix backend starting on {host}:{port}", flush=True)
    socketio.run(app, host=host, port=port, log_output=True)
