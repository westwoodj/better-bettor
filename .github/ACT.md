Running the GitHub Actions workflow locally with `act`

This document explains how to emulate the repository's GitHub Actions workflow (`.github/workflows/ci.yml`) locally using `act` so you can iterate on CI without pushing to GitHub.

Prerequisites
- Docker must be installed and running on your machine.
  - Windows: Docker Desktop (ensure WSL2 enabled if required).
  - macOS: Docker Desktop.
  - Linux: Docker Engine.
- `act` installed. See https://github.com/nektos/act/releases for binaries or use a package manager.
  - macOS (Homebrew): `brew install act-cli`
  - Windows (Scoop): `scoop install act`
  - Or download the binary and add it to PATH.

Prepare secrets for local runs
Create a file named `.secrets` in the repository root with the repository secrets the workflow expects. Example minimal file:

```
CODECOV_TOKEN=
ODDS_API_KEY=
```

Notes:
- Leaving `CODECOV_TOKEN` empty will cause the workflow's Codecov step to be skipped (the CI workflow has a conditional that checks for a non-empty token).
- Keep `.secrets` out of version control. Add `.secrets` to `.gitignore` (already done in this repo).

Build a pre-cached CI Docker image (optional, speeds up `act` runs)
A prebuilt image contains Python, pipenv, the project dependencies from `Pipfile.lock`, and dev tools (pytest, ruff, coverage). Build it once and reuse it for fast `act` runs.

From the repo root run:

```bash
# Linux / macOS (build default platform)
docker build -f .github/ci.Dockerfile -t nfl-data-aggregator-ci:latest .

# On Apple Silicon or when needing amd64 compat, add --platform
# (you must have Docker configured to support multi-arch or use buildx)
docker build --platform linux/amd64 -f .github/ci.Dockerfile -t nfl-data-aggregator-ci:latest .
```

Use the prebuilt image with `act`
Map the `ubuntu-latest` runner label to the built image so `act` runs inside that container (this avoids installing deps on every run).

```bash
# With image you built locally
act -j test --secret-file .secrets -P ubuntu-latest=nfl-data-aggregator-ci:latest

# If you built for amd64 on Apple Silicon, also include container architecture flag
act -j test --secret-file .secrets -P ubuntu-latest=nfl-data-aggregator-ci:latest --container-architecture linux/amd64
```

Run the `test` job directly without the prebuilt image (default behavior)

```bash
act -j test --secret-file .secrets -P ubuntu-latest=nektos/act-environments-ubuntu:18.04
```

Verbose debug output
Add `-v` to the `act` command to enable verbose logging for debugging:

```bash
act -j test --secret-file .secrets -P ubuntu-latest=nfl-data-aggregator-ci:latest -v
```

Faster iteration tips
- Pre-build the Docker image (as shown) to avoid repeated package installs.
- Use `act`'s `--reuse` mode or map to a local image that already contains dependencies.

Troubleshooting
- Docker must be running and accessible. If `act` fails to create containers, check Docker Desktop or run `docker ps`.
- If pipenv install fails in the Dockerfile, check network access or the `Pipfile.lock` consistency.
- If Codecov upload fails locally, keep `CODECOV_TOKEN` empty in `.secrets` to skip that step in our workflow.

If you'd like, I can also add a small `Makefile` target to build the Docker image and run `act` with the correct flags. Let me know and I'll add it.
