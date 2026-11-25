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

**Time spent on Part 1:** ___ min
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
1.
2.
3.
4.
5.
6.

**What I did**
-

**What the AI proposed that I rejected or changed, and why**
-

**How I verified the result**
-

**Open doubts / what I would do with more time**
-

---

## Part B — Silver generator

**Generated SQL for `articles.clauses` (or the array I chose)** — paste it here:

```sql

```

**How this SQL reflects my Part 1 design** (three lines: object type and version rule, decomposition, polymorphism):
-
-
-

**Why I chose these test cases**
-

**What the AI proposed that I rejected or changed, and why**
-

**How I verified the result**
-

**Open doubts / what I would do with more time**
-

---

## Part C — SQL

**What I did**
-

**What the AI proposed that I rejected or changed, and why**
-

**How I verified the result**
-

**Open doubts / what I would do with more time**
-

---

## Part D — Production questions

**What I did**
-

**What the AI proposed that I rejected or changed, and why**
-

**How I verified the result** (which answers you checked against the sample data or the code)
-

**Open doubts / what I would do with more time**
-

---

## Part 2 overall

**Time spent on Part 2:**
**Assumptions I made:**
-
