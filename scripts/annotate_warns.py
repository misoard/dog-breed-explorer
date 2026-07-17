"""
Make dbt's `warn` severity visible. The other half of the warn/error decision.

THE PROBLEM THIS EXISTS FOR: dbt prints WARN to stdout and exits **0**. So a
warn-severity test that fires produces a GREEN build and a line of text buried in
a collapsed log that nobody expands. Five tests in this project are `severity:
warn` on purpose (DECISIONS.md §3: invariants error, anomalies warn) — and until
something surfaces them, that classification is theatre: tests carefully sorted
into a bucket no human ever reads.

So this reads `dbt/target/run_results.json` after the build and emits:

  1. GitHub `::warning::` workflow commands  -> annotations on the PR / run page
  2. a markdown table to `$GITHUB_STEP_SUMMARY` -> the run's summary page

...and **exits 0 when it finds warns**, on purpose. Failing the build here would
re-implement `--warn-error` and destroy the exact distinction it exists to serve.
A warn is for a human to judge ("real regression or legitimate drift?"), not for
a robot to block on.

It is a plain script, not inline jq in the YAML, for one reason: a bug in inline
jq produces NO annotation, which is indistinguishable from NO WARNINGS. The thing
whose whole job is making problems visible would fail invisibly. This runs
locally against a real (or synthetic) run_results.json, so the mechanism can be
proven before CI ever depends on it.

Usage:
    python scripts/annotate_warns.py                     # reads dbt/target/run_results.json
    python scripts/annotate_warns.py --results PATH      # ...or any run_results.json

Exit 0 = the run was read and reported (warns included). Exit 1 = the results
could not be read, i.e. this guard could not do its job — which must never pass
silently.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS = ROOT / "dbt" / "target" / "run_results.json"

# dbt statuses, split by what they mean for a human reading the run.
#   pass/success  — the model built / the test held
#   warn          — a severity:warn test fired: THE POINT OF THIS SCRIPT
#   fail/error    — the build is already red; we list them for context only
#   skipped       — blocked by an upstream failure
WARN = "warn"
BAD = ("fail", "error", "runtime error")


def load_results(path: Path) -> dict:
    """Read run_results.json, or explain why we can't and let the caller exit 1.

    A missing file means dbt never got far enough to write one — the build has
    already failed for a louder reason. We still refuse to report success,
    because "I found no warnings" and "I could not look" must not look the same.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — did `dbt build` run, and from the dbt/ directory?"
        )
    with path.open() as fh:
        return json.load(fh)


def test_name(unique_id: str) -> str:
    """`test.dog_breed_explorer.assert_metric_shape_known` -> `assert_metric_shape_known`.

    dbt's generic tests carry a hash suffix (`not_null_x_y.26d893dcca`); the raw
    unique_id is the honest identifier but it's unreadable in an annotation title,
    so the full id goes in the body and the short name in the title.
    """
    name = unique_id.split(".")[-1]
    parts = unique_id.split(".")
    if len(parts) > 2 and len(name) == 10 and all(c in "0123456789abcdef" for c in name):
        name = parts[-2]  # drop dbt's hash suffix
    return name


def summarise(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def emit_annotations(warns: list[dict]) -> None:
    """GitHub workflow commands. One `::warning::` per fired test = one annotation."""
    for r in warns:
        name = test_name(r["unique_id"])
        failures = r.get("failures")
        detail = f"{failures} row(s) returned" if failures is not None else "fired"
        message = (r.get("message") or "").replace("\n", " ").strip()
        body = f"{r['unique_id']} — {detail}"
        if message:
            body += f". dbt says: {message}"
        # ::warning title=X::body  — the title shows in the annotation header.
        print(f"::warning title=dbt warn: {name}::{body}")


def build_summary(counts: dict[str, int], warns: list[dict], meta: dict, args_) -> str:
    total_tests = counts.get("pass", 0) + counts.get(WARN, 0) + counts.get("fail", 0)
    lines = [
        "## dbt build",
        "",
        f"- **target**: `{args_.get('target', '?')}`",
        f"- **dbt**: `{meta.get('dbt_version', '?')}`",
        "- **results**: "
        + " · ".join(f"{status} **{n}**" for status, n in sorted(counts.items())),
        "",
    ]
    if warns:
        lines += [
            f"### ⚠️ {len(warns)} warn-severity test(s) fired",
            "",
            "These do **not** fail the build by design — they flag data that changed"
            " without breaking an invariant, for a human to judge"
            " (see DECISIONS.md §3). Ignoring one is a decision; not seeing it isn't.",
            "",
            "| test | rows | dbt message |",
            "|---|---|---|",
        ]
        for r in warns:
            failures = r.get("failures")
            msg = (r.get("message") or "").replace("\n", " ").replace("|", "\\|").strip()
            lines.append(f"| `{test_name(r['unique_id'])}` | {failures if failures is not None else '—'} | {msg or '—'} |")
    else:
        lines.append("### ✅ No warn-severity tests fired")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"dbt run_results.json (default: {DEFAULT_RESULTS.relative_to(ROOT)})",
    )
    args = parser.parse_args(argv)

    try:
        data = load_results(args.results)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        # Loud, and non-zero: a guard that cannot run must not report "all clear".
        print(f"::error title=warn annotation failed::{exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    results = data.get("results", [])
    counts = summarise(results)
    warns = [r for r in results if r["status"] == WARN]
    bad = [r for r in results if r["status"] in BAD]

    emit_annotations(warns)

    summary = build_summary(counts, warns, data.get("metadata", {}), data.get("args", {}))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(summary + "\n")

    # Always readable locally too — the whole point is that this is testable
    # outside Actions.
    print(summary)

    if bad:
        print(f"note: {len(bad)} test(s) failed outright; the build is red for that reason.")

    return 0  # warns NEVER fail the build — that is the entire design.


if __name__ == "__main__":
    sys.exit(main())
