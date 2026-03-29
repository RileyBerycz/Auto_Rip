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
            automake \
            autoconf \
            libtool \
            pkg-config \
            libc6-dev \
            libssl-dev \
            libexpat1-dev \
            libavcodec-dev \
            zlib1g-dev; \
        MKV_VER=""; OSS_TGZ=""; BIN_TGZ=""; \
        for v in 1.18.3 1.18.2 1.18.1 1.18.0 1.17.9 1.17.8 1.17.7; do \
            OSS_TGZ="/tmp/makemkv-oss-${v}.tar.gz"; \
            BIN_TGZ="/tmp/makemkv-bin-${v}.tar.gz"; \
            if curl -fSL "https://www.makemkv.com/download/makemkv-oss-${v}.tar.gz" -o "${OSS_TGZ}" \
                 && curl -fSL "https://www.makemkv.com/download/makemkv-bin-${v}.tar.gz" -o "${BIN_TGZ}"; then \
                MKV_VER="$v"; \
                break; \
            fi; \
            rm -f "${OSS_TGZ}" "${BIN_TGZ}"; \
        done; \
        if [ -z "$MKV_VER" ]; then echo "No supported MakeMKV source tarball found"; exit 1; fi; \
        tar -xzf "${OSS_TGZ}" -C /tmp; \
        tar -xzf "${BIN_TGZ}" -C /tmp; \
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
            automake \
            autoconf \
            libtool \
            pkg-config \
            libc6-dev \
            libssl-dev \
            libexpat1-dev \
            libavcodec-dev \
            zlib1g-dev; \
        command -v makemkvcon >/dev/null; \
        rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend

ENV PYTHONPATH=/app
EXPOSE 7272

# makemkvcon is built into this image during docker build.
CMD ["python", "-m", "backend.run"]
