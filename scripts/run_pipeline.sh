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

# Load .env so BOTH programs see the secrets. ingest.py self-loads .env for
# DOG_API_KEY, but dbt reads env vars only from the SHELL — and a MotherDuck target
# (md:dogs) needs MOTHERDUCK_TOKEN visible to dbt, not just to ingest.py. Sourcing
# here is the one place that covers both. CI has no .env (secrets arrive as Actions
# env vars already in the shell), so this is skipped there — exactly right.
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

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
# A MotherDuck path is a CONNECTION STRING (md:dogs), not a file — absolutising it
# would turn it into a bogus local path ($REPO_ROOT/md:dogs). So absolute-ise only
# real file paths, and leave md: alone. This is the M9 Part B seam: the SAME env var
# now selects local file OR cloud, and dbt-duckdb routes an md: path to MotherDuck.
# md: requires MOTHERDUCK_TOKEN in the environment (sourced from .env above locally,
# an Actions secret in the cron).
if [[ "$DBT_DUCKDB_PATH" == md:* ]]; then
  if [[ -z "${MOTHERDUCK_TOKEN:-}" ]]; then
    echo "ERROR: DBT_DUCKDB_PATH=$DBT_DUCKDB_PATH needs MOTHERDUCK_TOKEN (set it in .env or an Actions secret)." >&2
    exit 1
  fi
else
  DBT_DUCKDB_PATH="$(cd "$(dirname "$DBT_DUCKDB_PATH")" && pwd)/$(basename "$DBT_DUCKDB_PATH")"
fi
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

# 0. MotherDuck only: create the database once. Connecting to `md:dogs` ATTACHES an
#    existing database — MotherDuck does NOT auto-create it, so a first-ever run 403s
#    with "no database named 'dogs' found". Both writers (ingest.py, dbt) hit that, so
#    the choke point is here, before either connects. IF NOT EXISTS makes it idempotent
#    — free on every subsequent night. Local-file paths need nothing (DuckDB creates the
#    file on open).
if [[ "$DBT_DUCKDB_PATH" == md:* ]]; then
  MD_DB_NAME="${DBT_DUCKDB_PATH#md:}"
  echo "--- [0/2] ensure MotherDuck database '$MD_DB_NAME' exists"
  python -c "import duckdb; duckdb.connect('md:').execute('CREATE DATABASE IF NOT EXISTS \"$MD_DB_NAME\"')"
fi

# 1. Ingest. Fetches all breeds, validates completeness IN MEMORY, then replaces
#    today's run_date partition in one transaction. A partial or failed fetch
#    exits non-zero here and never touches last-good data (set -e stops us).
echo "--- [1/2] ingest"
python "$REPO_ROOT/ingestion/ingest.py" --db "$DBT_DUCKDB_PATH"

# 2. Build + test. `dbt build` interleaves them: each model runs, then its tests
#    run, and a failing test blocks that model's children. MUST run from dbt/ —
#    from the repo root dbt falls back to ~/.dbt/profiles.yml and fails with a
#    misleading "profile not found" that looks like a broken install.
#
#    `dbt deps` FIRST, always: dbt_packages/ is gitignored (downloaded deps, not
#    source), so a fresh checkout — every CI run and the cron's clean VM — has zero
#    packages, and `dbt build` aborts with "expects N package(s)... found 0. Run dbt
#    deps." It's idempotent and fast when already installed (checks the lock), so
#    running it every time costs nothing locally and is required in CI. One place,
#    shared by all three callers — the same reason the pipeline lives in this script.
# M10 (Write-Audit-Publish): atomicity is a property of the DESTINATION, not the caller. Writing gold
# to the CLOUD store must be atomic — dbt materializes a model then tests it, so building straight into
# md:dogs would leave torn/stale gold live on a failed test. So for an `md:` destination we build the
# gold into a SHADOW schema (main_marts_next), test it, then swap it into live main_marts in ONE
# transaction (stage 3, only on full green). A LOCAL file needs none of this (single writer,
# read-after-build), so it builds straight into main_marts. This means `DBT_DUCKDB_PATH=md:dogs
# ./run_pipeline.sh` is atomic whether it's the cron OR a hand-run demo refresh; CI/local (file paths)
# are unchanged. Two explicit branches, NOT a `--vars` array: an empty array under `set -u` is an
# "unbound variable" on macOS's bash 3.2, and the "{marts_schema: ...}" space must survive as one arg.
echo "--- [2/2] dbt deps + build --target $DBT_TARGET"
cd "$REPO_ROOT/dbt"
dbt deps
if [[ "$DBT_DUCKDB_PATH" == md:* ]]; then
  dbt build --target "$DBT_TARGET" --vars "{marts_schema: marts_next}"   # cloud: gold -> shadow schema
else
  dbt build --target "$DBT_TARGET"                                        # local: gold -> main_marts direct
fi

# 3. Publish (CLOUD ONLY): atomically swap the validated shadow gold into live main_marts. A local
#    build already wrote main_marts directly, so this is skipped. Any error here exits non-zero (set
#    -e), which — in the cron — means no success heartbeat pings and the dead man's switch fires.
if [[ "$DBT_DUCKDB_PATH" == md:* ]]; then
  echo "--- [3/3] publish: atomic swap main_marts_next -> main_marts in $DBT_DUCKDB_PATH"
  python "$REPO_ROOT/scripts/publish_motherduck.py" --database "$DBT_DUCKDB_PATH" --drop-shadow
fi
