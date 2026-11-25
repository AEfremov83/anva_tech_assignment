# Part D — Production questions (~20 min)

Answer each of the 6 questions in **2-4 sentences**, and **name one concrete thing from your own experience per answer where you can**. We value clear, specific reasoning over length. Pseudocode, a short table or bullet points are fine.

---

## Question 1: Idempotency

The bronze loader from Part A appends rows and deduplicates on (VERSION_ID, validTo). BRONZE itself is append-only by design, so a re-run can still legitimately add rows (a closed version, a late correction, a re-load after a fix).

**What does "idempotent" mean for this pipeline, and where do you enforce it?** Consider the loader (re-runs, partial failures halfway through an entity type) and whatever you designed above BRONZE in Part 1: how does that layer stay deterministic regardless of how many times, and in which order, bronze was loaded?

> YOUR ANSWER:

---

## Question 2: Incremental Loading

The API only offers keyset pagination over all entities of a type (`/entity/key/{type}/keyset?size=100&after=<token>`). There is no `modifiedSince` parameter. Today every run fetches everything and appends what is new to the BRONZE layer.

**How would you make ingestion incremental and cheaper?** What would you ask the API or product team to add (for example `modifiedSince`, a change feed or webhook, an event stream), and what are the trade-offs of polling vs. push vs. CDC for a platform that serves up to 240 tenants? How do you detect deletes?

> YOUR ANSWER:

---

## Question 3: Error Handling Trade-offs

The loader in Part A has a `try/except` per entity type that logs and continues, retries transient errors with backoff and gives up on permanent ones. A malformed record inside a page, however, would still abort the whole entity type or be skipped silently, depending on where it fails.

**What error handling strategy would you implement for a production pipeline?** Consider: should one bad record block the entire batch? How do you surface errors for investigation, and how do you make a partially failed run safe to re-run?

> YOUR ANSWER:

---

## Question 4: Schema Drift

A new version of the `persons` configuration (v2.0) adds a nested array `nationalities` (objects with `countryCode` and `since`), removes the `age` field, and changes `addresses[].houseLetter` from string to integer. BRONZE keeps receiving both shapes: older versions with `age` and a string `houseLetter`, newer ones with `nationalities` and an integer `houseLetter`.

**What happens to whatever you designed above BRONZE in Part 1, and how do you roll the change out safely** across all customer databases? Name what breaks, what silently goes missing, and what you would automate.

> YOUR ANSWER:

---

## Question 5: AI Collaboration

Suppose the AI produced your Part B generator's SQL for `articles.clauses`: a chain of two flattens, typed casts, a version rule, and it looks correct at first glance.

**What is your process for validating AI-generated SQL like this before deploying it?** What are the specific risks you check for, and which of them would the sample data in `data/` let you check?

> YOUR ANSWER:

---

## Question 6: Reflection on Part 1

Part 2 made you implement your Part 1 design and showed how the API pages, versions and configurations behave: keyset pagination, versions that get closed after they were loaded, polymorphic arrays with `_discriminator`, local `$defs` references, arrays nested inside arrays and behind objects.

**Would you change anything in your Part 1 design now? What, and why (or why not)?** Do not edit Part 1; answer here.

> YOUR ANSWER:
