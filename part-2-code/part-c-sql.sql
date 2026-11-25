-- ============================================================
-- Part C — SQL (~15 min)
-- ============================================================
-- Two questions. Answer each by writing the SQL AND a brief
-- comment explaining your approach (1-3 lines max above the query).
-- You do not need a running Snowflake; Snowflake dialect preferred,
-- ANSI is fine.
--
-- Q1 runs against the append-only BRONZE table used throughout:
--
--   BRONZE.ENTITIES_RAW (LOADED_AT, ENTITY_TYPE, ENTITY_KEY,
--                        VERSION_ID, PAYLOAD VARIANT)
--
-- where PAYLOAD:validFrom and PAYLOAD:validTo are the validity
-- bounds of the version (validTo is null for an open version) and
-- PAYLOAD:data holds the entity fields.
-- ============================================================


-- ─── QUESTION 1: Data quality on BRONZE (~5 min) ───────────
-- One query: VERSION_IDs that were loaded more than once with
-- DIFFERENT PAYLOAD:validTo values (a version that was closed after
-- it was first loaded, so the loader appended it again). Return the
-- entity type, the version, the number of loads and the distinct
-- validTo values, including the open (null) one.
--
-- YOUR ANSWER:
-- Group per version; more than one distinct validTo means the version was closed after its first load.
-- validTo is normalised through TIMESTAMP_NTZ (the samples use two string formats), and an open validTo
-- becomes 'open' because COUNT(DISTINCT) and ARRAY_AGG skip NULL. On the Part A data: v-002-a, v-043-a.
WITH loads AS (
    SELECT
        r.ENTITY_TYPE,
        r.VERSION_ID,
        r.LOADED_AT,
        COALESCE(TO_VARCHAR(r.PAYLOAD:validTo::TIMESTAMP_NTZ, 'YYYY-MM-DD HH24:MI:SS'), 'open')     AS VALID_TO
    FROM BRONZE.ENTITIES_RAW AS r
)
SELECT
    l.ENTITY_TYPE,
    l.VERSION_ID,
    COUNT(*)                                                            AS LOAD_COUNT,
    ARRAY_AGG(DISTINCT l.VALID_TO) WITHIN GROUP (ORDER BY l.VALID_TO)   AS VALID_TO_VALUES,
    MIN(l.LOADED_AT)                                                    AS FIRST_LOADED_AT,
    MAX(l.LOADED_AT)                                                    AS LAST_LOADED_AT
FROM loads AS l
GROUP BY
    l.ENTITY_TYPE,
    l.VERSION_ID
HAVING COUNT(DISTINCT l.VALID_TO) > 1
ORDER BY
    l.ENTITY_TYPE,
    l.VERSION_ID;


-- ─── QUESTION 2: Flexible Attributes (EAV) (~10 min) ───────
-- Different insurance customers (tenants) need custom fields
-- on persons and contracts that vary per customer. Examples:
--   - Car registration number (person-level, only for motor insurers)
--   - Roof type (contract-level, only for property insurers)
--   - Loyalty score (person-level, only for some customers)
--
-- These fields are NOT in the schema: they are tenant-specific,
-- can be added at any time by any customer, and do not apply to
-- every customer.
--
-- Assume your person / contract structures from Part 1 exist;
-- refer to them by the names and keys you used there.
--
-- a) Design a data model to store these flexible attributes
--    centrally, linked to any entity. Provide CREATE TABLE DDL.
--
-- b) Write a query that returns all persons with their custom
--    attributes pivoted as columns (one row per person, custom
--    fields as additional columns).
--
-- c) What are the trade-offs of your approach? (2-3 sentences)
--
-- YOUR ANSWER (a) — DDL:
-- Catalogue plus value table, linked to any entity through VERSION_ID (SILVER.ENTITY_VERSION from Part 1),
-- so values have history like everything else. One database per customer, so no tenant column is needed.
CREATE TABLE SILVER.CUSTOM_ATTRIBUTE (
    ATTRIBUTE_ID        NUMBER(38,0) IDENTITY PRIMARY KEY,
    ENTITY_TYPE         VARCHAR NOT NULL,       -- 'persons', 'bl055', ...: the configuration key
    ATTRIBUTE_PATH      VARCHAR NOT NULL,       -- key in PAYLOAD:data, e.g. 'loyaltyScore'
    ATTRIBUTE_NAME      VARCHAR NOT NULL,       -- column name when pivoted, e.g. 'LOYALTY_SCORE'
    DATA_TYPE           VARCHAR NOT NULL,       -- 'VARCHAR', 'NUMBER(38,8)', 'DATE', 'BOOLEAN'
    DESCRIPTION         VARCHAR,
    REGISTERED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UNIQUE (ENTITY_TYPE, ATTRIBUTE_PATH)
);

