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



-- YOUR ANSWER (b) — query:



-- YOUR ANSWER (c) — trade-offs:


