"""
M1 — Ingestion: TheDogAPI /v1/breeds -> DuckDB raw/bronze layer.

The write path of the pipeline. Fetches the breeds payload with retry+backoff,
validates that the response is complete, and lands it *untouched* into
`raw.breeds`, partitioned by `run_date`. dbt takes over from there.

Three properties this job is built around:

1. **The payload is not interpreted.** Each breed lands as verbatim JSON. No
   parsing, no casting, no cleaning — that is dbt's job in staging. If the
   parser turns out to be wrong, the raw layer is still the truth and we can
   rebuild without re-fetching.
2. **Idempotent per run_date, and stateless across runs.** Re-running replaces
   that day's partition rather than appending to it, so a re-run yields the same
   628 rows with no duplicates. The job keeps **no state between runs** — the
   API is the source of truth and each run rebuilds from it, so CI's fresh,
   empty VM is a supported starting point rather than a problem. In CI exactly
   one partition ever exists; locally the file persists and partitions
   accumulate as a side effect, which is why silver still filters to the latest
   run_date. See DECISIONS.md §1.
3. **A partial fetch never overwrites last-good data.** Everything is fetched
   and validated in memory first; the warehouse is only touched once the payload
   has passed. The delete+insert is a single transaction, so the partition is
   never left half-written.

Usage:
    python ingestion/ingest.py                 # fetch + land into dogs.duckdb
    python ingestion/ingest.py --db /tmp/x.duckdb --run-date 2026-07-15

Requires DOG_API_KEY in the environment or a gitignored .env at the project
root. /v1/breeds returns 403 without it. The key is never logged.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import requests
from dotenv import load_dotenv
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

API_URL = "https://api.thedogapi.com/v1/breeds"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "dogs.duckdb"

REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 5

# HTTP statuses worth retrying: rate limiting and the transient 5xx family.
# Everything else (401/403/404) is a real problem that a retry cannot fix.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# The breed count observed during M0 profiling. Used as the completeness
# reference only on a first-ever run, when there is no prior partition to
# compare against.
BASELINE_BREED_COUNT = 628

# A run must return at least this fraction of the reference count to be
# promoted. Deliberately a tolerance, not equality: the API legitimately
# gaining or losing a breed is real data, not an error, and must not fail the
# job. A grossly short pull (a truncated response, a partial outage) is what
# this catches. Drift within the band is surfaced by a *warn*-severity dbt
# test downstream, not by failing the pipeline here.
MIN_COMPLETENESS_RATIO = 0.9

log = logging.getLogger("ingest")


class TransientFetchError(Exception):
    """A failure worth retrying (timeout, connection reset, 429/5xx)."""


class IncompletePayloadError(Exception):
    """The response arrived but is not trustworthy enough to promote."""


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def load_api_key() -> str:
    """Read DOG_API_KEY from the environment, falling back to a local .env.

    In GitHub Actions the key arrives as an env var from Actions secrets; there
    is no .env there. Fail loudly rather than silently calling unauthenticated,
    which would 403 and look like an API outage.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("DOG_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DOG_API_KEY is not set. /v1/breeds returns 403 without it. "
            "Set it in .env locally, or as a GitHub Actions secret in CI."
        )
    return key


