# Stage 1: Build React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --frozen-lockfile
COPY frontend ./
RUN npm run build

# Stage 2: Build Python backend with bundled frontend
FROM python:3.12-slim

WORKDIR /app

RUN set -eux; \
        # Enable contrib and non-free repositories so libdvd-pkg (libdvdcss) can be installed
        printf '%s\n' \
            'deb http://deb.debian.org/debian trixie main contrib non-free' \
            'deb http://deb.debian.org/debian-security trixie-security main contrib non-free' \
            'deb http://deb.debian.org/debian trixie-updates main contrib non-free' \
            > /etc/apt/sources.list.d/non-free.list; \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            lsdvd \
            eject \
            handbrake-cli \
            ffmpeg \
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
        # Ensure libdvdcss is available for encrypted DVD support via libdvd-pkg
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libdvd-pkg; \
        DEBIAN_FRONTEND=noninteractive dpkg-reconfigure -f noninteractive libdvd-pkg || true; \
        rm -rf /tmp/*; \
        command -v makemkvcon >/dev/null; \
        rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY dvdflix_core /app/dvdflix_core
COPY backend /app/backend
COPY scripts /app/scripts

# Copy bundled frontend from builder stage
COPY --from=frontend-builder /frontend/dist /app/backend/static

ENV PYTHONPATH=/app
EXPOSE 7272

CMD ["python", "-m", "backend.run"]
