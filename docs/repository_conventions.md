# Repository Conventions

This document defines the canonical folder and lane conventions for this repository.

## Top-level folder purpose

| Area | Purpose | Ownership |
|---|---|---|
| `apps/` | Service and application implementation lanes | Split by lane below |
| `data/` | Analytical inputs and source data storage | Shared data area; not an app lane |
| `artifacts/` | Generated outputs from runs | Generated output area; not an app lane |
| `infra/docker/` | Container and runtime configuration | Shared infrastructure area |
| `docs/` | Repository and project documentation | Shared documentation area |
| `scripts/` | Operational helper scripts | Shared operational area |

## Lane ownership

| Lane | Owner |
|---|---|
| `apps/api` | Marek |
| `apps/worker` | Marek during scaffold phase; later shared with data and engine integrations as assigned |
| `apps/ui` | Iris |

## Folder conventions

### `apps/api`
- **Belongs here:** API-facing backend service code, service entry points, request handling layers, and backend code that exists to serve the API lane.
- **Does not belong here:** worker execution logic, core engine logic, UI code, or cross-lane shared code.

### `apps/worker`
- **Belongs here:** background orchestration code, worker entry points, and backend execution code that exists to run outside the API request layer.
- **Does not belong here:** API route layers, UI code, or core engine math unless explicitly assigned later.

### `apps/ui`
- **Belongs here:** frontend application code, UI entry points, presentation logic, and user-facing application structure.
- **Does not belong here:** backend service logic, worker logic, or engine logic.

### `data`
- **Belongs here:** source datasets, analytical inputs, and data files used by the repository outside application code.
- **Does not belong here:** application source code, generated run outputs, infrastructure config, or project documentation.

### `artifacts`
- **Belongs here:** generated outputs from runs, exports, reports, and other reproducible run artifacts.
- **Does not belong here:** source datasets, application source code, hand-authored documentation, or infrastructure config.

### `infra/docker`
- **Belongs here:** container definitions, runtime container config, and Docker-related infrastructure files.
- **Does not belong here:** service business logic, app source files, analytical data, or generated artifacts.

### `docs`
- **Belongs here:** canonical repository documentation, project notes, and durable written guidance for contributors.
- **Does not belong here:** executable application code, generated outputs, datasets, or runtime config files.

### `scripts`
- **Belongs here:** operational helper scripts used to support repository tasks.
- **Does not belong here:** long-lived service implementation code, application packages, documentation, or generated outputs.

## Boundary rule

Do not mix service implementation, generated outputs, datasets, infrastructure config, documentation, and helper scripts in the same lane. Place files in the area that matches their primary purpose.
