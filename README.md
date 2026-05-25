# Project Phoenix

Project Phoenix is the central repository for the platform foundation. At the current stage, it provides the initial repository layout, ownership boundaries, and a small Python backend developer workflow baseline.

## Start Here

- Read [docs/repository_conventions.md](docs/repository_conventions.md) for canonical folder purpose, lane ownership, and placement rules.
- Use the root of the repo as the entry point for understanding where API, worker, UI, data, artifacts, infrastructure, and scripts belong.

## Top-Level Structure

```text
apps/
  api/              Backend API service lane
  worker/           Background worker lane
  ui/               Frontend application lane

data/               Non-Git analytical and source data
artifacts/          Generated outputs from runs
docs/               Repository documentation and conventions
infra/docker/       Container and runtime configuration area
scripts/            Developer helper scripts
```

## Current A1 Foundation Status

The repository currently includes:

- initial lane structure for `apps/api`, `apps/worker`, and `apps/ui`
- canonical repository conventions in [docs/repository_conventions.md](docs/repository_conventions.md)
- a repo-level Ruff baseline for the Python backend footprint
- minimal local environment file guidance via `.env.example`
- developer scripts for formatting and linting the backend Python paths in `scripts/`

## Not Fully Built Yet

The repository is still in foundation mode. It does not yet provide a fully built runtime, CI pipeline, Docker workflow, or substantive feature implementation across the application lanes.

## License

Project Phoenix is licensed under the [Apache License, Version 2.0](LICENSE).
This permissive license supports community contributions while allowing commercial use, private use, redistribution, modification, and proprietary products built from the project, subject to the license terms.

Contributions are accepted under the same Apache-2.0 terms unless explicitly stated otherwise. See [CONTRIBUTING.md](CONTRIBUTING.md) for the inbound contribution note.
