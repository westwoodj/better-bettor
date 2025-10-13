Repository GitHub Secrets

This repository's CI workflow uses a small set of GitHub Secrets. Add them in your repository settings (Settings → Secrets → Actions) or via the GitHub CLI.

Mandatory secrets
- `CODECOV_TOKEN` — token used by Codecov to associate coverage uploads with the repository. Create a Codecov account for your repo and copy the token into this secret.


Optional secrets (useful for tests or integration)
- `ODDS_API_KEY` — API key for The Odds API if you want CI or workflows to exercise the odds adapter against the live API. Do NOT put production secrets in public repos.
- `ESPN_API_KEY` — (if you add a private key or proxy) any ESPN-related secret (not currently required by the code as implemented).
- `GENAI_API_KEY` — (if you add AI features) API key for Generative AI services.

How to add a secret via the GitHub web UI
1. Go to your repository on github.com.
2. Click Settings → Secrets and variables → Actions.
3. Click "New repository secret".
4. Enter the secret name (e.g., CODECOV_TOKEN) and paste the value. Save.

How to add a secret using the GitHub CLI

Install gh (https://cli.github.com/) and authenticate with `gh auth login`.

```bash
# Create or update a repository secret
# Replace ORG/REPO with your repo and the token value with your secret
echo -n "<value>" | gh secret set CODECOV_TOKEN --body - --repo ORG/REPO
```

Local secrets for `act` (local workflow emulation)
Create a file named `.secrets` (or any file) with lines like:

```
CODECOV_TOKEN=your_token_here
ODDS_API_KEY=your_odds_api_key_here
```

Then run `act` with `--secret-file .secrets` to provide them to the workflow.

Security notes
- Keep secrets out of the repository and CI logs.
- Prefer repository-level secrets (not environment or organization-wide unless needed).
- Rotate API keys periodically.

