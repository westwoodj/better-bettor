# Convenience Makefile for local CI/test tasks

.PHONY: ci-image act act-image test lint push-ci-image

# Build the pre-cached CI Docker image used to speed up `act` runs
ci-image:
	docker build -f .github/ci.Dockerfile -t nfl-data-aggregator-ci:latest .

# Run the test job using act with the public nektos environment (no prebuilt image)
act:
	act -j test --secret-file .secrets -P ubuntu-latest=nektos/act-environments-ubuntu:18.04

# Run the test job using act with the locally built image (faster)
act-image:
	act -j test --secret-file .secrets -P ubuntu-latest=nfl-data-aggregator-ci:latest

# Run pytest locally (Windows cmd.exe compatible)
test:
	set PYTHONPATH=%CD% && pytest -q

# Lint using ruff
lint:
	ruff check .

# Push the CI Docker image to a registry. You must set DOCKER_REPO (e.g. username/repo).
# Optional env vars:
#   DOCKER_REGISTRY (default: docker.io)
#   DOCKER_TAG (default: latest)
#   DOCKER_USERNAME and DOCKER_PASSWORD (for non-interactive login)
push-ci-image:
	@if [ -z "${DOCKER_REPO}" ]; then \
		echo "Error: DOCKER_REPO must be set (e.g., username/repo)"; exit 1; \
	fi
	@REG=${DOCKER_REGISTRY:-docker.io}; \
	TAG=${DOCKER_TAG:-latest}; \
	IMAGE=$${REG}/${DOCKER_REPO}:$${TAG}; \
	docker build -f .github/ci.Dockerfile -t $${IMAGE} .;
	@if [ -n "${DOCKER_USERNAME}" ] && [ -n "${DOCKER_PASSWORD}" ]; then \
		echo "Logging into ${DOCKER_REGISTRY:-docker.io}..."; \
		echo "${DOCKER_PASSWORD}" | docker login ${DOCKER_REGISTRY:-docker.io} -u "${DOCKER_USERNAME}" --password-stdin; \
	fi
	@docker push $${IMAGE}