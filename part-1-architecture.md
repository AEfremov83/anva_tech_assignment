# Part 1 — Architecture questions

Three questions, about 65 minutes in total plus 10 minutes for `notes.md` (75 minutes for Part 1). Question 1 also asks for a high-level ERD in `part-1-erd.md`. Write your answers directly under each question. You do not need a running Snowflake; write DDL and SQL from the sample payload and the descriptions below (Snowflake dialect preferred, ANSI is fine).

Throughout, the raw data is assumed to sit in one append-only BRONZE table per customer database:

```sql
CREATE TABLE BRONZE.ENTITIES_RAW (
    LOADED_AT    TIMESTAMP_NTZ,   -- when this row was appended
    ENTITY_TYPE  VARCHAR,         -- the configuration key, e.g. 'persons', 'hullCaravanIntermediary'
    ENTITY_KEY   VARCHAR,         -- the entityId
    VERSION_ID   VARCHAR,         -- the versionId
    PAYLOAD      VARIANT          -- the full API wrapper JSON, unchanged
);
```

Every new version of an entity arrives as a new row. Re-loads can also produce a second row for the same version. Nothing is updated or deleted.

---

## Question 1 — Medallion modelling from the ANVA 6 JSON (~40 min)

### About the sample files

Open `data/anva6-contract-sample.json`. This is the shape of a real ANVA 6 contract as it lands in `BRONZE.ENTITIES_RAW.PAYLOAD`, here a caravan hull insurance product sold through an intermediary. The outer keys (`configKey`, `entityId`, `versionId`, `currentState`, `isDraft`, `validFrom`, `validTo`, ...) are the API envelope; the business content is under `data`. A few things to know before you model it:

- **Field names are the real ones; all values are fictitious.** The full contract schema has more than 120 root fields; the sample shows a representative subset.
- **`_discriminator`** marks the variant of an item in a polymorphic array. `parties`, `subjects` and `articles` are such arrays: each item carries a `_discriminator` and the set of fields depends on the variant (for example a `hull` article carries `sumInsured`, `deductibleAmount` and nested `clauses`, while a `breakdownAssistance` article has none of those and a `typeOfCalculationAtRenewal` instead).
- **`parties[].person` and `parties[].organization`** are references to a specific **version** of a person or organization entity (the `versionId`, not the `entityId`). This is snapshot semantics: the contract stays pointed at the version of the policyholder or intermediary it was issued with, even when that person or organization is updated later. The configuration shows these fields as `jet://entity/persons#/properties/id`; the `id` of an entity version is its `versionId`, so a reference always points at one specific version.
- **`controlData`** holds process-control fields, among them an array of objects (`scheduledFinancialTransaction`) that sits behind an object rather than at the root.
- **`customerReference`** is not part of the contract schema. It represents schema drift or a customer-specific field that the platform has to cope with without losing it.

The matching configuration row is `data/hull-caravan-configuration.json`: the JSON schema this entity was validated against, trimmed to the fields the sample uses, plus the `states` of the entity. Reference only, you do not need to read it line by line. It shows how the platform encodes what you see in the data: polymorphic arrays as `items.anyOf` with a `_discriminator` `const` per variant, code lists as `jet://schema/...Lookup` references or inline `oneOf`, and entity references as `jet://entity/...` (the full configuration has 120+ root fields and about 40 article variants).

Two more files show a **second, much simpler product exactly as both land in bronze**: `data/bl055-opstal-entity.json` is one buildings-insurance entity (`bl055`) as returned by the API, and `data/bl055-opstal-configuration.json` is its configuration row (the JSON schema under `schema`, plus the `states` the entity can be in). Note the inline `oneOf` code lists (`buildingType`, `roofType`, `status`) next to the `jet://schema/CountryLookup` reference, the `readOnly` calculated premium fields, and the `contract` field that references another entity. The platform has about 40 entity types (products); the same generated code must serve all of them.

Q2 and Q3 below cover polymorphism and materialisation separately; reference them from here rather than repeating yourself. Here we want the **structural** model. Keep DDL minimal: keys plus a few representative columns per table; `...` is allowed.

### (a) SILVER — the layer above BRONZE

How would you store contracts for analysis? Fully relational, JSON kept with views on top, or a mix — your call. Show the structures and their keys (`CREATE TABLE` / `VIEW` DDL or a clear table list). State how you handle:

- entity versions / history (every version is a new bronze row)
- the 1:1 nested objects (`productInformation`, `contractPeriod`, `contractAmounts`)
- the non-polymorphic arrays of objects (`clauses`, `termsAndConditions`)
- the polymorphic arrays (`parties`, `subjects`, `articles`) and the `clauses` nested inside `articles`
- the `versionId` references to persons / organizations in `parties[].person` and `parties[].organization`
- fields that are not in the schema (`customerReference`)
- what, if anything, stays as JSON
- how the second product (`bl055`, no arrays, inline code lists, a reference to a contract) fits into the same model without a redesign

Also provide a **high-level ERD** of your silver (and, if you like, gold) model as a Mermaid `erDiagram` in a Markdown file `part-1-erd.md` next to this file (template provided). Readable beats complete: show the main entities, keys and relations (cardinalities); you do not need every table. Keep it to what fits on one screen.

### (b) GOLD — the reporting model

The reporting model on top of your (a) for a Qlik "portfolio overview" report: one row per contract with policyholder, intermediary, product, status, premium and insured amount, plus coverage-level detail. It must also answer:

- Total premium per intermediary per month
- Average number of coverages (articles) per contract by product
- Top 10 postal codes by insured amount. The postal code is not in the contract: persons are separate entities with an `addresses` array (`street`, `houseNumber`, `postalCode`, `city`, `country`), referenced by versionId from `parties[].person`. No persons sample is provided in Part 1; state the join you assume.

Give fact / dimension DDL or a clear model description, and state the grain of each fact table.

### (c) One query

Write ONE query against your SILVER structures from (a): net annual premium and number of articles per contract, for the current version of each contract only.

> YOUR ANSWER (a) — SILVER model (the ERD goes in `part-1-erd.md`):

