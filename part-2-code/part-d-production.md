# Part D — Production questions (~20 min)

Answer each of the 6 questions in **2-4 sentences**, and **name one concrete thing from your own experience per answer where you can**. We value clear, specific reasoning over length. Pseudocode, a short table or bullet points are fine.

---

## Question 1: Idempotency

The bronze loader from Part A appends rows and deduplicates on (VERSION_ID, validTo). BRONZE itself is append-only by design, so a re-run can still legitimately add rows (a closed version, a late correction, a re-load after a fix).

**What does "idempotent" mean for this pipeline, and where do you enforce it?** Consider the loader (re-runs, partial failures halfway through an entity type) and whatever you designed above BRONZE in Part 1: how does that layer stay deterministic regardless of how many times, and in which order, bronze was loaded?

> YOUR ANSWER:

Idempotent means two things:
- re-running against an unchanged API adds nothing to BRONZE;
- SILVER and GOLD give the same answer however often, and in whatever order, rows were loaded.

**Loader.** It enforces this with the (`VERSION_ID`, `validTo`) check before every append; after the Part A fixes, a second run appends 0. In Snowflake I would land each page in a transient staging table and append it with one `INSERT … WHERE NOT EXISTS`. A crash then never leaves half a page, and "resume" simply means "run again". I would also allow only one run per tenant at a time (`max_active_runs=1`), so two runs cannot both pass the check.

**Above BRONZE.** Nothing depends on load order. SILVER takes the latest load per `VERSION_ID` and derives `IS_CURRENT` from `validFrom`/`validTo`, never from `LOADED_AT` across versions. GOLD tables are fully rebuilt (`INSERT OVERWRITE`), never appended.

**From my own work:** our dbt incremental models use `delete+insert` on the business date, so re-running a day replaces that day instead of duplicating it. That is the same "replace, don't append" rule I apply to GOLD.

---

## Question 2: Incremental Loading

The API only offers keyset pagination over all entities of a type (`/entity/key/{type}/keyset?size=100&after=<token>`). There is no `modifiedSince` parameter. Today every run fetches everything and appends what is new to the BRONZE layer.

**How would you make ingestion incremental and cheaper?** What would you ask the API or product team to add (for example `modifiedSince`, a change feed or webhook, an event stream), and what are the trade-offs of polling vs. push vs. CDC for a platform that serves up to 240 tenants? How do you detect deletes?

> YOUR ANSWER:

**Without any API change.** Store the last keyset token per tenant and type and fetch only newer versions; this is valid if the keyset is ordered by creation. Add a weekly full scan as a reconciliation, because closing an old version (`validTo` changes) or deleting an entity does not add an item at the end of the keyset.

**What I would ask the product team for:** `modifiedSince` on the versions endpoint, covering `validTo` changes and deletes. Better still: an ordered change feed with a sequence number and tombstones (explicit delete events).

| | Full scan (today) | `modifiedSince` polling | Push (webhooks) | CDC / event stream |
|---|---|---|---|---|
| Cost at 240 tenants | grows with all data × tenants | grows with changes only | low | low |
| Completeness | complete, repairs itself | needs an overlap window for clock skew; deletes only if the API exposes them | events lost while the receiver is down, so replay is needed | complete including deletes, ordered, replayable |
| Operations | none | low | always-on endpoint, retries, ordering | highest; someone has to run it for every tenant |

For a nightly BI load I would choose `modifiedSince` plus the periodic full scan. Push or CDC only pays off when reports need to be fresher than one day.

**Deletes:**
- **With full scans:** anti-join the BRONZE keys against the keys seen in the last *complete* scan, and record each delete as an appended tombstone row, so BRONZE stays append-only.
- **With `modifiedSince` or a feed:** the API must send explicit delete events; otherwise deletes are invisible.

---

## Question 3: Error Handling Trade-offs

The loader in Part A has a `try/except` per entity type that logs and continues, retries transient errors with backoff and gives up on permanent ones. A malformed record inside a page, however, would still abort the whole entity type or be skipped silently, depending on where it fails.

**What error handling strategy would you implement for a production pipeline?** Consider: should one bad record block the entire batch? How do you surface errors for investigation, and how do you make a partially failed run safe to re-run?

> YOUR ANSWER:

**Bad records.** One bad record must not block the batch, but it must never disappear either.
- Validate every wrapper: required envelope keys, `configKey` equal to the requested type, valid JSON.
- Append the good records. Write the bad ones, with raw payload, error, page token and run id, to a `BRONZE.ENTITIES_REJECTED` table.
- Add a threshold (e.g. more than 1% rejected in a type fails that type). Many bad records usually mean an API change, not bad data.

**Surfacing errors.**
- Every run writes one row per tenant × type to a run log: pages, read, appended, skipped, rejected, status, error.
- The run exits non-zero when any type failed, so the scheduler shows it red. The Part A loader logs `claims` as an ERROR but still exits 0.

**Re-running.** A partial run is safe to re-run because of Q1 (page-level append plus the dedup key). Rejected records are re-fed by re-running the type after the fix, never by editing BRONZE by hand.

**From my own work:** in Airflow I split work per item with dynamic task mapping (`.expand()`). One failing entity type is then one red task that can be retried on its own while the others stay green.

---

## Question 4: Schema Drift

A new version of the `persons` configuration (v2.0) adds a nested array `nationalities` (objects with `countryCode` and `since`), removes the `age` field, and changes `addresses[].houseLetter` from string to integer. BRONZE keeps receiving both shapes: older versions with `age` and a string `houseLetter`, newer ones with `nationalities` and an integer `houseLetter`.

