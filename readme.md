# Data Engineer — Technical Assessment (take-home)

**Duration:** about 3.5 to 4 hours, in two sittings (budgets below add up to 210 minutes)
**Tools allowed:** any editor or IDE, Python 3.9+, internet access, AI assistants (see "Working with AI" below)

---

## How this works

The assessment has two parts in this package and a review discussion afterwards:

1. **Part 1 — Architecture (about 75 minutes).** Three design questions about turning ANVA 6 entity JSON into an analytical model, plus a high-level ERD of your model. Deliberately code-free: we want to see your own architectural thinking before any code shapes it.
2. **Part 2 — Code (about 135 minutes).** Python and Snowflake SQL: a bronze loader to fix, a silver generator that implements your own Part 1 design for the same contract, two SQL questions and six production questions.
3. **Review discussion.** A 60-minute discussion of your submission afterwards (see "What happens next").

## Order rule

**Do Part 1 before you open Part 2, and do not revise your Part 1 answers afterwards.** Part 2 ends with a reflection question where you can say what you would change and why. We read Part 1 as your first thinking and the reflection as your second; both are valuable, a rewritten Part 1 is not.

---

## Context: what is given

ANVA 6 is a configuration-driven insurance platform. It exposes its **entity schemas** (JSON Schema-like definitions of persons, organizations, contracts, and so on) and its **entity data** through the **JET Engine API**. Because the platform is configuration-driven, the shape of the data is not fixed: it is described by the schemas, and the data platform has to follow those schemas rather than a hand-written model.

- The data platform is **Snowflake-native**; there is no separate ETL tool.
- Each customer has its **own Snowflake database**.
- Raw API responses (schemas and entity data) land **unchanged** in an append-only **BRONZE** layer, stored as JSON in VARIANT columns. Nothing is ever updated or deleted there.
- Every entity type (persons, organizations, each insurance product) has a **configuration**: a row with its key, name, states and the JSON schema of its data. The same key is the entity type in the API and in BRONZE.
- Entities are **versioned**: every change to a person, organization or contract produces a new version with its own `versionId`, and the API returns each version as a wrapper object (`configKey`, `entityId`, `versionId`, `createdAt`, `validFrom`, `validTo`, `currentState`, `data`), paged with keyset pagination.

What is **not** given: how anything above BRONZE should look. That is the subject of Part 1, and Part 2 makes you implement it for one entity.

You work locally with the provided sample data; no Snowflake account is needed.

```
JET Engine API                          Snowflake (one database per customer)
──────────────                          ────────────────────────────────────
/entity-schema/key/{key}/effective   →    BRONZE.ANVA6_CONFIGURATIONS   (one configuration row per entity type: exactly
                                                                        the rows in data/schemas.json that Part B reads)
/entity/key/{key}/keyset?after=…     →    BRONZE.ENTITIES_RAW           (Part A loads this; B and C query it)
```

---

## Provided files

```
take-home/
├── readme.md                          ← you are here
├── notes.md                           ← your decision log (mandatory, template provided)
├── part-1-architecture.md             ← Part 1: three architecture questions, answer in the file
├── part-1-erd.md                      ← Part 1: your high-level ERD (Mermaid, template provided)
├── data/
│   ├── anva6-contract-sample.json     ← Part 1: a real-shaped ANVA 6 contract (hull caravan), fictitious values
│   ├── hull-caravan-configuration.json ← Part 1: its configuration row, trimmed (Part 2 reads its copy in schemas.json)
│   ├── bl055-opstal-entity.json       ← Part 1: a second, simpler product as returned by the API
│   ├── bl055-opstal-configuration.json ← Part 1: its configuration row (Part 2 reads its copy in schemas.json)
│   ├── schemas.json                   ← Part 2: 5 configuration rows (persons, organizations, a countries code list,
│   │                                             the hull-caravan contract, bl055)
│   ├── api-pages.json                 ← Part 2: simulated keyset API pages (persons, organizations, hull-caravan contracts)
│   └── bronze-existing.json           ← Part 2: rows already present in BRONZE before the run
└── part-2-code/
    ├── part-a-bronze-loader.py        ← Part A: buggy bronze loader
    ├── part-b-silver-generator.py     ← Part B: schema walker + SQL generator for your Part 1 design
    ├── part-c-sql.sql                 ← Part C: data quality on BRONZE, flexible attributes
    └── part-d-production.md           ← Part D: production questions, ends with the reflection
```