**Design in one sentence:** SILVER is a generated, two-tier set of views on top of BRONZE. Tier 1 is a small fixed set of schema-agnostic structural objects, identical in every customer database. Tier 2 is one typed view per entity type and per array path, generated from the configuration, with every schema field as a typed column. In Q3 terms this is decomposition (C), materialised as views first.

**The generator** is a Python program that runs once per release in every customer database. It reads each configuration row from `BRONZE.ANVA6_CONFIGURATIONS`, walks its schema, and writes two things:
- the tier-2 `CREATE OR REPLACE VIEW` statements;
- the rows of `CONFIG_FIELD` and `CODE_LIST`.

Per entity type it emits one root view, one view per array path, and, for polymorphic arrays, one extra view per `_discriminator` value. For the hull-caravan sample that is 14 views; for `bl055` it is 1. Tier 1 is hand-written once and never generated.

**Tier 1 — structural, schema-agnostic (same DDL in every customer database, no change per release)**

| Object | Kind | Grain / key | Content |
|---|---|---|---|
| `SILVER.ENTITY_VERSION` | view | `VERSION_ID` | One row per version of every entity type: typed envelope, `IS_CURRENT`, `DATA` (= `PAYLOAD:data`, unchanged) |
| `SILVER.ENTITY_ARRAY_ITEM` | view | `VERSION_ID, ITEM_PATH` | One row per item of every array of objects, at any depth: `ARRAY_PATH`, `PARENT_ITEM_PATH`, `ITEM_INDEX`, `DISCRIMINATOR`, `ITEM` |
| `SILVER.ENTITY_EXTRA_FIELD` | view | `VERSION_ID, FIELD_PATH` | Scalar values in `DATA` whose path is not in the configuration (e.g. `customerReference`) |
| `SILVER.CONFIG_FIELD` | table, written by the generator | `ENTITY_TYPE, FIELD_PATH, DISCRIMINATOR` | Field catalogue from `BRONZE.ANVA6_CONFIGURATIONS`: data path, array path, SQL type, `$ref` target, `readOnly`, `title` |
| `SILVER.CODE_LIST` | table, written by the generator | `LIST_KEY, CODE` | Codes and descriptions from `jet://schema/...Lookup` code lists and inline `oneOf` lists |

**Tier 2 — typed views, generated per entity type from its configuration (example: `hullCaravanIntermediary`)**

| View | Grain / key | Typed columns |
|---|---|---|
| `HULLCARAVANINTERMEDIARY` | `VERSION_ID` | Envelope, `IS_CURRENT`, every root scalar, and the 1:1 objects flattened (`productInformation`, `contractPeriod`, `contractAmounts.*`, `controlData` scalars) |
| `HULLCARAVANINTERMEDIARY_PARTIES` | `VERSION_ID, ITEM_PATH` | Polymorphic union view: fields shared by all variants, every `jet://entity` reference (`PERSON_VERSION_ID`, `ORGANIZATION_VERSION_ID`), `VARIANT_FIELDS` |
| `HULLCARAVANINTERMEDIARY_PARTIES__POLICYHOLDER`, `..._PARTIES__INTERMEDIARY` | `VERSION_ID, ITEM_PATH` | Per-variant views: all fields of that variant (see Q2) |
| `HULLCARAVANINTERMEDIARY_SUBJECTS` (+ `__CARAVAN`) | `VERSION_ID, ITEM_PATH` | Same pattern |
| `HULLCARAVANINTERMEDIARY_ARTICLES` (+ `__HULL`, `__BREAKDOWNASSISTANCE`, `__PURCHASEVALUEGUARANTEE`) | `VERSION_ID, ITEM_PATH` | Same pattern; shared: `COVERAGE_CODE`, `NET_INVOICE_AMOUNT`, `TAX_CODE`, `TAX_AMOUNT` |
| `HULLCARAVANINTERMEDIARY_ARTICLES_CLAUSES` | `VERSION_ID, ITEM_PATH`; `PARENT_ITEM_PATH` → article | All fields |
| `HULLCARAVANINTERMEDIARY_CLAUSES`, `..._TERMS_AND_CONDITIONS` | `VERSION_ID, ITEM_PATH` | All fields |
| `HULLCARAVANINTERMEDIARY_CONTROL_DATA_SCHEDULED_FINANCIAL_TRANSACTION` | `VERSION_ID, ITEM_PATH` | All fields (array behind an object) |

**How each point is handled**

- **Versions / history.** Every version is one row in `ENTITY_VERSION`, keyed on `VERSION_ID`. History is never collapsed, and validity comes from the platform (`validFrom`/`validTo`), so we build no SCD2 of our own.
  - **Re-loads:** per `VERSION_ID`, the latest `LOADED_AT` wins, because it carries the latest `validTo`.
  - **`IS_CURRENT`:** the version is not a draft, `VALID_FROM <= now < VALID_TO` (or `VALID_TO` is NULL), and it has the highest `VERSION_TAG` among the versions of that entity in effect now. The tie-breaker guards against a missed re-load leaving two versions open.
  - **Never used:** `isValidNow` (frozen at extract time) and "latest loaded row per entity" (a re-load of an old version arrives later than the current version).
  - **As-of reporting:** replace `SYSDATE()` with the as-of date.
- **1:1 nested objects.** They have the same grain as their parent, so no separate table. They are flattened into the parent's typed view with path-prefixed columns and a `__` separator, e.g. `CONTRACT_PERIOD__EFFECTIVE_DATE`. The full prefix is required: `contractCosts`, `cumulativePremiumAmounts` and `netAnnualPremium` each occur at more than one path.
- **Non-polymorphic arrays** (`clauses`, `termsAndConditions`). Their items are rows in `ENTITY_ARRAY_ITEM`, with one typed view per `ARRAY_PATH` holding all fields. The key is the array position (`ITEM_PATH`), not `sequenceNumber`, because `sequenceNumber` is sparse: it is missing on the `intermediary` party and on the `hull` article.
- **Polymorphic arrays** (`parties`, `subjects`, `articles`). Storage is the same, plus a `DISCRIMINATOR` column. Each array gets a union view (shared fields + entity references typed, the rest in `VARIANT_FIELDS`) and one fully typed view per variant; reasoning in Q2. Only `_discriminator` identifies the variant; other `const` fields such as `coverageCode` or `businessLine` are ordinary columns.
  - **`articles[].clauses`** is its own `ARRAY_PATH` (`articles.clauses`) with its own view; `PARENT_ITEM_PATH = 'articles[0]'` links it to its article. This works at any depth.
  - **Arrays behind an object** (`controlData.scheduledFinancialTransaction`) are handled the same way, with `PARENT_ITEM_PATH` NULL.
