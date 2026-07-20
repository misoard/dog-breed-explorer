"""
M10 — Write-Audit-Publish, the PUBLISH phase: atomically swap the validated shadow gold
schema into the live one, in MotherDuck.

THE PROBLEM THIS EXISTS TO CLOSE: dbt materializes a model and THEN tests it, so a failed
test leaves the bad table live (only *downstream* is skipped); building straight into
`md:dogs` also leaves it torn on a mid-build crash. Either way the dashboard — and the
`last_refreshed_at` it prints — can show a mix of fresh and stale gold.

THE SHAPE (Write-Audit-Publish):
  - Phase A (the cron): `dbt build --vars '{marts_schema: marts_next}'` builds + TESTS the
    whole gold layer into a SHADOW schema `main_marts_next`. Any test failure fails the job.
  - Phase B (this script, run only if A passed — GitHub steps are sequential): replaces every
    table in live `main_marts` with its validated shadow copy, inside ONE transaction. A
    mid-swap failure rolls the whole thing back, so the dashboard never sees a torn mix.
    Verified atomic on MotherDuck (ARCHITECTURE_PLAN M10 Step 0).

WHAT THIS DOES NOT TOUCH: `raw.breeds` and `main_elementary`. They APPEND during the build
and must keep their history / trends — a failed run still records itself there (the partition
+ the Elementary failure), which is observability working. Only the regenerated gold marts
need the atomic swap.

`ALTER SCHEMA ... RENAME` is not implemented in DuckDB (verified), so the swap is per-table
`CREATE OR REPLACE ... AS SELECT *` inside a transaction — which IS atomic (all-or-nothing).

MOTHERDUCK_TOKEN is read from the environment by DuckDB for `md:` paths (never passed here).
Any error exits non-zero → the cron step fails → no success heartbeat pings → the dead man's
switch fires. That is the intended failure path.

Usage:
    python scripts/publish_motherduck.py                     # md:dogs, main_marts_next -> main_marts
    python scripts/publish_motherduck.py --drop-shadow       # ...and drop the shadow after
    python scripts/publish_motherduck.py --database md:wap_test --shadow main_marts_next --live main_marts
"""

from __future__ import annotations

import argparse
import sys

import duckdb


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--database", default="md:dogs",
                    help="MotherDuck (or DuckDB) database holding both schemas (default: md:dogs)")
    ap.add_argument("--live", default="main_marts",
                    help="the schema the dashboard reads (default: main_marts)")
    ap.add_argument("--shadow", default="main_marts_next",
                    help="the validated shadow schema Phase A built (default: main_marts_next)")
    ap.add_argument("--drop-shadow", action="store_true",
                    help="drop the shadow schema after a successful swap (else it's left, overwritten next run)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    con = duckdb.connect(args.database)  # MOTHERDUCK_TOKEN read from env for md: paths

    # Swap exactly what the validated build produced — discovered from the catalog, not hard-coded, so
    # adding a mart under models/marts/ flows through with no change here (dbt builds it into the shadow
    # schema; this query returns it). (A *removed* mart would leave a stale table in `live`; not a
    # concern for this fixed 7-table gold layer, and noted rather than silently handled.)
    #   - `table_catalog = current_database()`: on MotherDuck information_schema spans ATTACHED
    #     databases, so scope it to the one we connected to (else a same-named shadow schema in another
    #     db could leak in).
    #   - `table_type = 'BASE TABLE'`: gold is all materialized as tables; never pick up a view.
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = ? AND table_catalog = current_database() "
        "AND table_type = 'BASE TABLE' ORDER BY table_name", [args.shadow]).fetchall()]
    if not tables:
        print(f"ERROR: shadow schema '{args.shadow}' has no tables. Did Phase A run "
              f"`dbt build --vars '{{marts_schema: {args.shadow.split('_', 1)[-1]}}}'`?",
              file=sys.stderr)
        return 1

    con.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.live}"')  # first-ever publish: live may not exist
    print(f"--- publishing {len(tables)} table(s) {args.shadow} -> {args.live} in {args.database}: "
          f"{', '.join(tables)}")

    # The atomic swap. One transaction: all tables replace, or none do.
    con.execute("BEGIN")
    try:
        for t in tables:
            con.execute(f'CREATE OR REPLACE TABLE "{args.live}"."{t}" AS '
                        f'SELECT * FROM "{args.shadow}"."{t}"')
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")  # leave live untouched
        raise                    # -> non-zero exit -> cron step fails -> no heartbeat

    print("--- published atomically; live gold is now the validated build")

    if args.drop_shadow:
        con.execute(f'DROP SCHEMA IF EXISTS "{args.shadow}" CASCADE')
        print(f"--- dropped shadow schema {args.shadow}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
