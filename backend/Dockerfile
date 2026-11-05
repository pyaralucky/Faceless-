# syntax=docker/dockerfile:1.7
# Debian trixie ships FFmpeg 7.x (drawtext text_align, xfade, libass) and Python 3.13.
FROM python:3.13-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-core curl tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .
CMD ["pytest", "-q"]

FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data && chown app:app /data
COPY --chown=app:app . .
USER app
ENV STORAGE_ROOT=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "2"]