- **`versionId` references.** Each `jet://entity/...` field becomes a `VARCHAR` column with a `_VERSION_ID` suffix (`PERSON_VERSION_ID`, `ORGANIZATION_VERSION_ID`). It joins to `VERSION_ID` in `ENTITY_VERSION` or in the typed `PERSONS` / `ORGANIZATIONS` views, so snapshot semantics hold by construction.
  - The *current* person, if ever needed, is a second hop: referenced version → `ENTITY_KEY` → `IS_CURRENT`.
  - Always `LEFT JOIN`: persons are loaded in their own run and may arrive later than the contract.
- **Fields not in the schema (`customerReference`).** Never lost: the value stays in `DATA`. It has no typed column, because typed views are generated from the schema. `ENTITY_EXTRA_FIELD` lists it as (`VERSION_ID`, `FIELD_PATH = 'customerReference'`, `FIELD_VALUE`), which makes it queryable, gives a drift signal, and feeds the flexible-attribute structure. Together, the typed views and `ENTITY_EXTRA_FIELD` cover every value in `DATA`: a field in the schema is a typed column, a field not in the schema is a row here. Once the field enters the configuration, the next generator run types it.
- **What stays JSON.**
  - `ENTITY_VERSION.DATA` and `ENTITY_ARRAY_ITEM.ITEM`: complete, and the source for re-generating the typed views.
  - `VARIANT_FIELDS` in the polymorphic union views.
  - Values of extra fields.
  - Every field that *is* in the schema is also a typed column in some view.
- **Second product (`bl055`).** It needs no change to tier 1.
  - Its rows land in `ENTITY_VERSION` with `ENTITY_TYPE = 'bl055'` and zero rows in `ENTITY_ARRAY_ITEM`.
  - The generator emits one view, `SILVER.BL055`, with `INSURED_OBJECT__ADDRESS__POSTAL_CODE`, `COVERAGE__INSURED_AMOUNT`, `PREMIUM__NET_ANNUAL_PREMIUM`, `STATUS`, `CONTRACT_VERSION_ID`, ...
  - Inline `oneOf` lists become `CODE_LIST` rows (`LIST_KEY = 'bl055.insuredObject.buildingType'`); `jet://schema/CountryLookup` maps to `LIST_KEY = 'CountryLookup'`.
  - `readOnly` premium fields are typed like any other field; `CONFIG_FIELD.IS_READ_ONLY` records that the platform calculates them.
  - `contract` resolves on `VERSION_ID` regardless of entity type: the reference says `contracts`, but contracts are stored under their product `configKey`.
  - `data.id` differs from `entityId` here, so keys always come from the envelope.

**DDL (minimal)**