---

## Working with AI

AI use is expected and welcome in this assessment. We assess **you**, not the model: your judgment, your priorities, and your ability to explain and defend what you hand in. The rules:

1. **Use any tool you like** — IDE assistants, chat models, search, documentation.
2. **Everything you submit you must be able to explain and defend in the review discussion**, line by line if asked. If you cannot explain a piece of code or an answer, leave it out.
3. **`notes.md` is mandatory and graded.** It is a short decision log per question and per part: what you did, what the AI proposed that you rejected or changed and why, how you verified the result, and what doubts remain. Ten minutes per part, bullet points are fine, specifics beat prose. It is scored on concreteness.
4. **The review discussion is about your own submission** (see "What happens next"): make sure you own what you submit.

Questions you should expect in the discussion include:
- "Walk me through how you debugged this"
- "Why did you choose this approach over X?"
- "What would break if we changed Y?"

---

## Part 1 — Architecture (~75 min)

Open `part-1-architecture.md` and answer in the file, under each question. DDL, a table list, bullet points or a short table are all fine; keep DDL minimal (keys plus a few representative columns, `...` is allowed). Specific and opinionated beats complete and vague. You work with four sample files: the contract sample (`data/anva6-contract-sample.json`), its configuration (`data/hull-caravan-configuration.json`), and the `bl055` pair (`data/bl055-opstal-entity.json`, `data/bl055-opstal-configuration.json`), a second product that shows whether your model generalises. Q1 also asks for a high-level ERD of your model as a Mermaid diagram in `part-1-erd.md` (template provided; readable beats complete).

| Question | Topic | Budget |
|---|---|---|
| Q1 | Medallion modelling from the ANVA 6 contract JSON: the layer above BRONZE, a high-level ERD, a reporting model for Qlik, one query | ~40 min |
| Q2 | Modelling polymorphic arrays (discriminated unions) | ~10 min |
| Q3 | Comparing design scenarios for the layer above BRONZE | ~15 min |
| — | `notes.md`, Part 1 section | ~10 min |

Remember the order rule: finish Part 1, then open Part 2, and leave Part 1 as it is.

---

## Part 2 — Code (~135 min)

### Part A — Bronze loader: code review & bug fixing (~30 min)

Open `part-2-code/part-a-bronze-loader.py`. It simulates the loader that pages through the JET Engine API and appends entity versions to BRONZE. The API and the bronze table are faked from the files in `data/`, so it runs standalone. A junior developer wrote it and it contains **at least six bugs or design issues**. The loader rules it should implement are in the module docstring.

**Your task:**
1. Run it: `python3 part-2-code/part-a-bronze-loader.py` and read the summary it prints
2. Find and fix the bugs; mark each fix with an inline `# FIX:` comment
3. In `notes.md`, **rank the bugs by production impact** and state for each the **concrete symptom in BRONZE** (which rows would be missing, duplicated or wrong, what an operator would see in the logs)

**We look for:** prioritisation and symptom reasoning — which bug matters most and why, and what it does to the data — rather than the number of bugs found. The summary after your fixes should be internally consistent with the loader rules; check it against the fixtures.

### Part B — Silver generator: make your Part 1 design executable (~60 min)

Open `part-2-code/part-b-silver-generator.py`. In Part 1 you designed the layer above BRONZE. Here you make that design executable for one entity, the same contract you modelled in Part 1: this generator reads the configuration rows in `data/schemas.json`, discovers the repeating structures in all of them, and emits the Snowflake SQL that implements **your** silver design for the hull-caravan configuration (`HULLCARAVANINTERMEDIARY`). Whether you chose fully typed tables, a schema-agnostic structure, a mix, or something else, the SQL must follow your Part 1 answer. The walker is graded on fixed expectations; the generator on consistency with your Part 1.