@retry(
    retry=retry_if_exception_type((TransientFetchError, requests.Timeout, requests.ConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_breeds(api_key: str) -> list[dict]:
    """Fetch the full breeds list, retrying transient failures with backoff.

    The endpoint returns all breeds in a single response, so there is no
    pagination to walk. (If it ever starts paginating, the completeness check
    below is what would catch the truncation.)

    Only the retryable statuses raise TransientFetchError; a 403 raises
    immediately via raise_for_status, because retrying a bad key five times
    just delays the real error message.
    """
    response = requests.get(
        API_URL,
        headers={"x-api-key": api_key},  # never logged
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code in RETRYABLE_STATUS:
        raise TransientFetchError(f"HTTP {response.status_code} from {API_URL}")
    response.raise_for_status()

    breeds = response.json()
    log.info("Fetched %d breeds", len(breeds) if isinstance(breeds, list) else -1)
    return breeds


# --------------------------------------------------------------------------
# validate — everything here runs BEFORE the warehouse is touched
# --------------------------------------------------------------------------

def reference_count(con: duckdb.DuckDBPyConnection, run_date: date) -> tuple[int, str]:
    """The breed count this run is judged complete against.

    Prefers the most recent *earlier* partition — the last known-good run — and
    falls back to the M0 profiling baseline when there isn't one. Today's own
    partition is excluded on purpose: on a re-run it would otherwise compare the
    fetch against itself and validate nothing.

    Because the pipeline is stateless (DECISIONS.md §1), CI always takes the
    baseline branch — its warehouse starts empty every run. The prior-partition
    branch is what a local, persisted run gets. The trade is stated in §1: the
    floor is a fixed 628 in CI rather than one that tracks reality.
    """
    prior = con.execute(
        """
        SELECT run_date, count(*)
        FROM raw.breeds
        WHERE run_date < ?
        GROUP BY run_date
        ORDER BY run_date DESC
        LIMIT 1
        """,
        [run_date],
    ).fetchone()

    if prior:
        return prior[1], f"last-good partition {prior[0]}"
    return BASELINE_BREED_COUNT, "M0 profiling baseline (no prior partition)"


def validate(breeds: object, reference: int, source: str) -> list[dict]:
    """Reject a payload that must not be promoted over last-good data.

    Checks structure (is this even a breeds list?), the primary key (`id`
    present, non-null, unique — the PK claim SPEC.md rests on), and
    completeness against the reference count.
    """
    if not isinstance(breeds, list):
        raise IncompletePayloadError(
            f"Expected a JSON array of breeds, got {type(breeds).__name__}"
        )

    non_dicts = sum(1 for b in breeds if not isinstance(b, dict))
    if non_dicts:
        raise IncompletePayloadError(f"{non_dicts} element(s) are not JSON objects")

    missing_id = sum(1 for b in breeds if b.get("id") is None)
    if missing_id:
        raise IncompletePayloadError(f"{missing_id} breed(s) have a null/absent id")

    ids = [b["id"] for b in breeds]
    if len(set(ids)) != len(ids):
        raise IncompletePayloadError(
            f"id is not unique in the payload: {len(ids)} rows, {len(set(ids))} distinct"
        )

    floor = int(reference * MIN_COMPLETENESS_RATIO)
    if len(breeds) < floor:
        raise IncompletePayloadError(
            f"Payload looks incomplete: {len(breeds)} breeds, expected at least "
            f"{floor} ({MIN_COMPLETENESS_RATIO:.0%} of {reference} from {source}). "
            "Refusing to promote it."
        )

    log.info(
        "Payload validated: %d breeds, unique ids, >= %d required (%s)",
        len(breeds), floor, source,
    )
    return breeds


# --------------------------------------------------------------------------
# land
# --------------------------------------------------------------------------

def ensure_raw_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the raw layer if absent.

    `payload` holds the breed exactly as the API returned it. `breed_id` is
    lifted out alongside it — not a transformation, just the partition's key,
    so idempotency and duplicate checks are expressible in SQL without parsing
    JSON. Everything else stays inside the payload for dbt to unpack.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.breeds (
            breed_id  INTEGER   NOT NULL,
            payload   JSON      NOT NULL,
            run_date  DATE      NOT NULL,
            loaded_at TIMESTAMP NOT NULL
        )
        """
    )


def land(
    con: duckdb.DuckDBPyConnection,
    breeds: list[dict],
    run_date: date,
    loaded_at: datetime,
) -> int:
    """Replace this run_date's partition with the validated payload, atomically.

    DELETE-then-INSERT inside one transaction is what makes the job idempotent:
    a re-run on the same day rewrites its own partition instead of appending a
    second copy. Wrapping both in a transaction means a crash mid-insert rolls
    back to the previous partition rather than leaving a half-written day.
    """
    rows = [
        (int(b["id"]), json.dumps(b, separators=(",", ":")), run_date, loaded_at)
        for b in breeds
    ]

    con.execute("BEGIN TRANSACTION")
    try:
        deleted = con.execute(
            "DELETE FROM raw.breeds WHERE run_date = ?", [run_date]
        ).fetchone()[0]
        con.executemany(
            "INSERT INTO raw.breeds VALUES (?, CAST(? AS JSON), ?, ?)", rows
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    if deleted:
        log.info("Replaced existing partition %s (%d rows deleted)", run_date, deleted)
    return len(rows)


def verify_partition(con: duckdb.DuckDBPyConnection, run_date: date, expected: int) -> None:
    """Read back what we wrote: the row count and the no-duplicates invariant."""
    count, distinct = con.execute(
        "SELECT count(*), count(DISTINCT breed_id) FROM raw.breeds WHERE run_date = ?",
        [run_date],
    ).fetchone()

    if count != expected or distinct != expected:
        raise RuntimeError(
            f"Post-write check failed for {run_date}: wrote {expected}, "
            f"read back {count} rows / {distinct} distinct breed_ids"
        )
    log.info("Verified partition %s: %d rows, %d distinct breed_ids", run_date, count, distinct)


def report_history(con: duckdb.DuckDBPyConnection) -> None:
    """Print every partition — the accumulating history, at a glance."""
    partitions = con.execute(
        """
        SELECT run_date, count(*) AS breeds, max(loaded_at) AS loaded_at
        FROM raw.breeds
        GROUP BY run_date
        ORDER BY run_date
        """
    ).fetchall()

    log.info("raw.breeds now holds %d partition(s):", len(partitions))
    for run_date, breeds, loaded_at in partitions:
        log.info("  %s  %4d breeds  (loaded_at %s)", run_date, breeds, loaded_at)


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"DuckDB file (default: {DEFAULT_DB})"
    )
    parser.add_argument(
        "--run-date",
        type=date.fromisoformat,
        default=None,
        help="Partition to write (default: today, UTC). Mainly for testing/backfill.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    args = parse_args(argv)

    now = datetime.now(timezone.utc)
    run_date = args.run_date or now.date()

    try:
        api_key = load_api_key()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    con = duckdb.connect(str(args.db))
    try:
        ensure_raw_schema(con)
        reference, source = reference_count(con, run_date)

        try:
            breeds = fetch_breeds(api_key)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            hint = " — check DOG_API_KEY" if status in (401, 403) else ""
            log.error("Fetch failed with HTTP %s%s. Last-good data untouched.", status, hint)
            return 1
        except Exception as exc:
            log.error(
                "Fetch failed after %d attempts: %s. Last-good data untouched.",
                MAX_ATTEMPTS, exc,
            )
            return 1

        try:
            breeds = validate(breeds, reference, source)
        except IncompletePayloadError as exc:
            log.error("%s", exc)
            return 1

        written = land(con, breeds, run_date, now.replace(tzinfo=None))
        verify_partition(con, run_date, written)
        report_history(con)
        log.info("Ingestion complete: %d breeds landed into %s (run_date=%s)",
                 written, args.db, run_date)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
