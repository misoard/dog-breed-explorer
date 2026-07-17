"""
Deterministic end-of-milestone audit. The mechanical half of /milestone.

Answers only questions with a checkable answer, so they cannot be answered by
optimism:

  1. Is the build actually green, and how many tests ran?
  2. Do the numbers in the docs match the numbers in the warehouse?
  3. Is every test / model / seed on disk documented in SPEC + ARCHITECTURE_PLAN?
  4. Which milestone checklist items are still unticked?

It NEVER edits anything. It reports. Judgment — "is this inconsistency a stale
number or a decision that changed?" — is deliberately left to the human and the
agent, because that distinction is exactly where a script would do damage.

Usage:
    .venv/bin/python scripts/audit.py            # audit against dogs_dev.duckdb
    .venv/bin/python scripts/audit.py --db X     # ...or another warehouse

Exit code 0 = everything checkable is consistent. Non-zero = look at the report.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["SPEC.md", "DECISIONS.md", "ARCHITECTURE_PLAN.md", "CLAUDE.md"]

# The numbers that appear in prose and MUST match the warehouse. Each is (label, SQL).
#
# READ THIS BEFORE TRUSTING A GREEN RUN: this list is the tool's ENTIRE field of view. A
# figure not listed here is a figure nothing checks — and a guard that reports "ok" about the
# nine numbers it watches is actively misleading about the ninety it doesn't. That is the
# same failure as a dropped test (looks like coverage, isn't) and a permanent warn (looks
# like a signal, isn't). So: `report_coverage()` below prints what is NOT watched, every run,
# and the verdict never says "consistent" unqualified.
#
# Add a row here the moment a doc starts quoting a new figure.
LIVE_NUMBERS = [
    # counts
    ("raw.breeds rows",        "select count(*) from raw.breeds"),
    ("stg_breeds rows",        "select count(*) from main_staging.stg_breeds"),
    ("breeds with weight",     "select count(weight_min_kg) from main_staging.stg_breeds"),
    ("breeds with life span",  "select count(life_span_min_years) from main_staging.stg_breeds"),
    ("bridge rows",            "select count(*) from main_staging.stg_breed_temperaments"),
    ("distinct tags",          "select count(distinct temperament) from main_staging.stg_breed_temperaments"),
    ("breeds with a tag",      "select count(distinct breed_id) from main_staging.stg_breed_temperaments"),
    ("dim_breeds rows",        "select count(*) from main_marts.dim_breeds"),
    ("breeds plotted (scatter)", "select breeds_plotted_scatter from main_marts.mart_data_coverage"),
    ("breeds excluded (scatter)", "select breeds_excluded_scatter from main_marts.mart_data_coverage"),
    ("breeds with temperament", "select breeds_with_temperament from main_marts.mart_data_coverage"),

    # the size_class distribution — quoted as a frozen expectation in SPEC
    ("size_class toy",    "select breed_count from main_marts.mart_size_class_summary where size_class='toy'"),
    ("size_class small",  "select breed_count from main_marts.mart_size_class_summary where size_class='small'"),
    ("size_class medium", "select breed_count from main_marts.mart_size_class_summary where size_class='medium'"),
    ("size_class large",  "select breed_count from main_marts.mart_size_class_summary where size_class='large'"),
    ("size_class giant",  "select breed_count from main_marts.mart_size_class_summary where size_class='giant'"),

    # CORRELATIONS — the evidence for "size = weight, not height". Quoted in 4 files and
    # watched by nothing until now: exactly the blind spot this list existed to have.
    ("corr weight~life",   "select correlation from main_marts.mart_metric_correlation where metric_a='weight_mid_kg' and metric_b='life_span_mid_years'"),
    ("corr height~life",   "select correlation from main_marts.mart_metric_correlation where metric_a='height_mid_cm' and metric_b='life_span_mid_years'"),
    ("corr height~weight", "select correlation from main_marts.mart_metric_correlation where metric_a='height_mid_cm' and metric_b='weight_mid_kg'"),
    ("n_breeds weight~life",   "select n_breeds from main_marts.mart_metric_correlation where metric_a='weight_mid_kg' and metric_b='life_span_mid_years'"),
    ("n_breeds height~weight", "select n_breeds from main_marts.mart_metric_correlation where metric_a='height_mid_cm' and metric_b='weight_mid_kg'"),

    # the life-span story — mean AND the sigma that keeps it honest
    ("mean life toy",   "select mean_life_span_years from main_marts.mart_size_class_summary where size_class='toy'"),
    ("mean life giant", "select mean_life_span_years from main_marts.mart_size_class_summary where size_class='giant'"),
    ("stddev life small", "select stddev_life_span_years from main_marts.mart_size_class_summary where size_class='small'"),
    ("stddev life giant", "select stddev_life_span_years from main_marts.mart_size_class_summary where size_class='giant'"),
]

# What this tool CANNOT check, stated so a green run is never read as "the docs are right".
# Every line here is a standing invitation to make it checkable.
BLIND_SPOTS = [
    "prose claims with no number ('the spread grows with size')",
    "numbers in DAY_REPORT (narrative — deliberately a snapshot of the day, not live)",
    "figures from the M0.5 exploration that no model computes (the cut isometry fit: k=2.07, R2=0.864)",
    "whether a number is quoted in the RIGHT PLACE, or means what the sentence says it means",
]

FAIL = []


def report(section: str) -> None:
    print(f"\n{'=' * 72}\n{section}\n{'=' * 72}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def bad(msg: str) -> None:
    print(f"  FLAG  {msg}")
    FAIL.append(msg)


# ---------------------------------------------------------------------------
# 1. the build
# ---------------------------------------------------------------------------

def check_build() -> None:
    report("1. BUILD — is it actually green?")
    proc = subprocess.run(
        ["../.venv/bin/dbt", "build", "--target", "dev"],
        cwd=ROOT / "dbt", capture_output=True, text=True,
    )
    out = proc.stdout
    found = re.search(r"Found (\d+) models?, (\d+) data tests?", out)
    done = re.search(r"Done\. PASS=(\d+) WARN=(\d+) ERROR=(\d+) SKIP=(\d+)", out)

    if proc.returncode != 0:
        bad(f"dbt build exited {proc.returncode} — the milestone is not done")
    if found:
        ok(f"{found.group(1)} models, {found.group(2)} data tests registered")
        print(f"        ^ a test whose ref() breaks is DROPPED silently — watch this number")
    if done:
        p, w, e, s = done.groups()
        (ok if e == "0" else bad)(f"PASS={p} WARN={w} ERROR={e} SKIP={s}")
        if w != "0":
            print(f"        note: {w} warning(s) — expected 0 unless a guard is firing")
    else:
        bad("could not parse a Done. line from dbt output")


# ---------------------------------------------------------------------------
# 2. numbers in prose vs numbers in the warehouse
# ---------------------------------------------------------------------------

def check_numbers(db: str) -> int:
    report("2. NUMBERS — do the docs agree with the warehouse?")
    matched = 0
    con = duckdb.connect(db, read_only=True)
    text = {f: (ROOT / f).read_text() for f in DOCS}

    for label, sql in LIVE_NUMBERS:
        try:
            val = con.execute(sql).fetchone()[0]
        except Exception as exc:
            bad(f"{label}: cannot read ({str(exc)[:40]}) — has the model been built?")
            continue

        # Where does this number appear in prose? Match both 3538 and 3,538.
        forms = {str(val)}
        if isinstance(val, int):
            forms.add(f"{val:,}")
        if isinstance(val, float):
            # -0.67 is quoted as "−0.670" (trailing zero) and with a unicode minus
            for d in (2, 3):
                forms.add(f"{val:.{d}f}")
            forms |= {f.replace("-", "\u2212") for f in list(forms)}
        pattern = re.compile("|".join(rf"(?<![\d,.]){re.escape(f)}(?![\d,.])" for f in forms))
        cited = [f for f, t in text.items() if pattern.search(t)]
        if cited:
            matched += 1
            ok(f"{label:<24} = {str(val):<8} cited in {', '.join(x.replace('.md','') for x in cited)}")
        else:
            print(f"  ?     {label:<24} = {str(val):<8} not quoted in any doc (fine if it's not a claim)")
    con.close()
    return matched


# ---------------------------------------------------------------------------
# 3. is everything on disk documented?
# ---------------------------------------------------------------------------

def check_documented() -> None:
    report("3. COVERAGE — is every artifact on disk documented?")
    spec = (ROOT / "SPEC.md").read_text()
    plan = (ROOT / "ARCHITECTURE_PLAN.md").read_text()

    for kind, paths in [
        ("test",  sorted((ROOT / "dbt/tests").glob("*.sql"))),
        ("model", sorted((ROOT / "dbt/models").rglob("*.sql"))),
        ("seed",  sorted((ROOT / "dbt/seeds").glob("*.csv"))),
    ]:
        for p in paths:
            name = p.stem
            in_spec, in_plan = name in spec, name in plan
            if in_spec and in_plan:
                ok(f"{kind:<5} {name}")
            else:
                missing = ", ".join(d for d, hit in [("SPEC", in_spec), ("PLAN", in_plan)] if not hit)
                bad(f"{kind:<5} {name} — built but undocumented in: {missing}")


def check_promised_tests() -> None:
    """The OTHER direction: a test promised in the docs but never built.

    check_documented() walks from disk outward and can only ever find things that EXIST.
    A test that was specified and quietly never written is invisible to it -- which is
    exactly where assert_lifespan_plausible hid for two milestones: DECISIONS.md §3 said
    "range checks on weight/life span", SPEC carried only the weight half, and nothing
    reconciled the two. A promise nobody checks is a promise nobody keeps.
    """
    report("4. PROMISES — is every test named in the docs actually built?")
    on_disk = {p.stem for p in (ROOT / "dbt/tests").glob("*.sql")}

    # generic tests live in YAML, not as files — collect them so they don't read as missing
    yaml_text = "\n".join(
        p.read_text() for p in (ROOT / "dbt/models").rglob("*.yml")
    ) + "\n".join(p.read_text() for p in (ROOT / "dbt/seeds").glob("*.yml"))

    docs = {d: (ROOT / d).read_text() for d in
            ("SPEC.md", "DECISIONS.md", "ARCHITECTURE_PLAN.md", "CLAUDE.md")}
    named = set()
    for text in docs.values():
        named |= set(re.findall(r"assert_[a-z0-9_]+", text))

    plan = docs["ARCHITECTURE_PLAN.md"]
    pending, superseded, missing = [], [], []

    for name in sorted(named):
        if name in on_disk or name in yaml_text:
            ok(name if name in on_disk else f"{name} (generic, in YAML)")
            continue
        # A name mentioned only near "supersedes / replaces / cut / retired" is not a promise
        # — it's a tombstone. Check EVERY occurrence: if even one sits in live prose, it's a
        # promise. (First version only matched "supersedes X" and cried wolf over the
        # deliberate write-up of a test we removed on purpose.)
        blob = "\n".join(docs.values())
        occurrences = [m.start() for m in re.finditer(re.escape(name), blob)]
        tomb = re.compile(r"supersed|replac|\bcut\b|retired|removed|tombstone", re.I)
        if occurrences and all(tomb.search(blob[max(0, i - 260): i + 260]) for i in occurrences):
            superseded.append(name)
        # Named against a future milestone in the plan, e.g. "[M4]" on the same line.
        elif re.search(rf"{name}.*\[M[4-9]\]|\(M[4-9]\).*{name}|{name}.*\(M[4-9]\)", plan):
            pending.append(name)
        else:
            missing.append(name)

    for n in superseded:
        print(f"  --    {n} — superseded, referenced only as a tombstone. Not a promise.")
    for n in pending:
        print(f"  todo  {n} — promised for a LATER milestone. Expected absent for now.")
    for n in missing:
        bad(f"{n} — PROMISED with no milestone tag, and NOT built. This is how "
            f"assert_lifespan_plausible hid for two milestones.")


def report_coverage(watched: int, matched: int) -> None:
    """Never let a green run imply coverage it doesn't have."""
    report("5. BLIND SPOTS — what this tool does NOT check")
    print(f"  This tool watches {watched} figures. It found {matched} of them quoted in the docs.")
    print("  It does NOT check:")
    for b in BLIND_SPOTS:
        print(f"    - {b}")
    print("\n  A green verdict below means ONLY: 'the figures I watch agree with the warehouse'.")
    print("  It is NOT a statement that the docs are correct. Add to LIVE_NUMBERS when a doc")
    print("  starts quoting a new figure — an unlisted number is a number nothing checks.")