**Your task:**
1. Implement TODO 1 through TODO 4, the schema walker (resolve local `$ref`s, merge `anyOf` variants, walk the properties, run it for all schemas). Run it: `python3 part-2-code/part-b-silver-generator.py` and check the printed array paths and totals against `data/schemas.json` by hand: every array of objects, including the ones nested inside other arrays or behind objects and `$defs`, must appear exactly once.
2. Implement TODO 5, `generate_silver_sql`: the Snowflake statements for the hull-caravan configuration that implement your Part 1 design, reading from `BRONZE.ENTITIES_RAW`: the root structure plus **at least one nested array** (more is optional). The hard requirements are in the docstring: at least one runnable SELECT that reads nested array items from `BRONZE.ENTITIES_RAW.PAYLOAD` with typed columns; an explicit version rule based on the envelope fields (BRONZE is append-only and a version is appended again when its `validTo` changed, so the most recently loaded row is not necessarily the current version); the object type and the polymorphism handling from your Part 1.
3. Implement TODO 6, `run_tests()`, with **at least three tests using plain `assert`** (no external packages). At least two must cover **edge cases** of the walker, built from inline schema fragments. **Which cases you choose tells us what you understood.**
4. In `notes.md`, paste the generated SQL for `articles.clauses` (or the array you chose) and explain in three lines how it reflects your Part 1 design.

**We look for:** recursive thinking and careful handling of references and polymorphic items in the walker; in the generator, SQL that is consistent with what you wrote in Part 1 (object type, version rule, decomposition, discriminator handling) and that would run on Snowflake.

### Part C — SQL (~15 min)

Open `part-2-code/part-c-sql.sql`. Two questions.

- **Q1 (~5 min)** — *Data quality on BRONZE.* One query: versions loaded more than once with a changed `validTo`.
- **Q2 (~10 min)** — *Flexible attributes (EAV).* Tenant-specific fields that are not part of the schema, linked to the person and contract structures you designed in Part 1.

### Part D — Production questions (~20 min)

Open `part-2-code/part-d-production.md`. Six short questions: idempotency, incremental loading against an API without change tracking, error handling, schema drift, working with AI, and a reflection on your Part 1 design now that you have implemented it and seen the data.

**Keep answers to 2-4 sentences each, and name one concrete thing from your own experience per answer where you can.** Specific and opinionated beats complete and vague.

### notes.md, Part 2 section (~10 min)

One block per part: what you did, what the AI proposed that you rejected or changed and why, how you verified the result, and open doubts. Part A has slots for the bug ranking; Part B has a slot for the generated SQL. It is mandatory and graded on concreteness: "asked the AI for the retry loop, it retried on 4xx as well, changed the exception class and checked the claims type now fails once" scores; "used AI as a sounding board" does not.

---

## Submission

Return, zipped or as a git repository:

- `part-1-architecture.md` with your answers (unchanged after you opened Part 2)
- `part-1-erd.md` with your ERD (same rule)
- `part-2-code/part-a-bronze-loader.py` (fixed, with your `# FIX:` comments)
- `part-2-code/part-b-silver-generator.py` (TODO 1–6 implemented)
- `part-2-code/part-c-sql.sql`
- `part-2-code/part-d-production.md`
- `notes.md`

## What happens next

Within a week after submission we hold a 60-minute review discussion of your assessment with two interviewers. It is about your own work, nothing new to build: you walk us through your Part 1 model (ERD, silver, gold) and defend your choices; you walk us through your Part B generator and make one small change to your own code without AI; we discuss your Part A bug ranking and one debugging case on your own SQL; and we go through two of your Part D answers and your reflection. Please have your submission open and your screen ready to share.

Good luck!
