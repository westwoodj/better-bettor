FROM python:3.14-slim

# Install system deps required for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create app dir
WORKDIR /workspace

# Copy project metadata and lockfile first to leverage Docker layer caching
COPY pyproject.toml uv.lock /workspace/

# Install project + dev deps from the lockfile deterministically, outside the
# mounted workspace so they survive in the image
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-install-project
ENV PATH="/opt/venv/bin:$PATH"

# Default workdir when running container
WORKDIR /github/workspace

# Keep container lightweight - do not copy source by default
CMD ["/bin/bash"]
