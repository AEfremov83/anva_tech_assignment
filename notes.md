# notes.md — Decision log

Mandatory part of your submission (about 10 minutes per part). Bullet points are fine; specifics beat prose. We grade this on concreteness: name the actual suggestion, the actual reason, the actual check.

Fill in the Part 1 section before you open Part 2, and leave it as it is afterwards (see the order rule in `readme.md`).

---

# Part 1 — Architecture

## Q1 — Medallion modelling

**What I did**
- Went through the contract sample and its configuration first: envelope versus `data`, the `_discriminator` variants, `jet://` references versus local `$ref`, inline `oneOf` code lists.
- SILVER is a mixed design (C) with two tiers:
  - **Tier 1:** fixed views over BRONZE (`ENTITY_VERSION`, `ENTITY_ARRAY_ITEM`, `ENTITY_EXTRA_FIELD`).
  - **Tier 2:** typed views generated from the configuration, one per entity type, one per array path, and one per variant.
- Version rule: the latest `LOADED_AT` per `VERSION_ID` wins, because a re-load carries the new `validTo`. Then `IS_CURRENT` = not a draft, in effect now, and the highest `VERSION_TAG` among the versions in effect.
- GOLD:
  - three facts: contract (current), coverage (current), and contract × month-end;
  - dimensions keyed by version;
  - a hand-maintained `PRODUCT_MAPPING`, because premium, insured amount and status sit in different fields per product.
- Q1c: I wrote the query myself. The AI corrected it:
  - `WHERE` was placed after `GROUP BY`;
  - `COUNT(hca.*)` became `COUNT(hca.ITEM_PATH)`;
  - `GROUP BY` uses the contract key instead of the premium.

**How the second product (bl055) fits my model**
- Tier 1 is unchanged: bl055 rows go into `ENTITY_VERSION` and produce 0 rows in `ENTITY_ARRAY_ITEM`. The generator emits a single view, `SILVER.BL055`.
- Inline `oneOf` lists become `CODE_LIST` rows. `contract` resolves on `VERSION_ID` only, because the reference says `contracts` while contracts are stored under their product key.
- GOLD needs only its own mapping rows:
  - the single `coverage` object counts as 1 coverage;
  - the policyholder comes from the referenced contract;
  - the building address fills `RISK_POSTAL_CODE`.

**How the ERD relates to the DDL** (same entities? where they differ and why)
- Same objects: the tier-1 views plus the hull-caravan typed views (`HCI_` = `HULLCARAVANINTERMEDIARY_`).
- Left out of the ERD:
  - `CONFIG_FIELD` and `CODE_LIST`: metadata with no key relation to the data;
  - the per-variant views: they have the same key as their union view.
- In the ERD but not in the DDL: `PERSONS`, `PERSONS_ADDRESSES` and `ORGANIZATIONS`. There is no persons sample, so I assume they are generated the same way. They are needed for the postal-code join.

**What the AI proposed that I rejected or changed, and why**
- Removed the AI's Qlik-specific claims: role-playing views "because Qlik cannot associate one table through two keys", loops, synthetic keys. I have not worked with Qlik and could not defend them.
- The AI offered two readings of "premium per month". I chose "in force at each month-end" over "new business by start date": it uses the version history, and an intermediary transfer lands in the right month.
- I chose mixed (C) over fully typed because of:
  - schema drift;
  - the number of objects (about 40 products × about 7 per customer, in 80–240 databases);
  - the polymorphic arrays.
- I chose to type all schema fields instead of a curated list, so nobody has to maintain the list.
- I added the schema `title` (the Dutch label) to `CONFIG_FIELD`, to be emitted as a view column comment.
- I spotted that `CONFIG_FIELD` was created after the view that reads it, and had the DDL reordered; Snowflake would fail that deploy.
- I asked for the generator to be described explicitly in Q1a; it was unclear.

