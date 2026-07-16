# TheDogAPI `/v1/breeds` — Source Data Profile

Throwaway exploration to inform schema design. Not part of the pipeline.

- **Source:** `https://api.thedogapi.com/v1/breeds`
- **Total rows:** 628
- **Top-level fields:** 17

## Primary key candidate: `id`

- Nulls: **0**
- Distinct values: **628** / 628 rows
- Verdict: `id` is unique and non-null — **usable as the primary key**.

## Schema design flags

Things worth deciding on before modelling:

- **`name` is not unique** — 1 name(s) appear on multiple `id`s:
  - id `269` — Caucasian Shepherd Dog (origin: Caucasus Mountains)
  - id `70` — Caucasian Shepherd Dog (origin: Caucasus Mountains)
  Looks like a genuine duplicate record rather than two distinct breeds. `id` is still a valid PK, but a natural key on `name` would break, and breed counts will be off by one.
- **`country_code` and `country_codes` are identical on every row** — fully redundant; keep one.
- **Constant / zero-information fields:** `species_id`, `bred_for`, `perfect_for` — same value (or always null) on every row; safe to drop.
- **String sentinels hiding as data** — 4 measurement(s) use the literal `'unknown'` rather than null:
  - id `518` (Langqing) — `weight`
  - id `518` (Langqing) — `height`
  - id `536` (Mongrel) — `weight`
  - id `536` (Mongrel) — `height`
  These will not show up as nulls; they must be converted during staging or they will silently poison numeric casts.
- **`temperament` tags have inconsistent casing** — 66 distinct tags collapse to 46 when lowercased; 20 tag(s) appear in more than one casing (e.g. 'affectionate', 'alert', 'calm'). Normalise before grouping.

## Field summary

| Field | Type | Null rate | Distinct |
|---|---|---|---|
| `id` | VARCHAR | 0.0% (0) | 628 |
| `name` | VARCHAR | 0.0% (0) | 627 |
| `species_id` | VARCHAR | 0.0% (0) | 1 |
| `life_span` | VARCHAR | 6.4% (40) | 34 |
| `temperament` | VARCHAR | 0.0% (0) | 621 |
| `origin` | VARCHAR | 0.0% (0) | 315 |
| `country_codes` | VARCHAR | 0.0% (0) | 81 |
| `country_code` | VARCHAR | 0.0% (0) | 81 |
| `description` | VARCHAR | 0.0% (0) | 628 |
| `bred_for` | JSON | 100.0% (628) | 0 |
| `perfect_for` | JSON | 100.0% (628) | 0 |
| `breed_group` | VARCHAR | 0.0% (0) | 26 |
| `history` | VARCHAR | 0.0% (0) | 628 |
| `reference_image_id` | VARCHAR | 14.3% (90) | 538 |
| `weight` | STRUCT(imperial VARCHAR, metric VARCHAR) | 0.0% (0) | 530 |
| `height` | STRUCT(imperial VARCHAR, metric VARCHAR) | 0.0% (0) | 480 |
| `image` | STRUCT(id VARCHAR, url VARCHAR, width BIGINT, height BIGINT) | 14.3% (90) | 538 |

## Field detail

### `id`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **628**
- Examples:
  - `348`
  - `350`
  - `19`
  - `361`
  - `362`

### `name`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **627**
- Examples:
  - `Afghan Hound`
  - `American English Coonhound`
  - `American Pit Bull Terrier`
  - `Appenzeller Sennenhund`
  - `Australian Stumpy Tail Cattle Dog`

### `species_id`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **1**
- Examples:
  - `2`

### `life_span`

- Inferred type: `VARCHAR`
- Null / empty: **6.4%** (40 of 628)
- Distinct values: **34**
- Examples:
  - `12-15`
  - `11-14`
  - `8-12`
  - `9-12`
  - `10-16`

### `temperament`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **621**
- Examples:
  - `Intelligent, energetic, courageous, loyal, friendly, alert`
  - `Independent, protective, calm, alert, loyal, intelligent`
  - `Protective, loyal, independent, calm, alert, courageous, intelligent`
  - `Affectionate, friendly, loyal, playful, intelligent, energetic, outgoing`
  - `Confident, loyal, protective, energetic, affectionate, courageous`

### `origin`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **315**
- Examples:
  - `Afghanistan`
  - `Western Turkey`
  - `Argentina`
  - `Armenian Highlands`
  - `Norway`

### `country_codes`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **81**
- Examples:
  - `MA`
  - `TR`
  - `GR`
  - `FR`
  - `PT`

### `country_code`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **81**
- Examples:
  - `AU`
  - `CD`
  - `MX`
  - `IS`
  - `PE`

### `description`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **628**
- Examples:
  - `The largest of all terrier breeds, the Airedale is a large, athletic dog with a distinc...`
  - `Medium-sized, muscular terrier with athletic build and short coat, known for its streng...`
  - `A slender, medium-sized Spanish working terrier with a predominantly white coat and cha...`
  - `Medium-sized French scent hound with distinctive short, dense tricolor coat and powerfu...`
  - `A small, spirited toy terrier with a refined but substantial build, characterized by it...`

### `bred_for`

- Inferred type: `JSON`
- Null / empty: **100.0%** (628 of 628)
- Distinct values: **0**
- Examples: _none (field is entirely null/empty)_

### `perfect_for`

- Inferred type: `JSON`
- Null / empty: **100.0%** (628 of 628)
- Distinct values: **0**
- Examples: _none (field is entirely null/empty)_

### `breed_group`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **26**
- Examples:
  - `Mixed`
  - `Sporting`
  - `Scenthound`
  - `Pariah`
  - `Toy`

