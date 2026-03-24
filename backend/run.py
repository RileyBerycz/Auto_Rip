from backend.app import create_app, socketio

app = create_app()


if __name__ == "__main__":
    socketio.run(app, host=app.config["BACKEND_HOST"], port=app.config["BACKEND_PORT"])