**How I verified the result**
- Checked the amounts by hand against the sample:
  - the articles' `netInvoiceAmount` sums to 312.4 + 48.0 + 36.5 = 396.9, which equals `cumulativePremiumAmounts.netAnnualPremium`;
  - the articles' tax amounts sum to 65.6 + 10.08 + 7.67 = 83.35;
  - the root `netAnnualPremium` (486.2) does not reconcile with either, so I flagged it.
- Traced `IS_CURRENT` for `v-2041-c` (valid from 2026-04-01, `validTo` null, not a draft): TRUE today.
- Listed the 10 `ENTITY_ARRAY_ITEM` rows the sample produces. `articles[0].clauses[0]` gets `ARRAY_PATH = 'articles.clauses'` and `PARENT_ITEM_PATH = 'articles[0]'`.
- Compared every sample field with the configuration: only `customerReference` is missing, so it is the only `ENTITY_EXTRA_FIELD` row.
- Q1c expected result: `ctr-2041 | CAR-2026-004417 | 486.2 | 3`.
- Nothing has been run on Snowflake. The `FLATTEN` `PATH` format, `REGEXP_SUBSTR(..., 'e')` and `OBJECT_DELETE` are written from the documentation.

**Open doubts / what I would do with more time**
- Which premium is leading: the root 486.2 or the coverage sum 396.9?
- The primary address of a person: I assumed the first item, because no address type is known.
- `VERSION_ID` is assumed unique across entity types; references depend on it.
- I assumed `data` does not change when a version is re-loaded (only `validTo` does).
- `ENTITY_EXTRA_FIELD` matches paths without the discriminator, so a field from another variant would not be flagged.
- Old versions were validated against an older configuration, so fields removed later would show up as extra fields.
- With more time: run the tier-1 views on a Snowflake trial against the sample JSON.

---

## Q2 — Polymorphic arrays

**What I did**
- Chose shared columns + `VARIANT` as the stored structure (c), with a fully typed view generated per variant (a, as views).
- The union view types the fields shared by all variants plus every entity reference. `PERSON_VERSION_ID` exists only on `policyHolder`, but it is the join key, so it has to be typed.
- My own example: in dbt, incremental models with `on_schema_change = 'append_new_columns'` need a `--full-refresh` to fill new columns, and renamed source columns break models.

**What the AI proposed that I rejected or changed, and why**
- Rejected one wide table (b): about 700 mostly-NULL columns and an `ALTER TABLE` every release.
- Rejected physical per-variant tables (a): about 40 tables to union for totals, and a new table plus a backfill for every new variant.
- The AI wrote my dbt example from my description; I checked that it matches what actually happened.

**How I verified the result**
- From the configuration, the fields shared by all 3 article variants are `_discriminator`, `coverageCode`, `netInvoiceAmount`, `taxCode` and `taxAmount`.
  - `sumInsured` exists only on `hull`.
  - `sequenceNumber` exists only on `breakdownAssistance`.
  - `intermediaryCommission` exists on 2 of the 3.
- Worked out `VARIANT_FIELDS` by hand for each of the 3 sample articles.

**Open doubts / what I would do with more time**
- The shared-field set is computed per release. If a new variant lacks a shared field, that column drops out of the union view and breaks consumers. A rule of "published columns are never removed" may be needed.
- With about 40 per-variant views per product, BI users may struggle to find the right one.

---

## Q3 — Design scenarios

**What I did**
- Compared views + (C) against dynamic tables + (C): the same SQL, the only difference being whether tier 1 is stored.
- Pilot: views + (C) on the smallest customer, the largest, and the one with the most products. Promote tier 1 to dynamic tables where the views no longer fit the nightly window.

**What the AI proposed that I rejected or changed, and why**
- Comparing against physical tables + fully typed (iii + A) was considered and rejected. The question asks for the two most logical scenarios, and (A) was already rejected in Q1 and Q2.
- My measurement list (execution time, scalability, cardinality, robustness, data quality) was made concrete with the AI:
  - credits per customer via `QUERY_TAG`;
  - the re-load ratio (BRONZE rows per version);
  - the share of references that resolve;
  - extra fields per release.