```sql
-- Tier 1 ----------------------------------------------------------------------------------------
CREATE TABLE SILVER.CONFIG_FIELD (
    ENTITY_TYPE     VARCHAR,    -- configuration key
    FIELD_PATH      VARCHAR,    -- path in the entity data (not in the schema), without array indexes: 'articles.sumInsured'
    ARRAY_PATH      VARCHAR,    -- enclosing array path, NULL at root level
    DISCRIMINATOR   VARCHAR,    -- variant the field belongs to, NULL if not in a polymorphic array
    SQL_TYPE        VARCHAR,    -- 'DATE', 'NUMBER(38,8)', ...
    REF_TARGET      VARCHAR,    -- 'jet://entity/persons', 'jet://schema/CountryLookup', or the inline list key
    IS_READ_ONLY    BOOLEAN,
    TITLE           VARCHAR,    -- schema title, e.g. 'Verzekerde som'
    ...
);

CREATE TABLE SILVER.CODE_LIST (
    LIST_KEY        VARCHAR,    -- 'CountryLookup', 'bl055.insuredObject.buildingType'
    CODE            VARCHAR,
    DESCRIPTION     VARCHAR,
    PRIMARY KEY (LIST_KEY, CODE)
);

CREATE OR REPLACE VIEW SILVER.ENTITY_VERSION AS
WITH latest_load AS (
    -- a version is appended again when its validTo changes: the latest load per version carries the latest validTo
    SELECT
        r.VERSION_ID,
        r.ENTITY_TYPE,
        r.ENTITY_KEY,
        r.PAYLOAD:versionTag::NUMBER(38,0)              AS VERSION_TAG,
        r.PAYLOAD:createdAt::TIMESTAMP_NTZ              AS CREATED_AT,
        r.PAYLOAD:validFrom::TIMESTAMP_NTZ              AS VALID_FROM,     -- all envelope timestamps are UTC ('Z')
        r.PAYLOAD:validTo::TIMESTAMP_NTZ                AS VALID_TO,       -- NULL = open-ended
        r.PAYLOAD:currentState::VARCHAR                 AS CURRENT_STATE,
        COALESCE(r.PAYLOAD:isDraft::BOOLEAN, FALSE)     AS IS_DRAFT,
        r.LOADED_AT                                     AS LAST_LOADED_AT,
        r.PAYLOAD:data                                  AS DATA
    FROM BRONZE.ENTITIES_RAW AS r
    QUALIFY ROW_NUMBER() OVER (PARTITION BY r.VERSION_ID ORDER BY r.LOADED_AT DESC) = 1
),
in_effect AS (
    SELECT
        l.*,
        NOT l.IS_DRAFT
            AND l.VALID_FROM <= SYSDATE()
            AND (l.VALID_TO IS NULL OR l.VALID_TO > SYSDATE())          AS IS_IN_EFFECT
    FROM latest_load AS l
)
SELECT
    e.*,
    e.IS_IN_EFFECT
        AND ROW_NUMBER() OVER (PARTITION BY e.ENTITY_TYPE, e.ENTITY_KEY, e.IS_IN_EFFECT
                               ORDER BY e.VERSION_TAG DESC) = 1         AS IS_CURRENT
FROM in_effect AS e;

CREATE OR REPLACE VIEW SILVER.ENTITY_ARRAY_ITEM AS
SELECT
    v.VERSION_ID,
    v.ENTITY_TYPE,
    f.PATH                                              AS ITEM_PATH,          -- 'articles[0].clauses[0]'
    REGEXP_REPLACE(f.PATH, '\\[[0-9]+\\]', '')          AS ARRAY_PATH,         -- 'articles.clauses'
    REGEXP_SUBSTR(f.PATH, '^(.*\\])\\.', 1, 1, 'e')     AS PARENT_ITEM_PATH,   -- 'articles[0]'; NULL without an enclosing array item
    f.INDEX                                             AS ITEM_INDEX,
    f.VALUE:_discriminator::VARCHAR                     AS DISCRIMINATOR,      -- NULL for non-polymorphic arrays
    f.VALUE                                             AS ITEM
FROM SILVER.ENTITY_VERSION AS v,
     LATERAL FLATTEN(INPUT => v.DATA, RECURSIVE => TRUE) AS f
WHERE f.INDEX IS NOT NULL
  AND IS_OBJECT(f.VALUE);

CREATE OR REPLACE VIEW SILVER.ENTITY_EXTRA_FIELD AS
WITH leaf AS (
    SELECT
        v.VERSION_ID,
        v.ENTITY_TYPE,
        f.PATH                                          AS FIELD_PATH,
        REGEXP_REPLACE(f.PATH, '\\[[0-9]+\\]', '')      AS SCHEMA_PATH,
        f.VALUE                                         AS FIELD_VALUE
    FROM SILVER.ENTITY_VERSION AS v,
         LATERAL FLATTEN(INPUT => v.DATA, RECURSIVE => TRUE) AS f
    WHERE NOT IS_OBJECT(f.VALUE)
      AND NOT IS_ARRAY(f.VALUE)
)
SELECT
    l.VERSION_ID,
    l.ENTITY_TYPE,
    l.FIELD_PATH,
    l.FIELD_VALUE
FROM leaf AS l
LEFT JOIN SILVER.CONFIG_FIELD AS c
    ON  c.ENTITY_TYPE = l.ENTITY_TYPE
    AND c.FIELD_PATH  = l.SCHEMA_PATH
WHERE c.FIELD_PATH IS NULL;

-- Tier 2 (generated; excerpts) -------------------------------------------------------------------
CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY AS
SELECT
    v.VERSION_ID,
    v.ENTITY_KEY,
    v.VERSION_TAG,
    v.VALID_FROM,
    v.VALID_TO,
    v.CURRENT_STATE,
    v.IS_CURRENT,
    v.DATA:contractNumber::VARCHAR                                      AS CONTRACT_NUMBER,
    v.DATA:startDate::DATE                                              AS START_DATE,
    v.DATA:statusType::VARCHAR                                          AS STATUS_TYPE,
    v.DATA:netAnnualPremium::NUMBER(38,8)                               AS NET_ANNUAL_PREMIUM,
    v.DATA:productInformation.productCode::VARCHAR                      AS PRODUCT_INFORMATION__PRODUCT_CODE,
    v.DATA:contractPeriod.effectiveDate::DATE                           AS CONTRACT_PERIOD__EFFECTIVE_DATE,
    v.DATA:contractAmounts.contractPeriodAmounts.cumulativePremiumAmounts.netAnnualPremium::NUMBER(38,8)
                                                                        AS CONTRACT_AMOUNTS__CONTRACT_PERIOD_AMOUNTS__CUMULATIVE_PREMIUM_AMOUNTS__NET_ANNUAL_PREMIUM,
    v.DATA:controlData.applicationGoal::VARCHAR                         AS CONTROL_DATA__APPLICATION_GOAL,
    ...                                                                 -- one column per scalar field in the schema
FROM SILVER.ENTITY_VERSION AS v
WHERE v.ENTITY_TYPE = 'hullCaravanIntermediary';

CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES AS
SELECT
    i.VERSION_ID,
    i.ITEM_PATH,
    i.ITEM_INDEX,
    i.DISCRIMINATOR,
    i.ITEM:coverageCode::VARCHAR                                        AS COVERAGE_CODE,
    i.ITEM:netInvoiceAmount::NUMBER(38,8)                               AS NET_INVOICE_AMOUNT,
    i.ITEM:taxCode::NUMBER(38,8)                                        AS TAX_CODE,
    i.ITEM:taxAmount::NUMBER(38,8)                                      AS TAX_AMOUNT,
    -- nested arrays are removed: they have their own view
    OBJECT_DELETE(i.ITEM::OBJECT, '_discriminator', 'coverageCode', 'netInvoiceAmount', 'taxCode', 'taxAmount', 'clauses')
                                                                        AS VARIANT_FIELDS
FROM SILVER.ENTITY_ARRAY_ITEM AS i
WHERE i.ENTITY_TYPE = 'hullCaravanIntermediary'
  AND i.ARRAY_PATH  = 'articles';

CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES__HULL AS
SELECT
    i.VERSION_ID,
    i.ITEM_PATH,
    i.ITEM:coverageCode::VARCHAR                                        AS COVERAGE_CODE,
    i.ITEM:sumInsured::NUMBER(38,8)                                     AS SUM_INSURED,
    i.ITEM:deductibleAmount::NUMBER(38,8)                               AS DEDUCTIBLE_AMOUNT,
    i.ITEM:coveragePremiumCalculation.adjustmentFactor::NUMBER(38,8)    AS COVERAGE_PREMIUM_CALCULATION__ADJUSTMENT_FACTOR,
    ...
FROM SILVER.ENTITY_ARRAY_ITEM AS i
WHERE i.ENTITY_TYPE   = 'hullCaravanIntermediary'
  AND i.ARRAY_PATH    = 'articles'
  AND i.DISCRIMINATOR = 'hull';

CREATE OR REPLACE VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES_CLAUSES AS
SELECT
    i.VERSION_ID,
    i.ITEM_PATH,                                                        -- 'articles[0].clauses[0]'
    i.PARENT_ITEM_PATH,                                                 -- = HULLCARAVANINTERMEDIARY_ARTICLES.ITEM_PATH
    i.ITEM_INDEX,
    i.ITEM:sequenceNumber::NUMBER(38,0)                                 AS SEQUENCE_NUMBER,
    i.ITEM:number::VARCHAR                                              AS NUMBER,
    i.ITEM:version::VARCHAR                                             AS VERSION,
    i.ITEM:textShort::VARCHAR                                           AS TEXT_SHORT
FROM SILVER.ENTITY_ARRAY_ITEM AS i
WHERE i.ENTITY_TYPE = 'hullCaravanIntermediary'
  AND i.ARRAY_PATH  = 'articles.clauses';
```

