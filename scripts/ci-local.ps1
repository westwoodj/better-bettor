Param(
    [switch]$NoBuild,
    [string]$Image = "nfl-data-aggregator-ci:latest",
    [string]$ActArgs = ""
)

# Build the CI Docker image if missing (unless --NoBuild)
if (-not $NoBuild) {
    $img = docker images -q $Image 2>$null
    if (-not $img) {
        Write-Host "Building Docker image $Image from .github/ci.Dockerfile..."
        docker build -f .github/ci.Dockerfile -t $Image .
    } else {
        Write-Host "Docker image $Image already exists; skipping build."
    }
}

# Create a template .secrets file if missing
if (-not (Test-Path -Path ./.secrets)) {
    Write-Host ".secrets not found; creating a template with empty values."
    @"
CODECOV_TOKEN=
ODDS_API_KEY=
SKIP_RUFF=true
"@ | Out-File -FilePath ./.secrets -Encoding ascii
}

Write-Host "Running act with image $Image"
# Use cmd style invocation for act; allow passing extra args
act -j test --secret-file .secrets -P ubuntu-latest="$Image" $ActArgs