- The AI pointed out that `SYSDATE()` prevents incremental refresh, so `IS_CURRENT` has to move into a view when tier 1 is promoted. I kept this, but have not verified it on Snowflake.

**How I verified the result**
- Checked that tier-1 columns do not depend on any configuration, so a release never requires recreating a dynamic table.
- No measurements are possible without Snowflake.

**Open doubts / what I would do with more time**
- Whether incremental refresh supports the `ROW_NUMBER` deduplication and the recursive `FLATTEN`; the pilot would test this.
- The nightly window and the credit budget are unknown, so the decision rule has no thresholds yet.
- Cost attribution per customer if warehouses are shared.

---

## Part 1 overall

**Time spent on Part 1:** 120 min
**Assumptions I made:**
- `VERSION_ID` is unique across entity types.
- A version's `data` does not change on re-load; only `validTo` does.
- Envelope timestamps are UTC.
- The contract premium is the root `netAnnualPremium`.
- A person's first address is the primary one.
- Persons and organizations have the `addresses` array described in the readme.
- Reporting covers policies only: `applicationGoal = 'policy'`, non-draft.
- bl055 takes its policyholder and intermediary from the contract it references.

---

# Part 2 — Code

## Part A — Bronze loader

**Bug ranking by production impact** (most severe first, with the concrete symptom in BRONZE or in the logs):
1. **`fetch_pages` breaks after the first page.**
   - BRONZE: only the first page (100 versions) per entity type ever lands, on every run. In the fixtures, persons p2/p3 (`v-004-a` … `v-008-a`), organizations p2 and contracts p2 (`v-104-a`, `v-105-a`) are missing.
   - Logs: no error, only `pages: 1` for every type. Re-runs never repair it.
2. **Dedup on `entityId` instead of `versionId`.**
   - BRONZE: a new version that has the same `validTo` as an already loaded version of the same entity (usually NULL, i.e. the new current version) is skipped. `v-002-b` and `v-043-b` are missing, so after the re-append of the closed `v-002-a`, `ent-002` has no current version at all, and contracts that reference `v-002-b` dangle.
   - Logs: the skip counts as normal dedup. Re-runs never repair it.
3. **`ENTITY_TYPE` lags one type behind.**
   - BRONZE: organizations are stored as `persons`, contracts as `organizations` (buggy run: persons 7, organizations 5, hull 1). SILVER per-type views pick up the wrong entities, and the next run re-appends them because dedup is per type.
   - The payload is intact, so the data is recoverable, but only through a correction view, since BRONZE is append-only. Detectable with `ENTITY_TYPE <> PAYLOAD:configKey`.
4. **Client secret logged and hard-coded.**
   - Logs: the token with the secret is in the first INFO line of every run, and the secret is in git.
   - No data damage, but anyone with log or repo access can read the tenant's API. The secret has to be rotated. I rank data bugs higher; in a security review this would be first.
5. **Mutable default `cache=set()` in `known_keys`.**
   - BRONZE: types 2 onwards are deduped against the persons' keys, so every run re-appends their already loaded versions (`v-042-a`, `v-101-a`). Duplicates grow every night.
   - SILVER's latest-load dedup hides them, but storage grows and the duplicate-version DQ check is noisy.
6. **Retry catches `PermanentError` instead of `TransientError`.**
   - A 503 abandons the whole type for the night: `v-044-a` and `v-045-a` are missing until a later run succeeds. Logs: `ERROR … giving up … 503`.
   - A 422 is retried 3 times, with 3 misleading "retrying" warnings and extra API calls, instead of one error.
   - It repairs itself on the next good run, hence the lower rank.
7. **Only `TransientError`/`PermanentError` caught per type.**
   - Latent: any other exception (e.g. a wrapper without `versionId` → `KeyError`) stops the run and all remaining types. That breaks the rule "one failing type must not stop the others". It does not occur in the fixtures.