**Generator rules (configuration → typed view)**

| Schema | SQL type | Column |
|---|---|---|
| `string` | `VARCHAR` | path → `UPPER_SNAKE`, `__` between object levels |
| `string` + `format: date` | `DATE` | |
| `string` + `format: date-time` | `TIMESTAMP_NTZ` | |
| `integer` | `NUMBER(38,0)` | |
| `number` | `NUMBER(38,8)` | the schema does not separate amounts from rates (`taxCode` = 0.21), so 8 decimals for all |
| `boolean` | `BOOLEAN` | |
| `$ref: jet://schema/...Lookup`, inline `oneOf` | `VARCHAR` (code) | description through `CODE_LIST` |
| `$ref: jet://entity/...` | `VARCHAR` | suffix `_VERSION_ID`; typed in union views as well, because these are the join keys |
| local `$ref` (`#/$defs/...`) | resolved; its fields are typed like inline ones | |
| `title` | — | stored in `CONFIG_FIELD.TITLE` and emitted as the view column `COMMENT`, so business users see the Dutch label (`SUM_INSURED` → "Verzekerde som") |

Casts use plain `::`. The platform validates data against the schema, so a cast error means schema drift and should fail loudly rather than become a silent NULL.

**Materialisation** (see Q3): everything starts as views. `ENTITY_VERSION` and `ENTITY_ARRAY_ITEM` are the only objects that scan BRONZE and run `FLATTEN`, so they are the first to become dynamic tables if a view is too slow or too expensive. The typed views are thin projections and stay views.

> YOUR ANSWER (b) — GOLD model:

**Principles**

- **Star schema, conformed across products.** SILVER is per product, and the same business concept sits in different fields:

  | Concept | Hull caravan | bl055 |
  |---|---|---|
  | Insured amount | `articles[hull].sumInsured` | `coverage.insuredAmount` |
  | Premium | `netAnnualPremium` | `premium.netAnnualPremium` |
  | Status | `statusType = 'inForce'` | `status = 'ACTIVE'` |

  The schema cannot decide that these mean the same thing; that is a business decision. It lives in one small, hand-maintained table, `GOLD.PRODUCT_MAPPING`. The generator turns it into one `SELECT` per product and combines them with `UNION ALL`.
- **Dimensions keyed by version.** Contracts reference person and organization *versions*, so `DIM_RELATION` has one row per version. That is SCD type 2 for free from the platform. Each row also carries the entity key and the current name, so aggregations over time group by the entity, not by the version.
- **Policies only.** Draft versions and quotes (`controlData.applicationGoal = 'quote'`) are excluded.
- **Tables, rebuilt nightly** before the Qlik reload, with a fixed `REPORT_DATE`. Every Qlik app sees the same snapshot, and Qlik reads a few small tables instead of re-running the SILVER views. A view based on `SYSDATE()` would shift during the day.

**Objects and grain**

| Object | Kind | Grain | Used for |
|---|---|---|---|
| `GOLD.PRODUCT_MAPPING` | table, maintained by hand | product × gold column | Which SILVER field feeds which gold column, per product |
| `GOLD.STG_CONTRACT_VERSION` | generated view | one row per non-draft policy version, all products, conformed columns | Source of both contract facts |
| `GOLD.STG_COVERAGE_VERSION` | generated view | one row per coverage per contract version | Source of `FACT_COVERAGE` |
| `GOLD.FACT_CONTRACT` | table | **one row per contract**: its current version at `REPORT_DATE` | Portfolio overview, average coverages, top postal codes |
| `GOLD.FACT_COVERAGE` | table | **one row per coverage of the current contract version** | Coverage-level detail |
| `GOLD.FACT_CONTRACT_MONTH` | table | **one row per contract per month-end at which it was in force**, using the version in effect on that date | Premium per intermediary per month, trends |
| `GOLD.DIM_PRODUCT` | table | one row per product (configuration key) | Product name, business line |
| `GOLD.DIM_COVERAGE` | table | one row per product × coverage variant | Coverage name, ADN coverage code (conformed across products) |
| `GOLD.DIM_RELATION` | table | one row per person or organization version | Name, postal code |
| `GOLD.DIM_POLICYHOLDER`, `GOLD.DIM_INTERMEDIARY` | views on `DIM_RELATION` | same | Role-playing dimension: one view per role, each with its own clearly named columns |
| `GOLD.DIM_STATUS` | table | one row per product × status code | Description from `CODE_LIST`; conformed `STATUS_GROUP` (`inForce`, `ACTIVE` → `IN_FORCE`) |
| `GOLD.DIM_DATE` | table | one row per day | Months, month-ends |

**DDL (minimal)**

