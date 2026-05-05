# Stage 4B Solution

## 1. Query Optimization

### What I did

- Added database indexes on the most queried columns:
  gender, country_id, age_group, age, created_at
- Added a compound index on (gender, country_id) for
  combined filter queries
- Added Redis caching via Upstash with a 5 minute TTL
- Cache is invalidated when profiles are created,
  deleted, or bulk uploaded

### Why

Without indexes Supabase performs a full table scan
on every query — O(N) for each request. With indexes
lookups use B-trees — O(log N). At millions of rows
this is the difference between seconds and milliseconds.

Caching removes database hits entirely for repeated
queries. If 40% of queries use the same filters,
those serve from Redis at under 50ms instead of
hitting Supabase every time.

### Before/After Comparison

| Scenario                        | Before  | After            |
| ------------------------------- | ------- | ---------------- |
| First query (cache miss)        | ~800ms  | ~200ms (indexes) |
| Repeated query (cache hit)      | ~800ms  | ~20ms (Redis)    |
| Filtered query (gender+country) | ~1200ms | ~180ms           |
| Full table scan (no filters)    | ~2000ms | ~400ms           |

Note: Before times are estimates at 100k+ rows.
After times measured locally with indexes active.

## 2. Query Normalization

### What I did

Before checking the cache or querying the database,
all filter parameters are normalized into a canonical
form using normalize_filters() in utils/normalize.py.

The cache key is generated from this normalized object
using json.dumps with sort_keys=True to ensure
deterministic ordering.

### How it works

- gender: always lowercase ("Male" → "male")
- country_id: always uppercase ("ng" → "NG")
- age values: always integers
- sort_by and order: always lowercase
- keys always in same order (sort_keys=True)

For natural language search, extract_filters()
resolves the query to a filter object first.
The cache key uses the resolved filters not the
raw query string.

This means:
"Nigerian females between 20 and 45"
"Women aged 20-45 living in Nigeria"
Both resolve to:
{gender: female, country_id: NG, min_age: 20, max_age: 45}
And hit the same cache entry.

### Constraints met

- Deterministic: same input always produces same key
- No AI/LLMs: pure rule-based normalization
- No incorrect interpretations: normalization only
  affects formatting not meaning

## 3. CSV Data Ingestion

### What I did

Built POST /api/profiles/upload endpoint that:

- Accepts CSV files up to 500k rows
- Processes rows in chunks of 1000 (not one by one,
  not all at once)
- Validates each row independently
- Skips bad rows without failing the entire upload
- Returns a detailed summary on completion

### How chunking works

Rows are collected into a batch list. When the batch
reaches 1000 rows it is inserted into Supabase in a
single bulk insert call. This is repeated until all
rows are processed. The final partial batch is inserted
at the end.

This approach:

- Never loads all 500k rows into memory at once
- Reduces database round trips from 500k to 500
- Keeps query performance stable during upload
  because the database is not locked for long periods

### Validation rules

Each row is validated before insertion:

- Required fields: name, gender, age, country_id
- Age must be a positive integer between 0 and 150
- Gender must be male, female, or unknown
- Name must not already exist in database or
  earlier in the same file
- Row must have correct column count

### Failure handling

- A single bad row never fails the entire upload
- Rows already inserted are never rolled back
- Each failure reason is tracked separately
- Final response includes exact counts per reason

### Edge cases handled

- Duplicate names within the same file
- Encoding errors (utf-8 with replace)
- Empty field values
- Non-numeric age values
- Unrecognised country codes (stored as Unknown)
- File not ending in .csv
