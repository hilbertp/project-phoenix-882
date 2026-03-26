#!/usr/bin/env sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON=python
fi

TMP_OUTPUT=$(mktemp)
cleanup() {
  rm -f "$TMP_OUTPUT"
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

set +e
"$PYTHON" -m unittest -v \
  tests.test_a2_stack_workflow \
  tests.test_a2_postgres_persistence \
  tests.test_a2_mounts_and_env_contract \
  >"$TMP_OUTPUT" 2>&1
status=$?
set -e

OUTPUT_FILE="$TMP_OUTPUT" "$PYTHON" <<'PY'
from __future__ import annotations

import os
from pathlib import Path


output_path = Path(os.environ["OUTPUT_FILE"])
lines = output_path.read_text().splitlines()

checks = [
    {
        "test_name": "test_local_stack_workflow_runs_start_smoke_and_stop_sequence",
        "title": "Test 1 — Runtime workflow check",
        "meaning": "Meaning: the stack can start, report healthy shape, and stop cleanly",
    },
    {
        "test_name": "test_postgres_value_survives_service_recreation",
        "title": "Test 2 — Persistence integration check",
        "meaning": "Meaning: database state survives container recreation",
    },
    {
        "test_name": "test_compute_containers_expose_expected_storage_mounts",
        "title": "Test 3 — Container mount integration check",
        "meaning": "Meaning: storage is connected to the compute containers",
    },
    {
        "test_name": "test_compute_containers_expose_expected_runtime_env_contract",
        "title": "Test 4 — Runtime contract integration check",
        "meaning": "Meaning: the services receive the expected local runtime configuration",
    },
]
check_map = {check["test_name"]: check for check in checks}
results = {
    check["test_name"]: {"status": "FAIL", "detail": "result not reported"}
    for check in checks
}

for line in lines:
    if " ... " not in line or not line.startswith("test_"):
        continue

    prefix, raw_result = line.rsplit(" ... ", 1)
    test_name = prefix.split()[0]
    check = check_map.get(test_name)
    if check is None:
        continue

    if raw_result == "ok":
        results[test_name] = {"status": "PASS", "detail": ""}
    elif raw_result == "FAIL":
        results[test_name] = {"status": "FAIL", "detail": ""}
    elif raw_result == "ERROR":
        results[test_name] = {"status": "FAIL", "detail": "error"}
    elif raw_result.startswith("skipped "):
        reason = raw_result[len("skipped ") :].strip()
        results[test_name] = {"status": "SKIP", "detail": reason}
    else:
        results[test_name] = {"status": "FAIL", "detail": raw_result}

pass_count = 0
fail_count = 0
skip_count = 0

print("Phoenix Runtime Check")
print()

for check in checks:
    result = results[check["test_name"]]
    status = result["status"]
    detail = result["detail"]

    print(check["title"])
    print(check["meaning"])

    if status == "PASS":
        pass_count += 1
        print("PASS")
    elif status == "SKIP":
        skip_count += 1
        print("SKIP")
        if detail:
            print(f"Reason: {detail}")
    else:
        fail_count += 1
        print("FAIL")
        if detail:
            print(f"Detail: {detail}")

    print()

print("Result")
print(f"{pass_count} of {pass_count + fail_count + skip_count} checks passed")
print()
print("Overall")
if fail_count == 0:
    print("PASS")
else:
    print("FAIL")
PY

if [ "$status" -ne 0 ]; then
  printf '\nDetailed unittest output:\n'
  cat "$TMP_OUTPUT"
fi

exit "$status"