**What I did**
- Read the loader rules in the docstring, ran the script unchanged, and compared every function with the rules.
- Fixed 7 issues, each marked `# FIX:`:
  - the `break` became `if after is None: break`;
  - the dedup key is `(versionId, validTo)` on both sides;
  - `known_keys` builds a fresh set per type;
  - rows are labelled with `config_key`;
  - only `TransientError` is retried, and exhaustion raises a `TransientError` with its cause;
  - an extra `except Exception` per type;
  - the secret is read from the environment and the token is no longer logged.

**What the AI proposed that I rejected or changed, and why**
- The AI flagged that a security review would put the leaked secret first. I placed it fourth: the ranking is about production data impact, and the fix is one line plus a secret rotation, with no damage to BRONZE.
- I checked these and left them unchanged:
  - **Drafts are loaded** (`v-006-a`, `v-105-a`): BRONZE stores raw API responses, and filtering belongs in SILVER (`IS_DRAFT`).
  - **The `lambda` in `fetch_pages`:** it is called immediately inside `with_retry`, so it captures the current `after`.
  - **`LOADED_AT` format** (`+00:00` here, `Z` in the existing rows): cosmetic; in Snowflake it would be a `TIMESTAMP` set at insert.

**How I verified the result**
- **Unchanged run:** 3 pages, 10 read, 7 appended; BRONZE 6 → 13 (persons 7, organizations 5, hull 1). The token was printed, and claims was retried 3 times.
- **Expected numbers, derived by hand from the fixtures:**
  - the API serves 19 versions;
  - 4 are unchanged (`v-001-a`, `v-003-a`, `v-042-a`, `v-101-a`);
  - 2 were closed since they were loaded (`v-002-a` and `v-043-a`, whose `validTo` changed from NULL to a date);
  - 13 are new.
  - That gives 15 appended and 4 skipped, and BRONZE 6 → 21 (persons 10, organizations 6, hull 5).
- **Fixed run:** matches exactly. One WARNING for the 503 on `organizations-p2` followed by success; one ERROR for the claims 422.
- **Second run on the same BRONZE:** appends 0 (idempotent), and every row has `ENTITY_TYPE == PAYLOAD.configKey`.
- **The bugs masked each other:**
  - The shared cache hid the `entityId` dedup bug: `v-043-b` was appended only because organizations were deduped against the persons' keys.
  - The page-1 `break` hid the retry bug: `organizations-p2` was never requested.
  - So I verified after all fixes, against the fixture-derived numbers, not fix by fix.

**Open doubts / what I would do with more time**
- **Full scan every night:** the loader always starts at `after=None` and relies on dedup. For large tenants that is many API calls; incremental loading is covered in Part D.
- **Key loading:** `known_keys` holds all keys of a type in memory. In Snowflake this would be a query on `(VERSION_ID, PAYLOAD:validTo)`, or an anti-join from a staging table.
- **Data changes without a `validTo` change** are skipped by the agreed dedup key. A payload hash would catch them, if that can happen.
- **No guard against a looping `nextToken`** (the API repeating a token), which would cause an endless loop.
- **Exit code:** the run exits 0 even when a type failed. A non-zero exit would let the scheduler alert.

---

## Part B — Silver generator

**Generated SQL for `articles.clauses` (or the array I chose)** — paste it here:

