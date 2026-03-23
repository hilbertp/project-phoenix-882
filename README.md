# Project Phoenix

Central repository for Project Phoenix backtesting platform.

See [docs/repository_conventions.md](docs/repository_conventions.md) for canonical repository ownership and placement rules.

## Repository Structure

```
apps/
  ├── api/          - Backend API service
  ├── worker/       - Background worker service
  └── ui/           - Frontend application

data/              - Analytical and source data (non-Git)
artifacts/         - Generated outputs from runs
infra/docker/      - Container and runtime configuration
docs/              - Project documentation
scripts/           - Operational helper scripts
```