# ---------------------------------------------------------------------------
# 4. the milestone checklist
# ---------------------------------------------------------------------------

def check_checklist(milestone: str | None) -> None:
    report(f"6. CHECKLIST — unticked items{f' in {milestone}' if milestone else ''}")
    plan = (ROOT / "ARCHITECTURE_PLAN.md").read_text().splitlines()

    current, shown = None, 0
    for line in plan:
        m = re.match(r"\*\*(M\d[\d.]*) —", line)
        if m:
            current = m.group(1)
        if milestone and current != milestone:
            continue
        if re.match(r"- \[ \]", line.strip()):
            print(f"  TODO  [{current}] {line.strip()[6:90]}")
            shown += 1
    if shown == 0:
        ok("no unticked items")
    else:
        FAIL.append(f"{shown} unticked checklist item(s)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--db", default=str(ROOT / "dogs_dev.duckdb"))
    ap.add_argument("--milestone", help="e.g. M3 — restrict the checklist scan")
    args = ap.parse_args()

    check_build()
    matched = check_numbers(args.db)
    check_documented()
    check_promised_tests()
    check_checklist(args.milestone)
    report_coverage(len(LIVE_NUMBERS), matched)

    report("VERDICT")
    if FAIL:
        print(f"  {len(FAIL)} thing(s) need a human:\n")
        for f in FAIL:
            print(f"    - {f}")
        print("\n  NOT ready to ship.")
        return 1
    print(f"  The {len(LIVE_NUMBERS)} figures I watch agree with the warehouse, every artifact on")
    print("  disk is documented, every promised test is built, and no box is unticked.")
    print("  That is NOT 'the docs are correct' — see BLIND SPOTS. Ready for the judgment pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
