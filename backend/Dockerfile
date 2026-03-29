FROM python:3.12-slim

WORKDIR /app

RUN set -eux; \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            lsdvd \
            eject \
            ca-certificates \
            build-essential \
            automake \
            autoconf \
            libtool \
            pkg-config \
            libc6-dev \
            libssl-dev \
            libexpat1-dev \
            libavcodec-dev \
            libgl1-mesa-dev \
            qtbase5-dev \
            zlib1g-dev \
            curl \
            less \
            wget; \
        cd /tmp; \
        MKV_VER=""; \
        for v in 1.18.3 1.18.2 1.18.1 1.18.0 1.17.9 1.17.8 1.17.7; do \
            if curl -fSL "https://www.makemkv.com/download/makemkv-oss-${v}.tar.gz" -o "makemkv-oss-${v}.tar.gz" \
               && curl -fSL "https://www.makemkv.com/download/makemkv-bin-${v}.tar.gz" -o "makemkv-bin-${v}.tar.gz"; then \
                MKV_VER="$v"; \
                break; \
            fi; \
            rm -f "makemkv-oss-${v}.tar.gz" "makemkv-bin-${v}.tar.gz"; \
        done; \
        test -n "$MKV_VER"; \
        tar xzf "makemkv-oss-${MKV_VER}.tar.gz"; \
        tar xzf "makemkv-bin-${MKV_VER}.tar.gz"; \
        cd "/tmp/makemkv-oss-${MKV_VER}"; \
        ./configure; \
        make -j"$(nproc)"; \
        make install; \
        cd "/tmp/makemkv-bin-${MKV_VER}"; \
        mkdir -p tmp; \
        printf 'yes\n' > tmp/eula_accepted; \
        make -j"$(nproc)"; \
        make install; \
        ldconfig; \
        rm -rf /tmp/*; \
        command -v makemkvcon >/dev/null; \
        rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend

ENV PYTHONPATH=/app
EXPOSE 7272

CMD ["python", "-m", "backend.run"]