**What happens to whatever you designed above BRONZE in Part 1, and how do you roll the change out safely** across all customer databases? Name what breaks, what silently goes missing, and what you would automate.

> YOUR ANSWER:

| Change | Before the views are regenerated | After regenerating from v2.0 only |
|---|---|---|
| `nationalities` added | Items already appear in `ENTITY_ARRAY_ITEM` (tier 1 is schema-agnostic), but there is no typed view yet. `ENTITY_EXTRA_FIELD` flags `nationalities.countryCode` and `since`: a drift signal, nothing lost. | New view `PERSONS_NATIONALITIES`. |
| `age` removed | No effect. | Column `AGE` disappears from `PERSONS`, so every query or GOLD job selecting it **breaks**. Old versions' values stay in `DATA` but appear as "extra fields": noise. |
| `houseLetter` string → integer | No effect. | `ITEM:houseLetter::NUMBER` fails on old versions (`v-004-a` has `"B"`), so the whole `PERSONS_ADDRESSES` view **errors** for every query. |

**What I would automate.** The generator builds the typed views from the union of *all* configuration versions in `BRONZE.ANVA6_CONFIGURATIONS`, with three rules:
- columns are only ever added;
- a removed field stays as a nullable column for older versions;
- a type conflict widens the column (here to `VARCHAR`), never narrows it.

It also prints a diff (fields added / removed / retyped) and marks each change as safe or breaking.

**Rollout.** The same generator release goes to every customer database, but in waves:
1. a dry-run diff on all tenants;
2. apply to 2–3 canary databases;
3. run the views and the DQ checks there: rows per array path, `ENTITY_EXTRA_FIELD` back to zero for the new fields, the GOLD mapping check;
4. then the rest.

**From my own work:** in dbt, a renamed source column broke every model that selected it, and we only found out at run time. A diff before deployment is exactly what was missing.

---

## Question 5: AI Collaboration

Suppose the AI produced your Part B generator's SQL for `articles.clauses`: a chain of two flattens, typed casts, a version rule, and it looks correct at first glance.

**What is your process for validating AI-generated SQL like this before deploying it?** What are the specific risks you check for, and which of them would the sample data in `data/` let you check?

> YOUR ANSWER:

I treat AI SQL like a junior's pull request: I read it until I can explain every line, then run it on data with known answers before I trust it.

**Risks I check for in a two-flatten query:**
- **Grain:** chained `FLATTEN`s multiplying rows, or contracts with an empty array dropped because `OUTER => TRUE` is missing (`ctr-103`'s hull article has `"clauses": []`).
- **Version rule:** "latest loaded row" used instead of the current version (the re-loaded `v-002-a` and `v-043-a`), or drafts counted as current (`v-105-a`, `v-006-a`).
- **Silent NULLs:** Snowflake JSON paths are case-sensitive, and a typo returns NULL without an error, so I assert non-null counts per column. Casts can fail, or, with `TRY_CAST`, quietly hide bad values.
- **Invented functions or syntax.**

**What the sample data can check:** all of the above, through expected counts. For example, `articles.clauses` over the loaded fixtures must give exactly 3 rows (`v-101-a`, `v-102-a`, `v-104-a`; none for `v-103-a` and `v-105-a`). The samples cannot show cost at scale, concurrent loads, or real drift across tenants.

**From my own work:** when migrating reference tables from Oracle to Snowflake, I validated with a script of reconciliation checks: row counts against the source export, duplicate keys, dangling parent references, cycles in a hierarchy. I would write the same kind of checks here.

---

## Question 6: Reflection on Part 1

Part 2 made you implement your Part 1 design and showed how the API pages, versions and configurations behave: keyset pagination, versions that get closed after they were loaded, polymorphic arrays with `_discriminator`, local `$defs` references, arrays nested inside arrays and behind objects.

**Would you change anything in your Part 1 design now? What, and why (or why not)?** Do not edit Part 1; answer here.

> YOUR ANSWER:

Yes, four details that the Part 2 data exposed.
1. **Draft detection.** Person and organization wrappers have no `isDraft`, only `currentState` (`v-006-a` is `"draft"`). My `COALESCE(isDraft, FALSE)` would make that draft person current. The rule should be `isDraft OR currentState = 'draft'`.
2. **Tie-breaker.** Persons and organizations have no `versionTag`, so my `IS_CURRENT` tie-breaker does nothing for them. Order by `VALID_FROM` first, then `versionTag`, then `createdAt` and `versionId` so that ties are deterministic.
3. **Scalar arrays.** `organizations.tradeNames` has no place in my typed layer: `ENTITY_ARRAY_ITEM` keeps only object items, and the root view skips arrays. I would expose scalar arrays as an `ARRAY` column on the parent view.
4. **Schema versions.** Typed views should be generated from the union of all configuration versions, with columns that are never removed (see Q4). Part 1 generated them from the latest configuration only.

I applied fixes 1 and 2 in the Part B generator; Part 1 stays as I first wrote it.

**What I would keep:**
- **Every version, keyed on `VERSION_ID`:** `ctr-102` points at Maria's old `v-002-a`, so current-only SILVER would lose its policyholder.
- **Latest load per version:** it handles exactly the re-loaded `v-002-a` and `v-043-a`.
- **The schema-agnostic tier 1:** it absorbed the `$defs` alias chain and the nested and behind-object arrays without any special case.
