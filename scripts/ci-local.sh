#!/usr/bin/env bash
# Build the CI Docker image (if missing) and run the 'test' job with act using that image.
# Usage: ./scripts/ci-local.sh [--no-build] [--image NAME] [--act-args "..."]

set -euo pipefail

IMAGE_NAME="nfl-data-aggregator-ci:latest"
BUILD_IMAGE=true
ACT_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)
      BUILD_IMAGE=false
      shift
      ;;
    --image)
      IMAGE_NAME="$2"
      shift 2
      ;;
    --act-args)
      ACT_ARGS="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

if $BUILD_IMAGE; then
  echo "Checking for Docker image ${IMAGE_NAME}..."
  if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    echo "Image not found; building ${IMAGE_NAME} from .github/ci.Dockerfile"
    docker build -f .github/ci.Dockerfile -t "${IMAGE_NAME}" .
  else
    echo "Image ${IMAGE_NAME} already exists; skipping build"
  fi
fi

# Ensure .secrets exists (act requires it if workflow uses secrets)
if [ ! -f .secrets ]; then
  echo ".secrets file not found. Creating a template .secrets with empty values (won't be committed)."
  cat > .secrets <<'EOF'
CODECOV_TOKEN=
ODDS_API_KEY=
SKIP_RUFF=true
EOF
  chmod 600 .secrets
fi

echo "Running act using image ${IMAGE_NAME}"
act -j test --secret-file .secrets -P ubuntu-latest="${IMAGE_NAME}" ${ACT_ARGS}

