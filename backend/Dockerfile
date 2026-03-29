FROM ubuntu:24.04

WORKDIR /app

RUN set -eux; \
        apt-get update; \
        apt-get install -y --no-install-recommends software-properties-common; \
        add-apt-repository multiverse; \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            python3 \
            python3-pip \
            python3-venv \
            python-is-python3 \
            lsdvd \
            eject \
            makemkv \
            ca-certificates; \
        command -v makemkvcon >/dev/null; \
        rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --break-system-packages --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend

ENV PYTHONPATH=/app
EXPOSE 7272

# makemkvcon is installed from Ubuntu multiverse.
CMD ["python", "-m", "backend.run"]