CREATE TABLE SILVER.ENTITY_ATTRIBUTE_VALUE (
    VERSION_ID          VARCHAR NOT NULL,       -- -> SILVER.ENTITY_VERSION, a person or a contract version
    ATTRIBUTE_ID        NUMBER(38,0) NOT NULL,  -- -> SILVER.CUSTOM_ATTRIBUTE
    VALUE               VARIANT,                -- original JSON value; typed via DATA_TYPE when read
    LOADED_AT           TIMESTAMP_NTZ,
    PRIMARY KEY (VERSION_ID, ATTRIBUTE_ID)
);

-- Filled nightly from Part 1's ENTITY_EXTRA_FIELD (payload fields that are not in the schema). Only registered
-- attributes are copied; unregistered extra fields remain a drift signal. Version data never changes, so insert-only.
INSERT INTO SILVER.ENTITY_ATTRIBUTE_VALUE (VERSION_ID, ATTRIBUTE_ID, VALUE, LOADED_AT)
SELECT
    x.VERSION_ID,
    a.ATTRIBUTE_ID,
    x.FIELD_VALUE,
    CURRENT_TIMESTAMP()
FROM SILVER.ENTITY_EXTRA_FIELD AS x
INNER JOIN SILVER.CUSTOM_ATTRIBUTE AS a
    ON  a.ENTITY_TYPE    = x.ENTITY_TYPE
    AND a.ATTRIBUTE_PATH = x.FIELD_PATH
WHERE NOT EXISTS (
    SELECT 1
    FROM SILVER.ENTITY_ATTRIBUTE_VALUE AS v
    WHERE v.VERSION_ID   = x.VERSION_ID
      AND v.ATTRIBUTE_ID = a.ATTRIBUTE_ID
);


-- YOUR ANSWER (b) — query:
-- One row per person (current version), one column per registered person attribute. The MAX(IFF(...)) list
-- is generated from SILVER.CUSTOM_ATTRIBUTE per customer, like the typed views; two attributes shown.
SELECT
    p.ENTITY_KEY                                                                        AS PERSON_KEY,
    p.VERSION_ID,
    p.FIRST_NAME,
    p.LAST_NAME,
    MAX(IFF(a.ATTRIBUTE_NAME = 'CAR_REGISTRATION_NUMBER', v.VALUE::VARCHAR, NULL))       AS CAR_REGISTRATION_NUMBER,
    MAX(IFF(a.ATTRIBUTE_NAME = 'LOYALTY_SCORE', v.VALUE::VARCHAR, NULL))::NUMBER(38,8)   AS LOYALTY_SCORE
FROM SILVER.PERSONS AS p
LEFT JOIN SILVER.ENTITY_ATTRIBUTE_VALUE AS v
    ON v.VERSION_ID = p.VERSION_ID
LEFT JOIN SILVER.CUSTOM_ATTRIBUTE AS a
    ON a.ATTRIBUTE_ID = v.ATTRIBUTE_ID
WHERE p.IS_CURRENT
GROUP BY
    p.ENTITY_KEY,
    p.VERSION_ID,
    p.FIRST_NAME,
    p.LAST_NAME;


-- YOUR ANSWER (c) — trade-offs:
-- + A customer adds a field with one catalogue row: no DDL, no generator change, the same two tables in all
--   80-240 databases, and values follow the entity versions, so history comes for free.
-- - Storage is untyped (VARIANT, cast on read), Snowflake does not enforce the keys (the insert's NOT EXISTS
--   does), and the pivot needs one generated column per attribute and customer: fine for a handful of fields,
--   slow and unreadable for hundreds.
-- - When the same custom field shows up at many customers, promote it into the schema so it becomes a typed column.

