"""
Throwaway profiling of the TheDogAPI /v1/breeds source data.

Not production code: this exists only to inform schema design for the
ingestion -> dbt -> dashboard pipeline. Fetches the breeds payload, lands
it as raw JSON, and lets DuckDB do the reading/profiling natively.

Usage:
    python exploration/profile_breeds.py

Reads DOG_API_KEY from .env / environment if present. The public endpoint
may work without one; if it 403s, a key is required.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import duckdb
import requests

API_URL = "https://api.thedogapi.com/v1/breeds"
EXPLORATION_DIR = Path(__file__).parent
RAW_JSON = EXPLORATION_DIR / "raw_breeds.json"
SAMPLE_JSON = EXPLORATION_DIR / "sample_breeds.json"
REPORT_MD = EXPLORATION_DIR / "PROFILE_REPORT.md"

MESSY_FIELDS = ["life_span", "weight", "height", "temperament"]
N_EXAMPLES = 5


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def load_api_key() -> str | None:
    """Read DOG_API_KEY from the environment, falling back to a local .env."""
    if key := os.environ.get("DOG_API_KEY"):
        return key
    env_file = EXPLORATION_DIR.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("DOG_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def fetch_breeds() -> list[dict]:
    """Fetch all breeds. The endpoint returns the full list in one response."""
    headers = {}
    if key := load_api_key():
        headers["x-api-key"] = key
        print("Using DOG_API_KEY from environment/.env")
    else:
        print("No DOG_API_KEY found; calling the endpoint unauthenticated")

    resp = requests.get(API_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    breeds = resp.json()
    if not isinstance(breeds, list):
        raise ValueError(f"Expected a JSON array of breeds, got {type(breeds).__name__}")
    print(f"Fetched {len(breeds)} breeds")

    RAW_JSON.write_text(json.dumps(breeds, indent=2))
    return breeds


# --------------------------------------------------------------------------
# field discovery + profiling (DuckDB reads the JSON natively)
# --------------------------------------------------------------------------

def connect(raw_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW breeds AS SELECT * FROM read_json_auto('{raw_path}', maximum_object_size=20000000)"
    )
    return con


def describe(con) -> list[tuple[str, str]]:
    """(column_name, duckdb_type) as inferred from the JSON."""
    return [(r[0], r[1]) for r in con.execute("DESCRIBE breeds").fetchall()]


def profile_field(con, name: str, dtype: str, total: int) -> dict:
    """Null rate, distinct count and example values for one top-level field.

    Nested fields (STRUCT) are cast to JSON text so they can be counted and
    displayed uniformly alongside scalars.
    """
    is_nested = dtype.startswith("STRUCT") or dtype.startswith("MAP")
    expr = f'to_json("{name}")' if is_nested else f'"{name}"'

    # Empty strings are the API's de-facto null for several text fields, so
    # count them as missing rather than as a real value.
    null_pred = f'{expr} IS NULL' + ('' if is_nested else f' OR trim(CAST("{name}" AS VARCHAR)) = \'\'')

    nulls = con.execute(f"SELECT count(*) FROM breeds WHERE {null_pred}").fetchone()[0]
    distinct = con.execute(
        f"SELECT count(DISTINCT {expr}) FROM breeds WHERE NOT ({null_pred})"
    ).fetchone()[0]
    examples = [
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT {expr} FROM breeds WHERE NOT ({null_pred}) LIMIT {N_EXAMPLES}"
        ).fetchall()
    ]

    return {
        "name": name,
        "type": dtype,
        "nulls": nulls,
        "null_rate": (nulls / total * 100) if total else 0.0,
        "distinct": distinct,
        "examples": examples,
    }


def check_primary_key(con, total: int) -> dict:
    nulls = con.execute("SELECT count(*) FROM breeds WHERE id IS NULL").fetchone()[0]
    distinct = con.execute("SELECT count(DISTINCT id) FROM breeds").fetchone()[0]
    return {
        "nulls": nulls,
        "distinct": distinct,
        "total": total,
        "is_pk": nulls == 0 and distinct == total,
    }


# --------------------------------------------------------------------------
# messy-field format analysis
# --------------------------------------------------------------------------

NUM = r"\d+(?:\.\d+)?"
SENTINELS = {"unknown", "n/a", "na", "none", "-", "?", "varies"}


def classify_range_string(value: str) -> str:
    """Bucket a value into a *format variant* label.

    Labels must describe the shape, never the value itself — otherwise every
    distinct measurement becomes its own 'variant' and the counts are useless.
    """
    v = value.strip()
    if not v:
        return "empty string"
    if v.lower() in SENTINELS:
        return f"sentinel string: '{v}'"
    if re.fullmatch(rf"{NUM}\s*-\s*{NUM}", v):
        return "range: 'X-Y'"
    if re.fullmatch(rf"{NUM}\s*-\s*{NUM}\s*years?", v, re.I):
        return "range with unit: 'X-Y years'"
    if re.fullmatch(rf"{NUM}\s*years?", v, re.I):
        return "single value with unit: 'X years'"
    if re.fullmatch(NUM, v):
        return "single value: 'X'"
    # Sex-specific forms, e.g. "Male: 50-70; Female: 40-55" (either side may be
    # a single value, and one sex may be absent entirely).
    part = rf"(?:Male|Female)\s*:\s*{NUM}(?:\s*-\s*{NUM})?"
    if re.fullmatch(rf"{part}(?:\s*;\s*{part})*", v, re.I):
        sexes = re.findall(r"(Male|Female)\s*:", v, re.I)
        both = len({s.lower() for s in sexes}) == 2
        has_range = bool(re.search(rf":\s*{NUM}\s*-\s*{NUM}", v))
        shape = "range" if has_range else "single value"
        return (
            f"sex-specific {shape}: 'Male: … ; Female: …'"
            if both
            else f"sex-specific {shape}, one sex only: '{sexes[0].title()}: …'"
        )
    return f"unrecognised: {v!r}"


def analyse_life_span(breeds: list[dict]) -> dict:
    variants = Counter()
    per_variant_example: dict[str, str] = {}
    for b in breeds:
        raw = b.get("life_span")
        if raw is None:
            variants["null/missing"] += 1
            continue
        label = classify_range_string(str(raw))
        variants[label] += 1
        per_variant_example.setdefault(label, str(raw))
    return {"variants": variants, "examples": per_variant_example}


def analyse_measure(breeds: list[dict], field: str) -> dict:
    """weight/height are expected to be objects with metric/imperial keys."""
    shapes = Counter()
    subkey_variants: dict[str, Counter] = {}
    subkey_examples: dict[str, dict[str, str]] = {}

    for b in breeds:
        raw = b.get(field)
        if raw is None:
            shapes["null/missing"] += 1
            continue
        if not isinstance(raw, dict):
            shapes[f"scalar ({type(raw).__name__})"] += 1
            continue
        shapes["object with keys: " + ", ".join(sorted(raw))] += 1
        for k, v in raw.items():
            label = classify_range_string(str(v))
            subkey_variants.setdefault(k, Counter())[label] += 1
            subkey_examples.setdefault(k, {}).setdefault(label, str(v))

    return {"shapes": shapes, "subkey_variants": subkey_variants, "subkey_examples": subkey_examples}


def analyse_temperament(breeds: list[dict]) -> dict:
    tag_counts = Counter()
    folded_counts = Counter()
    per_breed = []
    missing = 0
    for b in breeds:
        raw = b.get("temperament")
        if raw is None or not str(raw).strip():
            missing += 1
            continue
        tags = [t.strip() for t in str(raw).split(",") if t.strip()]
        per_breed.append(len(tags))
        tag_counts.update(tags)
        folded_counts.update(t.lower() for t in tags)

    # The same tag arrives in more than one casing ("Loyal" vs "loyal"), which
    # inflates the distinct count and would fragment any group-by downstream.
    inconsistent = sorted(
        t for t in folded_counts if len({x for x in tag_counts if x.lower() == t}) > 1
    )

    return {
        "missing": missing,
        "with_tags": len(per_breed),
        "avg_tags": (sum(per_breed) / len(per_breed)) if per_breed else 0.0,
        "min_tags": min(per_breed) if per_breed else 0,
        "max_tags": max(per_breed) if per_breed else 0,
        "distinct_tags": len(tag_counts),
        "distinct_tags_folded": len(folded_counts),
        "inconsistent_casing": inconsistent,
        "top_tags": folded_counts.most_common(10),
    }


def analyse_quality(breeds: list[dict]) -> dict:
    """Cross-field checks that bear directly on schema/grain decisions."""
    name_counts = Counter(b.get("name") for b in breeds)
    dupe_names = {n: c for n, c in name_counts.items() if c > 1}
    dupe_detail = [
        {"id": b["id"], "name": b["name"], "origin": b.get("origin")}
        for b in breeds
        if b.get("name") in dupe_names
    ]

    cc_mismatch = sum(
        1 for b in breeds if b.get("country_code") != b.get("country_codes")
    )

    sentinel_rows = [
        {"id": b["id"], "name": b["name"], "field": f}
        for b in breeds
        for f in ("weight", "height")
        if isinstance(b.get(f), dict)
        and str(b[f].get("metric", "")).strip().lower() in SENTINELS
    ]

    constant_fields = [
        k
        for k in (breeds[0].keys() if breeds else [])
        if len({json.dumps(b.get(k), sort_keys=True) for b in breeds}) == 1
    ]

    return {
        "dupe_names": dupe_names,
        "dupe_detail": dupe_detail,
        "cc_mismatch": cc_mismatch,
        "sentinel_rows": sentinel_rows,
        "constant_fields": constant_fields,
    }


# --------------------------------------------------------------------------
# sample selection
# --------------------------------------------------------------------------

def pick_samples(breeds: list[dict], all_fields: list[str], n: int = 5) -> list[dict]:
    """A handful of representative records, deliberately including the sparsest.

    Sparsity = how many known fields are absent/empty, so the picked set spans
    the richest and the most incomplete records rather than just the first n.
    """
    def sparsity(b: dict) -> int:
        return sum(1 for f in all_fields if b.get(f) in (None, "", {}, []))

    ranked = sorted(breeds, key=sparsity)
    if len(ranked) <= n:
        return ranked

    picked = [ranked[0]]                      # richest record
    picked.append(ranked[-1])                 # sparsest record
    picked.append(ranked[-2])                 # second sparsest
    mid = len(ranked) // 2
    picked.append(ranked[mid])                # typical record
    # one with a temperament, to show the tag format concretely
    for b in ranked:
        if b.get("temperament") and b not in picked:
            picked.append(b)
            break
    return picked[:n]


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

MAX_VARIANT_ROWS = 15


def variant_rows(counter: Counter, examples: dict[str, str]) -> list[str]:
    """Variant table rows, capped — with an explicit note if anything is dropped."""
    rows = []
    for label, count in counter.most_common(MAX_VARIANT_ROWS):
        rows.append(f"| {label} | {count} | `{examples.get(label, '—')}` |")
    hidden = len(counter) - MAX_VARIANT_ROWS
    if hidden > 0:
        rows.append(f"| _… {hidden} further variant(s) not shown_ | | |")
    return rows


def fmt_example(v) -> str:
    s = str(v)
    if len(s) > 90:
        s = s[:87] + "..."
    return f"`{s}`"


def build_report(total, pk, fields, life_span, weight, height, temperament, quality) -> str:
    L = []
    a = L.append

    a("# TheDogAPI `/v1/breeds` — Source Data Profile\n")
    a("Throwaway exploration to inform schema design. Not part of the pipeline.\n")
    a(f"- **Source:** `{API_URL}`")
    a(f"- **Total rows:** {total}")
    a(f"- **Top-level fields:** {len(fields)}\n")

    a("## Primary key candidate: `id`\n")
    a(f"- Nulls: **{pk['nulls']}**")
    a(f"- Distinct values: **{pk['distinct']}** / {pk['total']} rows")
    verdict = (
        "`id` is unique and non-null — **usable as the primary key**."
        if pk["is_pk"]
        else "`id` is **NOT** a safe primary key (see counts above)."
    )
    a(f"- Verdict: {verdict}\n")

    # --- flags -------------------------------------------------------------
    a("## Schema design flags\n")
    a("Things worth deciding on before modelling:\n")

    if quality["dupe_names"]:
        a(f"- **`name` is not unique** — {len(quality['dupe_names'])} name(s) appear on multiple `id`s:")
        for d in quality["dupe_detail"]:
            a(f"  - id `{d['id']}` — {d['name']} (origin: {d['origin']})")
        a("  Looks like a genuine duplicate record rather than two distinct breeds. `id` is still a valid PK, but a natural key on `name` would break, and breed counts will be off by one.")
    else:
        a("- `name` is unique across all rows.")

    if quality["cc_mismatch"] == 0:
        a("- **`country_code` and `country_codes` are identical on every row** — fully redundant; keep one.")
    else:
        a(f"- `country_code` differs from `country_codes` on {quality['cc_mismatch']} row(s).")

    if quality["constant_fields"]:
        a(f"- **Constant / zero-information fields:** {', '.join(f'`{f}`' for f in quality['constant_fields'])} — same value (or always null) on every row; safe to drop.")

    if quality["sentinel_rows"]:
        a(f"- **String sentinels hiding as data** — {len(quality['sentinel_rows'])} measurement(s) use the literal `'unknown'` rather than null:")
        for r in quality["sentinel_rows"]:
            a(f"  - id `{r['id']}` ({r['name']}) — `{r['field']}`")
        a("  These will not show up as nulls; they must be converted during staging or they will silently poison numeric casts.")

    if temperament["inconsistent_casing"]:
        a(f"- **`temperament` tags have inconsistent casing** — {temperament['distinct_tags']} distinct tags collapse to {temperament['distinct_tags_folded']} when lowercased; {len(temperament['inconsistent_casing'])} tag(s) appear in more than one casing (e.g. {', '.join(repr(t) for t in temperament['inconsistent_casing'][:3])}). Normalise before grouping.")

    a("")

    a("## Field summary\n")
    a("| Field | Type | Null rate | Distinct |")
    a("|---|---|---|---|")
    for f in fields:
        a(f"| `{f['name']}` | {f['type']} | {f['null_rate']:.1f}% ({f['nulls']}) | {f['distinct']} |")
    a("")

    a("## Field detail\n")
    for f in fields:
        a(f"### `{f['name']}`\n")
        a(f"- Inferred type: `{f['type']}`")
        a(f"- Null / empty: **{f['null_rate']:.1f}%** ({f['nulls']} of {total})")
        a(f"- Distinct values: **{f['distinct']}**")
        if f["examples"]:
            a("- Examples:")
            for ex in f["examples"]:
                a(f"  - {fmt_example(ex)}")
        else:
            a("- Examples: _none (field is entirely null/empty)_")
        a("")

    a("## Messy-field format variants\n")

    a("### `life_span`\n")
    a("| Format variant | Count | Example |")
    a("|---|---|---|")
    L.extend(variant_rows(life_span["variants"], life_span["examples"]))
    a("")

    for field, data in (("weight", weight), ("height", height)):
        a(f"### `{field}`\n")
        a("Object shapes found:\n")
        a("| Shape | Count |")
        a("|---|---|")
        for shape, count in data["shapes"].most_common():
            a(f"| {shape} | {count} |")
        a("")
        for subkey, variants in data["subkey_variants"].items():
            a(f"Value formats inside `{field}.{subkey}`:\n")
            a("| Format variant | Count | Example |")
            a("|---|---|---|")
            L.extend(variant_rows(variants, data["subkey_examples"][subkey]))
            a("")

    a("### `temperament`\n")
    t = temperament
    a(f"- Breeds with at least one tag: **{t['with_tags']}**")
    a(f"- Breeds with no temperament: **{t['missing']}**")
    a(f"- Tags per breed: avg **{t['avg_tags']:.1f}**, min **{t['min_tags']}**, max **{t['max_tags']}**")
    a(f"- Distinct tags overall: **{t['distinct_tags']}** (**{t['distinct_tags_folded']}** once lowercased)")
    a("- Most common tags (case-folded):")
    for tag, count in t["top_tags"]:
        a(f"  - `{tag}` ({count})")
    a("")
    a("Format: a single comma-separated string, **not** a JSON array — needs splitting into a bridge table if tags are to be queried individually.\n")

    a("## Files\n")
    a(f"- `{SAMPLE_JSON.name}` — representative records, including sparse ones")
    a(f"- `{RAW_JSON.name}` — full raw payload as fetched")

    return "\n".join(L) + "\n"


def main() -> None:
    breeds = fetch_breeds()
    total = len(breeds)

    con = connect(RAW_JSON)
    cols = describe(con)
    print(f"DuckDB inferred {len(cols)} top-level fields")

    fields = [profile_field(con, name, dtype, total) for name, dtype in cols]
    pk = check_primary_key(con, total)

    life_span = analyse_life_span(breeds)
    weight = analyse_measure(breeds, "weight")
    height = analyse_measure(breeds, "height")
    temperament = analyse_temperament(breeds)
    quality = analyse_quality(breeds)

    samples = pick_samples(breeds, [name for name, _ in cols])
    SAMPLE_JSON.write_text(json.dumps(samples, indent=2))
    print(f"Wrote {len(samples)} sample records -> {SAMPLE_JSON}")

    REPORT_MD.write_text(
        build_report(total, pk, fields, life_span, weight, height, temperament, quality)
    )
    print(f"Wrote profile report -> {REPORT_MD}")


if __name__ == "__main__":
    main()