```sql
CREATE TABLE GOLD.PRODUCT_MAPPING (         -- key: PRODUCT_KEY, GOLD_COLUMN, DISCRIMINATOR
    PRODUCT_KEY             VARCHAR,        -- configuration key
    GOLD_COLUMN             VARCHAR,        -- 'NET_ANNUAL_PREMIUM', 'STATUS', 'COVERAGE_ARRAY', 'COVERAGE_INSURED_AMOUNT', ...
    FIELD_PATH              VARCHAR,        -- a FIELD_PATH or ARRAY_PATH from SILVER.CONFIG_FIELD; field names only, never SQL
    DISCRIMINATOR           VARCHAR         -- variant, when the field exists in one variant only
);

CREATE TABLE GOLD.FACT_CONTRACT (           -- grain: one row per contract, current version at REPORT_DATE
    CONTRACT_KEY            VARCHAR PRIMARY KEY,    -- entityId
    CONTRACT_VERSION_ID     VARCHAR,                -- → FACT_COVERAGE
    CONTRACT_NUMBER         VARCHAR,
    PRODUCT_KEY             VARCHAR,                -- → DIM_PRODUCT
    STATUS_KEY              VARCHAR,                -- → DIM_STATUS
    POLICYHOLDER_VERSION_ID VARCHAR,                -- → DIM_POLICYHOLDER
    INTERMEDIARY_VERSION_ID VARCHAR,                -- → DIM_INTERMEDIARY
    START_DATE              DATE,
    END_DATE                DATE,
    NET_ANNUAL_PREMIUM      NUMBER(38,2),
    INSURED_AMOUNT          NUMBER(38,2),           -- sum of FACT_COVERAGE.INSURED_AMOUNT
    NUMBER_OF_COVERAGES     NUMBER(38,0),           -- 0, not missing, for a contract without coverages
    RISK_POSTAL_CODE        VARCHAR,                -- only for products with an insured-object address (bl055)
    REPORT_DATE             DATE
);

CREATE TABLE GOLD.FACT_COVERAGE (           -- grain: one row per coverage of the current contract version
    CONTRACT_VERSION_ID     VARCHAR,                -- → FACT_CONTRACT
    COVERAGE_ITEM_PATH      VARCHAR,                -- 'articles[0]'; 'coverage' for a single coverage object (bl055)
    COVERAGE_KEY            VARCHAR,                -- → DIM_COVERAGE
    NET_PREMIUM             NUMBER(38,2),           -- netInvoiceAmount
    TAX_AMOUNT              NUMBER(38,2),
    INSURED_AMOUNT          NUMBER(38,2),           -- NULL for coverages without a sum insured (breakdownAssistance)
    DEDUCTIBLE_AMOUNT       NUMBER(38,2),
    PRIMARY KEY (CONTRACT_VERSION_ID, COVERAGE_ITEM_PATH)
);

CREATE TABLE GOLD.FACT_CONTRACT_MONTH (     -- grain: one row per contract per month-end at which it was in force
    MONTH_END_DATE          DATE,                   -- → DIM_DATE
    CONTRACT_KEY            VARCHAR,
    CONTRACT_VERSION_ID     VARCHAR,                -- version in effect on MONTH_END_DATE
    PRODUCT_KEY             VARCHAR,
    INTERMEDIARY_VERSION_ID VARCHAR,
    NET_ANNUAL_PREMIUM      NUMBER(38,2),
    MONTHLY_PREMIUM         NUMBER(38,2),           -- NET_ANNUAL_PREMIUM / 12
    PRIMARY KEY (MONTH_END_DATE, CONTRACT_KEY)
);

CREATE TABLE GOLD.DIM_RELATION (            -- grain: one row per person or organization version
    RELATION_VERSION_ID     VARCHAR PRIMARY KEY,
    RELATION_KEY            VARCHAR,                -- entityId: all versions of one person or organization
    RELATION_TYPE           VARCHAR,                -- 'PERSON' / 'ORGANIZATION'
    NAME                    VARCHAR,                -- on this version
    CURRENT_NAME            VARCHAR,                -- on the current version: label when grouping over time
    POSTAL_CODE             VARCHAR,                -- first address, upper case, no spaces ('1015CS')
    CITY                    VARCHAR
);

CREATE TABLE GOLD.DIM_COVERAGE (            -- built from the configuration, so a new variant exists before its first contract
    COVERAGE_KEY            VARCHAR PRIMARY KEY,    -- 'hullCaravanIntermediary|hull'
    PRODUCT_KEY             VARCHAR,
    COVERAGE_CODE           VARCHAR,                -- the variant's coverageCode const, e.g. '2002'
    COVERAGE_NAME           VARCHAR                 -- the variant's title, e.g. 'Casco'
);

CREATE TABLE GOLD.DIM_PRODUCT (
    PRODUCT_KEY             VARCHAR PRIMARY KEY,    -- configuration key
    PRODUCT_NAME            VARCHAR,                -- '022 - Casco caravan (intermediair)'
    BUSINESS_LINE           VARCHAR                 -- '022'
);
-- DIM_STATUS and DIM_DATE: see the table above
```

**`PRODUCT_MAPPING`, sample rows** (about 8 rows per product, so roughly 320 for 40 products)

| PRODUCT_KEY | GOLD_COLUMN | FIELD_PATH | DISCRIMINATOR |
|---|---|---|---|
| hullCaravanIntermediary | NET_ANNUAL_PREMIUM | `netAnnualPremium` | |
| hullCaravanIntermediary | STATUS | `statusType` | |
| hullCaravanIntermediary | POLICYHOLDER | `parties` | `policyHolder` |
| hullCaravanIntermediary | INTERMEDIARY | `parties` | `intermediary` |
| hullCaravanIntermediary | COVERAGE_ARRAY | `articles` | |
| hullCaravanIntermediary | COVERAGE_INSURED_AMOUNT | `articles.sumInsured` | `hull` |
| bl055 | NET_ANNUAL_PREMIUM | `premium.netAnnualPremium` | |
| bl055 | STATUS | `status` | |
| bl055 | COVERAGE_INSURED_AMOUNT | `coverage.insuredAmount` | |
| bl055 | PARENT_CONTRACT | `contract` | |

The generator checks every `FIELD_PATH` against `SILVER.CONFIG_FIELD`. A release that renames a mapped field therefore fails the build, instead of silently producing NULL premiums.

**How bl055 fits:**
- It gets its own mapping rows; no other change is needed.
- Its single `coverage` object becomes one coverage row (`COVERAGE_ITEM_PATH = 'coverage'`), so it counts as 1 coverage.
- It has no `parties`, so its policyholder and intermediary come from the contract version it references (`PARENT_CONTRACT`).
- Its insured-object address fills `RISK_POSTAL_CODE`. For property insurance, the risk location is what exposure reporting really needs.

