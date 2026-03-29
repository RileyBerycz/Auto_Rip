FROM python:3.12-slim

WORKDIR /app

RUN set -eux; \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            lsdvd \
            eject \
            ca-certificates \
            curl \
            build-essential \
            pkg-config \
            libc6-dev \
            libssl-dev \
            libexpat1-dev \
            zlib1g-dev; \
        MKV_VER=""; \
        for v in 1.18.1 1.18.0 1.17.9 1.17.8 1.17.7; do \
            if curl -fsI "https://www.makemkv.com/download/makemkv-oss-${v}.tar.gz" >/dev/null \
                 && curl -fsI "https://www.makemkv.com/download/makemkv-bin-${v}.tar.gz" >/dev/null; then \
                MKV_VER="$v"; \
                break; \
            fi; \
        done; \
        test -n "$MKV_VER"; \
        curl -fsSL "https://www.makemkv.com/download/makemkv-oss-${MKV_VER}.tar.gz" -o /tmp/makemkv-oss.tar.gz; \
        curl -fsSL "https://www.makemkv.com/download/makemkv-bin-${MKV_VER}.tar.gz" -o /tmp/makemkv-bin.tar.gz; \
        tar -xzf /tmp/makemkv-oss.tar.gz -C /tmp; \
        tar -xzf /tmp/makemkv-bin.tar.gz -C /tmp; \
        cd /tmp/makemkv-oss-${MKV_VER}; \
        ./configure; \
        make -j"$(nproc)"; \
        make install; \
        cd /tmp/makemkv-bin-${MKV_VER}; \
        make -f makefile.linux -j"$(nproc)"; \
        make -f makefile.linux install; \
        rm -rf /tmp/makemkv-*; \
        apt-get purge -y --auto-remove \
            build-essential \
            pkg-config \
            libc6-dev \
            libssl-dev \
            libexpat1-dev \
            zlib1g-dev; \
        command -v makemkvcon >/dev/null; \
        rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend

ENV PYTHONPATH=/app
EXPOSE 7272

# Note: makemkvcon is expected to be available on the host/server environment.
CMD ["python", "-m", "backend.run"]
