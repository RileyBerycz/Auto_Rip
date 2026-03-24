FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    lsdvd \
    eject \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend

ENV PYTHONPATH=/app
EXPOSE 7272

# Note: makemkvcon is expected to be available on the host/server environment.
CMD ["python", "-m", "backend.run"]
