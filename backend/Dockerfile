# ==============================================================================
# BeePrepared Backend Dockerfile
# ==============================================================================

# Use official Python 3.11 slim image for smaller footprint
FROM python:3.11-slim

# Set environment variables
# PYTHONDONTWRITEBYTECODE: Prevents Python from writing pyc files to disc
# PYTHONUNBUFFERED: Prevents Python from buffering stdout and stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# ------------------------------------------------------------------------------
# 1. Install System Dependencies
# ------------------------------------------------------------------------------
# We combine updates and installs in one layer to reduce image size.
# Dependencies:
# - ffmpeg: Required for audio/video processing
# - git: Required for some python packages
# - texlive-*: Required for LaTeX (PDF) generation
# - libxml2-dev, libxslt-dev: Required for lxml (PPTX support)
# - zlib1g-dev: Required for compression
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    lmodern \
    cm-super \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# 2. Install Python Dependencies
# ------------------------------------------------------------------------------
# Copy requirements first to leverage Docker cache
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# 3. Copy Application Code
# ------------------------------------------------------------------------------
# We copy code into a 'backend' directory so that it is treated as a package.
# This matches the local structure where 'backend' contains __init__.py.
COPY . backend/

# Set PYTHONPATH so python can find the 'backend' package in /app
ENV PYTHONPATH=/app

# ------------------------------------------------------------------------------
# 4. Runtime Configuration
# ------------------------------------------------------------------------------
# Expose port (FastAPI default)
EXPOSE 8000

# Healthcheck command for Docker Compose
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the application using module syntax (backend.main:app)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