**How `FACT_CONTRACT_MONTH` is built.** Each version is valid in `[VALID_FROM, VALID_TO)`, so every month-end falls inside exactly one version of a contract. The core is a range join with the calendar; `QUALIFY` is only a safety net in case versions overlap.

```sql
INSERT OVERWRITE INTO GOLD.FACT_CONTRACT_MONTH
SELECT
    d.DATE_KEY                              AS MONTH_END_DATE,
    v.CONTRACT_KEY,
    v.CONTRACT_VERSION_ID,
    v.PRODUCT_KEY,
    v.INTERMEDIARY_VERSION_ID,
    v.NET_ANNUAL_PREMIUM,
    v.NET_ANNUAL_PREMIUM / 12               AS MONTHLY_PREMIUM
FROM GOLD.STG_CONTRACT_VERSION AS v
INNER JOIN GOLD.DIM_DATE AS d
    ON  d.IS_MONTH_END
    AND d.DATE_KEY <= CURRENT_DATE()
    AND d.DATE_KEY >= v.VALID_FROM::DATE
    AND (v.VALID_TO IS NULL OR d.DATE_KEY < v.VALID_TO::DATE)
WHERE v.STATUS_GROUP = 'IN_FORCE'
QUALIFY ROW_NUMBER() OVER (PARTITION BY d.DATE_KEY, v.CONTRACT_KEY ORDER BY v.VERSION_TAG DESC) = 1;
```

**The three questions**

```sql
-- Total premium per intermediary per month
SELECT
    m.MONTH_END_DATE,
    i.INTERMEDIARY_KEY,
    MAX(i.CURRENT_NAME)                     AS INTERMEDIARY_NAME,
    SUM(m.MONTHLY_PREMIUM)                  AS PREMIUM
FROM GOLD.FACT_CONTRACT_MONTH AS m
LEFT JOIN GOLD.DIM_INTERMEDIARY AS i
    ON i.INTERMEDIARY_VERSION_ID = m.INTERMEDIARY_VERSION_ID
GROUP BY
    m.MONTH_END_DATE,
    i.INTERMEDIARY_KEY;

-- Average number of coverages per contract by product
SELECT
    p.PRODUCT_NAME,
    AVG(c.NUMBER_OF_COVERAGES)              AS AVG_COVERAGES_PER_CONTRACT
FROM GOLD.FACT_CONTRACT AS c
INNER JOIN GOLD.DIM_PRODUCT AS p
    ON p.PRODUCT_KEY = c.PRODUCT_KEY
GROUP BY p.PRODUCT_NAME;

-- Top 10 postal codes by insured amount
SELECT
    ph.POSTAL_CODE,                                     -- NULL = person version not loaded yet, shown on purpose
    SUM(c.INSURED_AMOUNT)                   AS INSURED_AMOUNT
FROM GOLD.FACT_CONTRACT AS c
LEFT JOIN GOLD.DIM_POLICYHOLDER AS ph
    ON ph.POLICYHOLDER_VERSION_ID = c.POLICYHOLDER_VERSION_ID
GROUP BY ph.POSTAL_CODE
ORDER BY INSURED_AMOUNT DESC
LIMIT 10;
```

**Assumptions**

- **Postal code join.** `FACT_CONTRACT.POLICYHOLDER_VERSION_ID` → `SILVER.PERSONS.VERSION_ID` (or `SILVER.ORGANIZATIONS` when `partyType = 'ORGANIZATION'`) → `SILVER.PERSONS_ADDRESSES` on `VERSION_ID` with `ITEM_INDEX = 0`.
  - The first address is taken as the primary one. If the persons schema has an address type, filter on that instead.
  - The join is by version, so it returns the address the contract was issued with, not the person's latest address.
- **Premium per month** is the net annual premium of the version in force at each month-end, divided by 12. Because the version is taken per month-end rather than today's version, a mid-year premium change or a transfer to another intermediary lands in the right month.
- **Two premium figures.** Contract premium is the root `netAnnualPremium` (486.2 in the sample). It does not reconcile with the sum of the coverages' `netInvoiceAmount` (396.9). Both are available (`FACT_CONTRACT` and `FACT_COVERAGE`), and the business has to confirm which one is leading.
- **Insured amount.** The contract's insured amount sums only the coverages the mapping marks as carrying a sum insured. For hull caravan that is only `hull`, so there is no double counting when several coverages insure the same object.

> YOUR ANSWER (c) — query:

```sql
SELECT
    hc.ENTITY_KEY                           AS CONTRACT_KEY,
    hc.CONTRACT_NUMBER,
    hc.NET_ANNUAL_PREMIUM,
    COUNT(hca.ITEM_PATH)                    AS NUMBER_OF_ARTICLES   -- 0 for a contract without articles
FROM SILVER.HULLCARAVANINTERMEDIARY AS hc
LEFT JOIN SILVER.HULLCARAVANINTERMEDIARY_ARTICLES AS hca
    ON hca.VERSION_ID = hc.VERSION_ID
WHERE hc.IS_CURRENT
GROUP BY
    hc.ENTITY_KEY,
    hc.CONTRACT_NUMBER,
    hc.NET_ANNUAL_PREMIUM;
```

- Articles belong to a version, so the join is on `VERSION_ID`. Filtering the contract side on `IS_CURRENT` therefore counts only the current version's articles.
- On the sample: `ctr-2041 | CAR-2026-004417 | 486.2 | 3`.
- SILVER is per product, so this query covers one product. Across all products, the same two numbers are `GOLD.FACT_CONTRACT.NET_ANNUAL_PREMIUM` and `NUMBER_OF_COVERAGES`.

---

## Question 2 — Polymorphic arrays (~10 min)

A contract has an `articles` array whose items are a discriminated union: the item schema is an `anyOf` with about 40 variants (for example `hullVessel`, `breakdownAssistance`, `hullTrailer`), each with a `_discriminator` constant and its own set of fields. Fully typing all variants side by side would give a table of about 700 columns.