```sql
-- articles.clauses: one row per item of every version, every field typed; PARENT_ITEM_PATH joins the articles item's ITEM_PATH
CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES_CLAUSES AS
SELECT
    i.VERSION_ID,
    i.ITEM_PATH,
    i.PARENT_ITEM_PATH,
    i.ITEM_INDEX,
    i.ITEM:sequenceNumber::NUMBER(38,0)                                    AS SEQUENCE_NUMBER,
    i.ITEM:number::VARCHAR                                                 AS NUMBER,
    i.ITEM:version::VARCHAR                                                AS VERSION,
    i.ITEM:textShort::VARCHAR                                              AS TEXT_SHORT
FROM SILVER.ENTITY_ARRAY_ITEM AS i
WHERE i.ENTITY_TYPE = 'hullCaravanIntermediary'
  AND i.ARRAY_PATH  = 'articles.clauses';

-- and the polymorphic parent (Q2):
CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES AS
SELECT
    i.VERSION_ID,
    i.ITEM_PATH,
    i.ITEM_INDEX,
    i.DISCRIMINATOR,
    i.ITEM:coverageCode::VARCHAR                                           AS COVERAGE_CODE,
    i.ITEM:netInvoiceAmount::NUMBER(38,8)                                  AS NET_INVOICE_AMOUNT,
    i.ITEM:taxCode::NUMBER(38,8)                                           AS TAX_CODE,
    i.ITEM:taxAmount::NUMBER(38,8)                                         AS TAX_AMOUNT,
    OBJECT_DELETE(i.ITEM::OBJECT, '_discriminator', 'coverageCode', 'netInvoiceAmount', 'taxCode', 'taxAmount', 'clauses') AS VARIANT_FIELDS
FROM SILVER.ENTITY_ARRAY_ITEM AS i
WHERE i.ENTITY_TYPE = 'hullCaravanIntermediary'
  AND i.ARRAY_PATH  = 'articles';
```

**How this SQL reflects my Part 1 design** (three lines: object type and version rule, decomposition, polymorphism):
- **Object type and version rule:** a `VIEW`, as in the Q3 pilot (views + mixed). It keeps every version; the version rule lives in the generated tier-1 view `ENTITY_VERSION`: latest `LOADED_AT` per `VERSION_ID`, then `IS_CURRENT` = not a draft (`isDraft` or `currentState = 'draft'`), in effect now, and the latest `validFrom` (then `versionTag`, `createdAt`, `versionId`). The chain back to BRONZE is `ENTITY_ARRAY_ITEM` (`LATERAL FLATTEN`) ← `ENTITY_VERSION` ← `BRONZE.ENTITIES_RAW.PAYLOAD`.
- **Decomposition:** each array path gets its own typed view over the generic `ENTITY_ARRAY_ITEM`, keyed on (`VERSION_ID`, `ITEM_PATH`). The nested clauses link to their article through `PARENT_ITEM_PATH = 'articles[0]'`, not through `sequenceNumber`.
- **Polymorphism (Q2):** `DISCRIMINATOR` column; the union view types the fields shared by all variants plus entity references, and the rest stays in `VARIANT_FIELDS`. There is one fully typed view per variant (`..._ARTICLES__HULL` with `SUM_INSURED`). For hull caravan that gives 1 root + 7 array + 6 variant views = 14, as stated in Part 1.

**Why I chose these test cases**
1. **Two-hop `$ref` alias chain** (the `persons.bankAccounts` shape): the case most likely to be missed by checking only one level of `$ref`. The test also checks that `jet://` refs are left unchanged.
2. **Cycles:** an alias loop `a → b → a` must raise a clear error, and a self-referencing tree (`node.children` → `node`) must be recorded once and terminate. Recursion without a guard is the classic walker bug.
3. **Arrays behind objects:**
   - an array behind an object, with and without `"type": "object"`, must get the same dotted path;
   - an array inside an object inside an array item must have that item's array as `parent_array` and appear in its `nested_arrays`.

   The readme calls out both.
4. **Polymorphic merge:**
   - two variants share a field name with different types (first wins, no crash);
   - a non-object variant is skipped;
   - an array that exists in only one variant is still found.
5. **Negatives:** scalar items, an `anyOf` of scalars, a `oneOf` code list on a scalar, and empty properties must not be reported as arrays of objects.
6. **Generator:** a field with conflicting types across variants must stay out of the union view (it is in `VARIANT_FIELDS`) and be typed in the variant view. That checks my Q2 rule rather than just the walker.

