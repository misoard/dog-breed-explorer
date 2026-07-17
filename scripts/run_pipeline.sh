#!/usr/bin/env bash
#
# The pipeline, in one place: ingest -> dbt build. Both CI workflows and a local
# run invoke THIS, so there is exactly one definition of "run the pipeline".
#
# The rule (M5): deduplicate in the script, not in the CI system. ci.yml and
# scheduled.yml are then ~8 lines of trigger + boilerplate each, they stay
# genuinely separate status checks (they answer different questions), and none
# of this is locked to GitHub Actions.
#
# THE SEAM THIS EXISTS TO CLOSE: ingest.py and dbt are two separate programs
# that must agree on one DuckDB file path. ingest.py takes --db (relative to the
# CWD); dbt reads DBT_DUCKDB_PATH from profiles.yml (relative to dbt/, since dbt
# must run from there). Set one env var, pass it to both, and make it ABSOLUTE so
# the two different working directories cannot disagree about what "../dogs.duckdb"
# means. That resolution is the whole job of the first half of this script.
#
# Usage:
#   ./scripts/run_pipeline.sh                    # -> prod target, ./dogs.duckdb
#   DBT_TARGET=dev ./scripts/run_pipeline.sh     # -> dev target, ./dogs_dev.duckdb
#   DBT_DUCKDB_PATH=/tmp/fresh.duckdb ./scripts/run_pipeline.sh   # -> anywhere
#
# Requires DOG_API_KEY in the environment (or a gitignored .env at the repo root).
# /v1/breeds returns 403 without it. The key is never logged.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# dbt's default is `dev` on purpose (profiles.yml), so a bare `dbt build` cannot
# touch the serving copy. This script is what CI runs, and CI runs prod — so prod
# is the default HERE, and reaching dev is the deliberate act. Same principle,
# opposite direction, because the two callers have opposite risks.
DBT_TARGET="${DBT_TARGET:-prod}"

# One path, absolute, shared by both programs. The default mirrors profiles.yml's
# own default for the chosen target; setting DBT_DUCKDB_PATH overrides both at once.
if [[ -z "${DBT_DUCKDB_PATH:-}" ]]; then
  if [[ "$DBT_TARGET" == "dev" ]]; then
    DBT_DUCKDB_PATH="$REPO_ROOT/dogs_dev.duckdb"
  else
    DBT_DUCKDB_PATH="$REPO_ROOT/dogs.duckdb"
  fi
fi
# Absolute-ise whatever we were handed, for the same reason.
DBT_DUCKDB_PATH="$(cd "$(dirname "$DBT_DUCKDB_PATH")" && pwd)/$(basename "$DBT_DUCKDB_PATH")"
export DBT_DUCKDB_PATH

# Prefer the project venv when there is one. dbt needs protobuf>=6 and the conda
# base TensorFlow stack pins <4 — they cannot coexist, and a script that silently
# picked up the wrong interpreter is a failure this project has already hit once.
# CI has no .venv (pip install goes into setup-python's env), so it falls through
# to PATH, which is exactly right.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

echo "--- pipeline: target=$DBT_TARGET db=$DBT_DUCKDB_PATH"
echo "--- python:   $(command -v python)"
echo "--- dbt:      $(command -v dbt)"

# 1. Ingest. Fetches all breeds, validates completeness IN MEMORY, then replaces
#    today's run_date partition in one transaction. A partial or failed fetch
#    exits non-zero here and never touches last-good data (set -e stops us).
echo "--- [1/2] ingest"
python "$REPO_ROOT/ingestion/ingest.py" --db "$DBT_DUCKDB_PATH"

# 2. Build + test. `dbt build` interleaves them: each model runs, then its tests
#    run, and a failing test blocks that model's children. MUST run from dbt/ —
#    from the repo root dbt falls back to ~/.dbt/profiles.yml and fails with a
#    misleading "profile not found" that looks like a broken install.
echo "--- [2/2] dbt build --target $DBT_TARGET"
cd "$REPO_ROOT/dbt"
dbt build --target "$DBT_TARGET"
