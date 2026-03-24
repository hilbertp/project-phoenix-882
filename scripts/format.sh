#!/usr/bin/env sh
set -eu

ruff format apps/api apps/worker