**What the AI proposed that I rejected or changed, and why**
- **Version rule:** the AI copied Part 1's tier-1 version rule unchanged. Checking it against the data for Part D Q6, I had two things changed:
  - **drafts:** `isDraft` or `currentState = 'draft'`, so `v-006-a` is no longer current;
  - **tie-breaker:** `VALID_FROM`, then `VERSION_TAG`, `CREATED_AT`, `VERSION_ID`, because a tie between person or organization versions was a random pick.

  Re-ran the script afterwards: 6 tests ok, 16 statements.
- **SQL in Python strings:** I questioned it. I kept it for the take-home and recorded it under open doubts.

**How I verified the result**
- **Hand count from `schemas.json`:** 4 configurations with properties, 11 array-of-object paths, 1 scalar array. Persons has 3 arrays (`addresses`, `profiles`, `bankAccounts` via the alias chain), organizations 1 plus scalar array `tradeNames`, hull caravan 7, bl055 0. The printed totals match.
- **Discovery details:**
  - `articles.clauses` has parent `articles`;
  - `controlData.scheduledFinancialTransaction` is reported under its dotted path with no parent;
  - `bankAccounts` fields are `iban`, `bic` and `accountHolderName`, which proves the two-hop chain is resolved.
- **Against Part 1:** the generated `..._ARTICLES` union view has the same shared columns and the same `OBJECT_DELETE` key list as the hand-written Part 1 DDL. The tier-1 views are a copy of Part 1 with two deliberate fixes, found while answering Part D Q6:
  - **drafts:** `isDraft` **or** `currentState = 'draft'`, because person and organization wrappers have no `isDraft` and `v-006-a` would otherwise count as current;
  - **tie-breaker:** `VALID_FROM` first, then `VERSION_TAG`, because persons and organizations have no `versionTag`; `CREATED_AT` and `VERSION_ID` last, so a tie never gives a random pick.

  Part 1 is left as submitted.
- All 6 tests pass. Not run on Snowflake.

**Open doubts / what I would do with more time**
- **Generated SQL never executed.** The `FLATTEN` `PATH` format and `REGEXP_SUBSTR(..., 'e')` in `ENTITY_ARRAY_ITEM` are untested.
- **Single-variant arrays** (`subjects`): the union view types every field and `VARIANT_FIELDS` becomes an empty object, which is redundant next to `__CARAVAN`.
- **Not generated in Part B:**
  - the column `COMMENT`s from schema `title`;
  - `CONFIG_FIELD` / `CODE_LIST` rows;
  - `ENTITY_EXTRA_FIELD`.

  All three are in the Part 1 design and were left out to keep Part B to the required scope.
- **Unquoted identifiers:** a field named like a Snowflake reserved word (e.g. `start`) would need a quoted column name.
- **SQL inside Python strings:** the fixed tier-1 SQL lives in Python string constants. In production I would keep it in `.sql` files (or dbt models) and keep only the generated part in Python, so the SQL can be linted and reviewed as SQL.

---

## Part C — SQL

**What I did**
- **Q1:** group BRONZE per (`ENTITY_TYPE`, `VERSION_ID`) and keep versions with more than one distinct `validTo`; return the load count, the distinct `validTo` values as an array, and the first and last `LOADED_AT`.
  - An open `validTo` is mapped to `'open'` before aggregating, because `COUNT(DISTINCT)` and `ARRAY_AGG` skip NULL.
  - `validTo` goes through `TIMESTAMP_NTZ` first, so two string formats of the same instant count as one value.
- **Q2:**
  - a catalogue `CUSTOM_ATTRIBUTE` (per entity type: JSON path, column name, data type);
  - a value table `ENTITY_ATTRIBUTE_VALUE` keyed on (`VERSION_ID`, `ATTRIBUTE_ID`), filled insert-only from Part 1's `ENTITY_EXTRA_FIELD`;
  - a pivot over `SILVER.PERSONS` (current version) using `MAX(IFF(...))` per attribute.

**What the AI proposed that I rejected or changed, and why**
- Nothing rejected. I accepted it after checking that Q1 returns exactly `v-002-a` and `v-043-a` on the loaded fixture data (see below).