**How would you model `articles` in the layer above BRONZE?** Choose between (a) one table per variant, (b) one wide merged table with NULLs plus a discriminator column, (c) one table with the shared columns, a discriminator column and a VARIANT column for the variant-specific fields, or something else. Defend your choice for a BI/Qlik consumer and for schema evolution (a new variant is added next quarter).

Answer in 2–4 sentences plus, if useful, a small table; name one concrete thing from your own experience.

> YOUR ANSWER:

I choose (c) as the stored structure and generate (a) on top of it as views.
- `HULLCARAVANINTERMEDIARY_ARTICLES` holds the fields every variant shares (coverage code, net premium, tax), the discriminator, and a `VARIANT_FIELDS` column with the rest.
- The generator adds one fully typed view per variant, e.g. `..._ARTICLES__HULL` with `SUM_INSURED`.

A BI user gets one table for portfolio-wide coverage totals and real typed columns for variant-specific analysis, and never writes a JSON path. A new variant next quarter appears in the union view the day it ships, with its own fields in `VARIANT_FIELDS`; the next generator run adds its typed view, which is a `CREATE VIEW` with no `ALTER TABLE` and no backfill.

From my own experience: in our dbt project on Snowflake, a new column in an incremental model meant a `--full-refresh`. `on_schema_change = 'append_new_columns'` adds the column but leaves it NULL for rows already loaded. Renamed source columns broke every model that selected the old name. Views over JSON avoid both problems: there is no stored data to backfill, and a rename shows up in one place, as a failed GOLD mapping check (see Q1b).

| Option | For the BI consumer | When a new variant is added next quarter |
|---|---|---|
| (a) one table per variant | typed, but about 40 tables to union for "all coverages" | a new table plus a backfill in every customer database |
| (b) one wide table | one table, but about 700 mostly-NULL columns | `ALTER TABLE` plus a backfill |
| (c) shared columns + VARIANT | one table, but variant fields need JSON paths | nothing to do |
| **Chosen: (c) + generated per-variant views** | union view for totals, typed views for detail | rows appear immediately; the next generator run adds one view, with no data migration |

---

## Question 3 — Design scenarios for the layer above BRONZE (~15 min)

Candidate designs for the layer above the append-only `BRONZE.ENTITIES_RAW` table (`LOADED_AT`, `ENTITY_TYPE`, `ENTITY_KEY`, `VERSION_ID`, `PAYLOAD VARIANT`; one row per loaded entity version, see the DDL at the top of this file) can be described on two axes. The setting: a nightly BI load, about 40 entity types (products) whose configurations change with every release, and 80–240 customer databases that must all run the same generated code.

| Axis | Options |
|---|---|
| **1. Materialisation** | (i) views · (ii) dynamic tables · (iii) physical tables |
| **2. Decomposition** | (A) **fully typed** — every entity type and nested array becomes its own typed table · (B) **schema-agnostic** — a small fixed set of structural tables, business fields kept as JSON · (C) **mixed** — (B) plus a limited set of typed columns for the fields reporting needs most |

A scenario is one option from each axis, for example "(ii) + (A)".

**Name the TWO scenarios you consider most logical for this platform and give the main pros and cons of each** (cost, schema drift, consumer friendliness for Qlik, multi-tenant maintainability). Which would you build first as a pilot, and what would you measure? A short table plus 3–5 sentences is fine.

> YOUR ANSWER:

The two scenarios are **(i) views + (C)** and **(ii) dynamic tables + (C)**. Both use the same decomposition, which is my Q1 design, and the same SQL; they differ only in whether tier 1 (`ENTITY_VERSION`, `ENTITY_ARRAY_ITEM`) is stored.

| | (i) views + (C): pilot | (ii) dynamic tables + (C): next step |
|---|---|---|
| **Cost** | No storage or refresh cost. Every read re-deduplicates and re-flattens all of BRONZE, which only grows. | Storage plus refresh compute. Incremental refresh reads only new BRONZE rows (append-only fits this well), so reads are cheap. |
| **Schema drift** | Best: a release is `CREATE OR REPLACE VIEW`, with nothing to migrate. | Still good: tier-1 columns never change, so the dynamic tables survive every release. Drift stays in the JSON and the typed views. |
| **Qlik friendliness** | Same typed views. Slow if queried directly, so the GOLD tables sit in between. | Same typed views, fast. |
| **Multi-tenant maintenance** | Stateless: deploying means running DDL. Nothing to refresh, backfill or repair. | Refresh schedules and refresh failures to monitor in 80–240 databases. `IS_CURRENT` has to move into a view on top, because `SYSDATE()` prevents incremental refresh. |

**Why not the others:**
- **(A), in any materialisation:** about 40 products × about 7 typed objects per customer, all changing with every release.
- **(iii):** physical tables mean writing our own `MERGE`/watermark code for what dynamic tables do declaratively.

**Pilot: (i) + (C).** It is the cheapest to build and to throw away, and its SQL becomes the body of the dynamic tables unchanged if we need to promote. I would run it on three customers: the smallest, the largest, and the one with the most products. Measurements:
- **Execution time:** the nightly GOLD build and the Qlik reload, per customer.
- **Cost:** credits per night per customer, attributed through a `QUERY_TAG` per database in `ACCOUNT_USAGE.QUERY_HISTORY`.
- **Scalability:** how runtime and credits grow with the number of BRONZE rows, extrapolated to the largest customer.
- **Cardinality:** rows per object, BRONZE rows per distinct version (the re-load ratio), and array items per version, reconciled against counts taken directly from BRONZE.
- **Robustness:** failed builds per configuration release (generator or mapping check), and the time to recover.
- **Data quality:**
  - exactly one current version per contract;
  - the share of `*_VERSION_ID` references that resolve to a loaded version;
  - the number of `ENTITY_EXTRA_FIELD` rows per release.

**Decision rule:** promote `ENTITY_VERSION` and `ENTITY_ARRAY_ITEM` to dynamic tables for the customers where the views no longer fit the nightly window. The typed views and GOLD stay unchanged.