### `history`

- Inferred type: `VARCHAR`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **628**
- Examples:
  - `Ancient Spanish Molosser breed tied to dogs brought by Alani tribes in 5th century. Tra...`
  - `Descended from Old English Bulldogs brought by working-class immigrants to the American...`
  - `Descended from English Foxhounds brought to American colonies in the 17th and 18th cent...`
  - `Developed in the late 19th century from English bull-and-terrier breeds brought to Amer...`
  - `Ancient landrace breed native to the Armenian Highlands, used for millennia as livestoc...`

### `reference_image_id`

- Inferred type: `VARCHAR`
- Null / empty: **14.3%** (90 of 628)
- Distinct values: **538**
- Examples:
  - `OAr3CJcw9i`
  - `33mJ-V3RX`
  - `IKwhmJWCwN`
  - `lIYQQfaDwr`
  - `WjazcxuOMh`

### `weight`

- Inferred type: `STRUCT(imperial VARCHAR, metric VARCHAR)`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **530**
- Examples:
  - `{"imperial":"7-10","metric":"3.2-4.5"}`
  - `{"imperial":"Male: 40-70; Female: 40-65","metric":"Male: 18-32; Female: 18-30"}`
  - `{"imperial":"Male: 38-60; Female: 35-55","metric":"Male: 17-27; Female: 16-25"}`
  - `{"imperial":"Male: 75-100; Female: 60-80","metric":"Male: 34-45; Female: 27-36"}`
  - `{"imperial":"Male: 25-30; Female: 20-25","metric":"Male: 11-14; Female: 9-11"}`

### `height`

- Inferred type: `STRUCT(imperial VARCHAR, metric VARCHAR)`
- Null / empty: **0.0%** (0 of 628)
- Distinct values: **480**
- Examples:
  - `{"imperial":"9-11.5","metric":"23-29"}`
  - `{"imperial":"Male: 20-24; Female: 18-22","metric":"Male: 52-62; Female: 46-55"}`
  - `{"imperial":"Male: 22-25; Female: 21-24","metric":"Male: 56-64; Female: 53-61"}`
  - `{"imperial":"10-20","metric":"25-51"}`
  - `{"imperial":"Male: 21-25; Female: 20-24","metric":"Male: 53-65; Female: 51-61"}`

### `image`

- Inferred type: `STRUCT(id VARCHAR, url VARCHAR, width BIGINT, height BIGINT)`
- Null / empty: **14.3%** (90 of 628)
- Distinct values: **538**
- Examples:
  - `{"id":"w1Cal_vrT","url":"https://cdn2.thedogapi.com/images/w1Cal_vrT.jpg","width":1600,...`
  - `{"id":"oFvaQYx899","url":"https://storage.googleapis.com/dog-api-uploads-prod/originals...`
  - `{"id":"SkmRJl9VQ","url":"https://cdn2.thedogapi.com/images/SkmRJl9VQ_1280.jpg","width":...`
  - `{"id":"hmOHpgNB1H","url":"https://cdn4.thedogapi.com/optimized/hmOHpgNB1H.jpg","width":...`
  - `{"id":"G0k1fak65p","url":"https://storage.googleapis.com/dog-api-uploads-prod/originals...`

## Messy-field format variants

### `life_span`

| Format variant | Count | Example |
|---|---|---|
| range: 'X-Y' | 588 | `12-15` |
| null/missing | 40 | `—` |

### `weight`

Object shapes found:

| Shape | Count |
|---|---|
| object with keys: imperial, metric | 628 |

Value formats inside `weight.imperial`:

| Format variant | Count | Example |
|---|---|---|
| sex-specific range: 'Male: … ; Female: …' | 432 | `Male: 55-65; Female: 45-55` |
| range: 'X-Y' | 194 | `7-10` |
| sentinel string: 'unknown' | 2 | `unknown` |

Value formats inside `weight.metric`:

| Format variant | Count | Example |
|---|---|---|
| sex-specific range: 'Male: … ; Female: …' | 430 | `Male: 25-30; Female: 20-25` |
| range: 'X-Y' | 196 | `3.2-4.5` |
| sentinel string: 'unknown' | 2 | `unknown` |

### `height`

Object shapes found:

| Shape | Count |
|---|---|
| object with keys: imperial, metric | 628 |

Value formats inside `height.imperial`:

| Format variant | Count | Example |
|---|---|---|
| sex-specific range: 'Male: … ; Female: …' | 480 | `Male: 27-29; Female: 25-27` |
| range: 'X-Y' | 146 | `9-11.5` |
| sentinel string: 'unknown' | 2 | `unknown` |

Value formats inside `height.metric`:

| Format variant | Count | Example |
|---|---|---|
| sex-specific range: 'Male: … ; Female: …' | 480 | `Male: 69-74; Female: 63-69` |
| range: 'X-Y' | 146 | `23-29` |
| sentinel string: 'unknown' | 2 | `unknown` |

### `temperament`

- Breeds with at least one tag: **628**
- Breeds with no temperament: **0**
- Tags per breed: avg **5.6**, min **1**, max **9**
- Distinct tags overall: **66** (**46** once lowercased)
- Most common tags (case-folded):
  - `intelligent` (536)
  - `loyal` (451)
  - `alert` (376)
  - `energetic` (303)
  - `courageous` (212)
  - `independent` (210)
  - `affectionate` (163)
  - `friendly` (161)
  - `protective` (143)
  - `playful` (140)

Format: a single comma-separated string, **not** a JSON array — needs splitting into a bridge table if tags are to be queried individually.

## Files

- `sample_breeds.json` — representative records, including sparse ones
- `raw_breeds.json` — full raw payload as fetched
