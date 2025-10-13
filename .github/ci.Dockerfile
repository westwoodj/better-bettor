FROM python:3.14-slim

# Install system deps required for pipenv and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app dir
WORKDIR /workspace

# Copy Pipfile and Pipfile.lock first to leverage Docker layer caching
COPY Pipfile Pipfile.lock /workspace/

# Install pipenv and project deps from lockfile deterministically
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install pipenv \
    && pipenv install --deploy --system --ignore-pipfile

# Install test & dev tools into the image to speed local runs
RUN pip install pytest ruff coverage codecov requests

# Default workdir when running container
WORKDIR /github/workspace

# Keep container lightweight - do not copy source by default
CMD ["/bin/bash"]

