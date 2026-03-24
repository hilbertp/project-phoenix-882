#!/usr/bin/env sh
set -eu

ruff check apps/api apps/worker
