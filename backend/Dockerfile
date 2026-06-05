# =============================================================================
# BeePrepared backend image.
#
# One image runs all three roles - API, Celery worker, Celery beat - because
# they share the same code and the same dependencies. The role is chosen by the
# command in docker-compose.yml, which keeps the build cache warm across all of
# them instead of rebuilding three near-identical images.
# =============================================================================

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# -----------------------------------------------------------------------------
# System dependencies
#   ffmpeg    - audio/video normalisation during ingest
#   texlive   - typesetting exams to PDF
#   libxml2   - lxml, which python-pptx needs for deck generation
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        texlive-latex-base \
        texlive-fonts-recommended \
        texlive-latex-extra \
        lmodern \
        cm-super \
        libxml2-dev \
        libxslt-dev \
        zlib1g-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: they change far less often than the code, so this layer
# stays cached across almost every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# The code lands in /app/backend so `backend.main` resolves as a package.
COPY . backend/

# Run as a non-root user, and give it ownership of the data volume mount point.
RUN useradd --create-home --uid 10001 bee \
    && mkdir -p /data \
    && chown -R bee:bee /app /data
USER bee

ENV BEE_STORAGE_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

# Overridden per role in docker-compose.yml.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
