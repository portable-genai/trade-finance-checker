# B4 Trade-Finance Document Checker : container image for the GCP profile.
#
# Multi-stage build. The runtime image installs the [gcp] extra so the managed-service
# adapters work; the API serves on :8094. Region and credentials come from the runtime
# environment (Cloud Run / Agent Runtime inject ADC), never baked into the image.

# --- build stage ------------------------------------------------------------ #
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build deps first for layer caching.
COPY pyproject.toml README.md ./
COPY requirements-gcp.lock ./
COPY src ./src
COPY config ./config

RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements-gcp.lock && pip install --no-deps .

# --- runtime stage ---------------------------------------------------------- #
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    TRADE_FINANCE_PROFILE=gcp \
    PORT=8094

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY src ./src
COPY config ./config
COPY eval ./eval

USER appuser
EXPOSE 8094

# Liveness: the /healthz endpoint reports profile + region.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8094\")}/healthz')" || exit 1

CMD ["python", "-m", "trade_finance_checker.api.app"]
