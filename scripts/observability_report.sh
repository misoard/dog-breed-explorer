#!/usr/bin/env bash
#
# M9 — regenerate the Elementary observability report from the local warehouse.
#
# WHAT THIS IS: the dbt package (dbt/packages.yml) already CAPTURES every test result
# (pass/warn/fail, timings, the warn/error split) into `main_elementary.*` tables on an
# automatic on-run-end hook, every `dbt build`. This script renders the human-facing
# half — the `edr` CLI reads those tables and writes a single-file HTML dashboard.
#
# WHY IT'S A SCRIPT, NOT A COMMITTED FILE: the report is generated and ~5 MB, so it is
# regenerable-not-committed, exactly like the dbt docs lineage graph (DECISIONS §5 — the
# laptop serves the demo; CI proves the pipeline). Run this, open the HTML, screenshot for
# the debrief.
#
# WHY A SEPARATE VENV: `edr` is only a READER of the duckdb file — it shares none of the
# pipeline's runtime. It gets its own `.venv-edr/` so it can never perturb the pipeline
# `.venv` (this project has already been bitten once by a protobuf/TensorFlow version
# clash — env hygiene is load-bearing here). Version pinned to match dbt/packages.yml;
# the edr CLI and the dbt package must agree on major.minor or edr refuses to run.
#
# Usage:
#   ./scripts/observability_report.sh                 # reads ./dogs_dev.duckdb (the dev build)
#   ./scripts/observability_report.sh ./dogs.duckdb   # ...or the prod build
#
# First run bootstraps .venv-edr (a slow pip install); later runs are seconds.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDR_VERSION="0.25.1"                       # keep in lockstep with dbt/packages.yml
EDR_VENV="$REPO_ROOT/.venv-edr"
DB_PATH="${1:-$REPO_ROOT/dogs_dev.duckdb}"

# Load .env so an md: path can find MOTHERDUCK_TOKEN (same reason as run_pipeline.sh).
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

# A MotherDuck path (md:dogs) is a connection string, not a file — don't absolutise or
# stat it. This is what lets the report read the CLOUD store the cron refreshes at 02:00
# (M9 Part B): `./scripts/observability_report.sh md:dogs`. A local file path still gets
# absolutised so the edr profile (read from a temp dir) resolves it unambiguously.
if [[ "$DB_PATH" == md:* ]]; then
  if [[ -z "${MOTHERDUCK_TOKEN:-}" ]]; then
    echo "ERROR: $DB_PATH needs MOTHERDUCK_TOKEN (set it in .env or the environment)." >&2
    exit 1
  fi
else
  DB_PATH="$(cd "$(dirname "$DB_PATH")" && pwd)/$(basename "$DB_PATH")"
  if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: no warehouse at $DB_PATH — run the pipeline first (scripts/run_pipeline.sh)." >&2
    exit 1
  fi
fi

# Bootstrap the isolated edr venv on first run.
if [[ ! -x "$EDR_VENV/bin/edr" ]]; then
  echo "--- bootstrapping edr $EDR_VERSION into $EDR_VENV (first run only)"
  python3 -m venv "$EDR_VENV"
  "$EDR_VENV/bin/pip" install --quiet --upgrade pip
  "$EDR_VENV/bin/pip" install --quiet "elementary-data[duckdb]==$EDR_VERSION"
fi

# edr connects through a dbt profile literally named `elementary`. It points at the same
# duckdb file and the schema the package wrote its tables to: our models use
# `+schema: elementary`, which dbt concatenates onto the `main` target schema, so the
# tables live in `main_elementary`.
PROFILES_DIR="$(mktemp -d)"
trap 'rm -rf "$PROFILES_DIR"' EXIT
cat > "$PROFILES_DIR/profiles.yml" <<YAML
elementary:
  outputs:
    default:
      type: duckdb
      path: "$DB_PATH"
      schema: main_elementary
      threads: 1
  target: default
YAML

OUT="$REPO_ROOT/elementary_report.html"
echo "--- generating report from $DB_PATH"
# No --project-dir: edr renders from its OWN internal dbt project (bundled in the edr
# package); it only needs --profiles-dir to know how to reach our warehouse.
"$EDR_VENV/bin/edr" report \
  --profiles-dir "$PROFILES_DIR" \
  --file-path "$OUT"

echo "--- done: $OUT"
echo "    open it:  open \"$OUT\""
