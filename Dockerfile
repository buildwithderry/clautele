# syntax=docker/dockerfile:1
FROM node:22-slim AS base

# Python untuk bot + git (dipakai Claude Code untuk bekerja di repo)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# ---- stage test: docker build --target test . ----
FROM base AS test
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
RUN python -m pytest -q

# ---- stage runtime (default) ----
FROM base AS runtime
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src

# Image node:22 menyediakan user 'node' (uid 1000). Claude Code menolak
# bypassPermissions sebagai root, jadi jalankan sebagai non-root.
RUN mkdir -p /workspace /data && chown -R node:node /workspace /data
USER node
ENV HOME=/home/node \
    CLAUDE_WORKDIR=/workspace \
    DATA_DIR=/data

CMD ["python", "-m", "clautele"]
