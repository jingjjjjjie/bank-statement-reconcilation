FROM node:22-bookworm-slim AS frontend

WORKDIR /frontend
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY dashboard/frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS codex

ARG CODEX_VERSION=0.154.0
RUN npm install --global "@openai/codex@${CODEX_VERSION}"

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_FRONTEND=/opt/dashboard-frontend

COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
COPY --from=frontend /frontend/dist /opt/dashboard-frontend
RUN mkdir -p /home/app/.codex /workspace/duplicated /workspace/dashboard/.data \
    && chown -R app:app /home/app/.codex /workspace

USER app
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3)"]

CMD ["python", "-m", "dashboard.app", "--host", "0.0.0.0", "--port", "8765"]

# Agent workspace: full Debian Python image plus inspection and test tools.
FROM python:3.12-bookworm AS development

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DASHBOARD_FRONTEND=/opt/dashboard-frontend \
    PATH="/home/app/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential git ripgrep curl procps less vim-tiny \
    && rm -rf /var/lib/apt/lists/*

COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt ./
COPY dashboard/requirements-dev.txt ./dashboard/requirements-dev.txt
RUN pip install --no-cache-dir -r requirements.txt -r dashboard/requirements-dev.txt pytest debugpy

COPY --chown=app:app . .
COPY --from=frontend /frontend/dist /opt/dashboard-frontend
RUN mkdir -p /home/app/.codex /workspace/duplicated /workspace/dashboard/.data \
    && chown -R app:app /home/app/.codex /workspace

USER app
# Trust only the repository mount, whose host ownership may differ.
RUN git config --global --add safe.directory /workspace
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3)"]

CMD ["python", "-m", "dashboard.app", "--host", "0.0.0.0", "--port", "8765"]
