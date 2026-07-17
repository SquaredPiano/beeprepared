# One image serves all three roles - API, worker, beat - selected by the command
# in docker-compose.yml. They share code and dependencies, so separate images
# would only cost build cache.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ffmpeg normalises audio at ingest, texlive typesets exams, libxml2 backs
# python-pptx.
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

# Dependencies first: they change far less often than the code.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . backend/

RUN useradd --create-home --uid 10001 bee \
    && mkdir -p /data \
    && chown -R bee:bee /app /data
USER bee

ENV BEE_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