**How I verified the result**
- **Q1 expected result:** I simulated it in Python on the BRONZE rows produced by the fixed Part A loader. Grouping per version gives exactly `v-002-a` (persons: 2 loads, `2026-06-30` and open) and `v-043-a` (organizations: 2 loads, `2026-03-31` and open), the two versions closed after their first load.
- **Q2 against Part 1:** the value table links to `VERSION_ID` like every SILVER structure, uses the `ENTITY_EXTRA_FIELD` view from Q1a, and the pivot uses the generated `PERSONS` view with `IS_CURRENT`.
- Not run on Snowflake.

**Open doubts / what I would do with more time**
- **Q1:** if a version is ever re-loaded with a changed `data` but the same `validTo`, this query does not see it. A `HASH(PAYLOAD:data)` comparison would.
- **Q2:**
  - The pivot's column list is generated per customer. Snowflake's `PIVOT ... IN (ANY)` is dynamic, but it yields quoted, untyped column names, so I kept conditional aggregation.
  - Values are attached per version, so the pivot shows the custom attributes of the person's *current* version. If an attribute is only set on an older version, it is not shown.
  - Custom fields that do not arrive in the payload (e.g. entered in another tool) would need a second loader into the same value table.

---

## Part D — Production questions

**What I did**
- Answered each question against my own design rather than in general terms:
  - **Q1:** where idempotency lives (the loader's dedup key, page-level appends, SILVER rules that ignore load order, GOLD fully rebuilt).
  - **Q4:** walked the three persons v2.0 changes through tier 1 and tier 2.
  - **Q6:** listed the Part 1 details the Part 2 data proved wrong.
- Added one example from my own work where I had one: dbt `delete+insert`, Airflow `.expand()`, a dbt source rename, reconciliation checks during an Oracle → Snowflake migration.

**What the AI proposed that I rejected or changed, and why**
- **Q1:** I asked which code actually makes the loader idempotent.
  - Only the dedup key is implemented: `known_keys`, `dedup_key`, the skip, and `seen.add`.
  - All-or-nothing per page is a Snowflake proposal, not in the code, and the answer says so.
  - Two runs at the same time are prevented only by `max_active_runs=1`.
- **Q6:** I didn't leave findings 1–2 as text only. I had them applied in the Part B generator and left Part 1 as submitted.

**How I verified the result** (which answers you checked against the sample data or the code)
- **Q4:** `v-004-a` in `api-pages.json` really has `houseLetter: "B"`, so a cast to `NUMBER` would fail on existing data.
- **Q5:**
  - `ctr-103`'s hull article has `"clauses": []`;
  - the loaded fixtures contain exactly 3 article clauses (`v-101-a`, `v-102-a`, `v-104-a`);
  - `v-002-a` and `v-043-a` are re-loaded, `v-105-a` and `v-006-a` are drafts.
- **Q6:**
  - person and organization wrappers in `api-pages.json` have no `isDraft` and no `versionTag` (only contracts do);
  - `organizations.tradeNames` is a scalar array;
  - `ctr-102` references `v-002-a`.
- **Q1:** the Part A loader's second run appends 0.

**Open doubts / what I would do with more time**
- **Q6 findings 1 and 2** (draft detection, tie-breaker) are real gaps in the SQL I submitted in Part 1. I fixed them in the Part B generator's tier-1 SQL and left Part 1 as submitted.
- **Q2:** whether the keyset is ordered by creation is an assumption; it decides whether the "last token" shortcut is safe at all.
- **GDPR:** a right-to-erasure request conflicts with "nothing in BRONZE is ever deleted". That needs a separate, audited purge process.

---

## Part 2 overall

**Time spent on Part 2:** 3h
**Assumptions I made:**
- Every change gets a new `versionId`; an existing version only changes its `validTo` (readme). That is why the dedup key is (`versionId`, `validTo`).
- The API's keyset pagination is ordered by creation.
- None of the SQL was run on Snowflake; it is written from documentation.
