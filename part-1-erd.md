# Part 1 — High-level ERD

Replace the placeholder diagram below with the ERD of your silver model from Q1 (a); gold entities are optional. Readable beats complete: show the main entities, their keys and the relations with cardinalities, and keep it to what fits on one screen. You do not need every table or every column. Any Markdown viewer with Mermaid support renders it (GitHub, VS Code preview, mermaid.live).

```mermaid
erDiagram
    %% Tier 1: structural, schema-agnostic, identical in every customer database
    ENTITY_VERSION ||--o{ ENTITY_ARRAY_ITEM : "array items, any depth"
    ENTITY_ARRAY_ITEM |o--o{ ENTITY_ARRAY_ITEM : "parent item (nested arrays)"
    ENTITY_VERSION ||--o{ ENTITY_EXTRA_FIELD : "fields not in schema"

    %% Tier 2: typed views generated per entity type (HCI_ = HULLCARAVANINTERMEDIARY_)
    ENTITY_VERSION ||--o| HULLCARAVANINTERMEDIARY : "typed view of"
    ENTITY_VERSION ||--o| BL055 : "typed view of"
    ENTITY_VERSION ||--o| PERSONS : "typed view of"
    ENTITY_VERSION ||--o| ORGANIZATIONS : "typed view of"
    HULLCARAVANINTERMEDIARY ||--o{ HCI_PARTIES : "parties[]"
    HULLCARAVANINTERMEDIARY ||--o{ HCI_ARTICLES : "articles[]"
    HCI_ARTICLES ||--o{ HCI_ARTICLES_CLAUSES : "clauses[] (hull only)"
    PERSONS ||--o{ PERSONS_ADDRESSES : "addresses[]"
    HCI_PARTIES }o--o| PERSONS : "PERSON_VERSION_ID (by version)"
    HCI_PARTIES }o--o| ORGANIZATIONS : "ORGANIZATION_VERSION_ID (by version)"
    BL055 }o--o| ENTITY_VERSION : "CONTRACT_VERSION_ID (by version)"

    ENTITY_VERSION {
        varchar VERSION_ID PK
        varchar ENTITY_TYPE
        varchar ENTITY_KEY
        number VERSION_TAG
        timestamp VALID_FROM
        timestamp VALID_TO
        boolean IS_CURRENT
        variant DATA
    }
    ENTITY_ARRAY_ITEM {
        varchar VERSION_ID PK, FK
        varchar ITEM_PATH PK
        varchar ARRAY_PATH
        varchar PARENT_ITEM_PATH FK
        varchar DISCRIMINATOR
        variant ITEM
    }
    ENTITY_EXTRA_FIELD {
        varchar VERSION_ID PK, FK
        varchar FIELD_PATH PK
        variant FIELD_VALUE
    }
    HULLCARAVANINTERMEDIARY {
        varchar VERSION_ID PK, FK
        varchar ENTITY_KEY
        boolean IS_CURRENT
        varchar CONTRACT_NUMBER
        number NET_ANNUAL_PREMIUM
        varchar PRODUCT_INFORMATION__PRODUCT_CODE
    }
    HCI_PARTIES {
        varchar VERSION_ID PK, FK
        varchar ITEM_PATH PK
        varchar DISCRIMINATOR
        varchar PERSON_VERSION_ID FK
        varchar ORGANIZATION_VERSION_ID FK
    }
    HCI_ARTICLES {
        varchar VERSION_ID PK, FK
        varchar ITEM_PATH PK
        varchar DISCRIMINATOR
        varchar COVERAGE_CODE
        number NET_INVOICE_AMOUNT
        variant VARIANT_FIELDS
    }
    HCI_ARTICLES_CLAUSES {
        varchar VERSION_ID PK, FK
        varchar ITEM_PATH PK
        varchar PARENT_ITEM_PATH FK
        varchar NUMBER
    }
    PERSONS {
        varchar VERSION_ID PK, FK
        varchar ENTITY_KEY
    }
    PERSONS_ADDRESSES {
        varchar VERSION_ID PK, FK
        varchar ITEM_PATH PK
        varchar POSTAL_CODE
    }
    ORGANIZATIONS {
        varchar VERSION_ID PK, FK
        varchar ENTITY_KEY
    }
    BL055 {
        varchar VERSION_ID PK, FK
        varchar INSURED_OBJECT__ADDRESS__POSTAL_CODE
        number COVERAGE__INSURED_AMOUNT
        varchar CONTRACT_VERSION_ID FK
    }
```

Notes on the diagram:
- **Keys.**
  - Every version-level object is keyed on `VERSION_ID`.
  - Every array item is keyed on (`VERSION_ID`, `ITEM_PATH`), e.g. `articles[0].clauses[0]`.
  - Nested items link to their parent through `PARENT_ITEM_PATH`.
  - `sequenceNumber` is not a key because it is sparse.
- **By version, not by entity.** All relations are by `VERSION_ID`, including the `jet://entity` references (snapshot semantics). `ENTITY_KEY` only groups the versions of one entity, for `IS_CURRENT`.
- **Tier 2 shown for one product.** Only the hull-caravan views and the per-variant views that matter here are shown. The per-variant views (e.g. `HCI_ARTICLES__HULL`) have the same key as the union view. The generator-maintained tables `CONFIG_FIELD` and `CODE_LIST` are metadata and are left out of the diagram.
