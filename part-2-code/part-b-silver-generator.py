"""
PART B - Silver generator: make your Part 1 design executable
=============================================================
In Part 1 you designed the layer above BRONZE. Here you make that design
executable for one entity: the hull-caravan contract, the same contract
you modelled in Part 1. This generator reads the configuration rows in
data/schemas.json, discovers the repeating structures in every schema,
and emits the Snowflake SQL that implements YOUR silver design for the
hull-caravan configuration (key hullCaravanIntermediary, discovery key
HULLCARAVANINTERMEDIARY). Whether you chose fully typed tables, a
schema-agnostic structure, a mix, or something else, the SQL must follow
your Part 1 answer. The walker (TODO 1 to 4) is graded on fixed
expectations; the generator (TODO 5) on consistency with your Part 1.

TODO 1 to 4 - the walker. Before entity JSON can be decomposed we need to
know, from the schemas alone, where the repeating structures are: which
properties are arrays of objects, how they nest, which of them are
polymorphic (items with anyOf / oneOf and a _discriminator), and which
scalar fields each array item carries. The walker reads data/schemas.json
and reports exactly that, for every configuration in the file. Merging
variant properties in the walker is only for DISCOVERY of fields; it does
not prescribe how you store variants - that is your Part 1 Q2 decision.

TODO 5 - the generator. From the discovery result and the schema,
generate_silver_sql() returns the Snowflake statements for the
hull-caravan configuration, reading from BRONZE.ENTITIES_RAW. Scope: the
root structure plus AT LEAST ONE nested array; more is optional. See its
docstring for the hard requirements.

TODO 6 - tests for the walker.

Schema conventions you will meet in data/schemas.json (a list of
configuration rows, the shape that GET /entity-schema/key/{key}/effective
returns and that lands in BRONZE.ANVA6_CONFIGURATIONS):
  * A row has key, name, type, configurationType, states and schema; the
    entity fields live in row["schema"]["properties"]. Rows whose schema
    has no properties (code lists such as countries: a string schema with
    a oneOf of constants) are skipped.
  * Local definitions live in row["schema"]["$defs"] and are referenced
    as {"$ref": "#/$defs/<name>"}. A definition may itself be a $ref (an
    alias chain).
  * Non-local references ({"$ref": "jet://schema/...Lookup"} for code
    lists, {"$ref": "jet://entity/<key>#/properties/id"} for links to
    other entities) are scalars from the walker's point of view: leave
    them unchanged.
  * An array's items is one of: an object schema with properties (with or
    without "type": "object"), a $ref, an anyOf/oneOf list of object
    variants each carrying a {"_discriminator": {"const": ...}}, or a
    scalar schema ({"type": "string"}).
  * A oneOf of constants on a scalar property (partyType, buildingType) is
    a code list, not a polymorphic array.
  * Objects between arrays fold into a dotted path, so an array at
    controlData.scheduledFinancialTransaction is reported under that path.
  * Objects inside an array item (an article's intermediaryCommission)
    are neither scalar fields nor arrays of that item; descend into them,
    they may hold arrays of their own.

Implement TODO 1 to TODO 6. The __main__ block runs your tests, prints
the discovered paths and totals so you can check your walker, and then
prints every generated statement.

    python3 part-b-silver-generator.py

No external packages; Python 3.9+.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# --- PROVIDED helpers -------------------------------------------------------

def to_identifier(name: str) -> str:
    """'hullCaravanIntermediary' -> 'HULLCARAVANINTERMEDIARY'; used for table and column names."""
    if not name:
        return "UNNAMED"
    cleaned = re.sub(r"[^A-Z0-9_]", "_", name.upper())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = f"T_{cleaned}"
    return cleaned or "UNNAMED"


def schema_root(row: dict) -> tuple[dict, dict]:
    """Return (properties, defs) of one configuration row of schemas.json; ({}, {}) for code lists."""
    node = row.get("schema", {}) or {}
    return node.get("properties", {}) or {}, node.get("$defs", {}) or {}


# --- YOUR IMPLEMENTATION: the walker ----------------------------------------

def resolve_ref(prop_def: dict, defs: dict) -> dict:
    """
    TODO 1: Resolve local references.

    If prop_def is {"$ref": "#/$defs/<name>"}, return the definition it
    points to, following chains (a definition that is itself a local $ref)
    and guarding against cycles (a -> b -> a must not loop forever; return
    the last definition reached, or raise a clear error - your choice, but
    document it).

    Anything else - a normal schema node, or a non-local $ref such as
    "jet://schema/CountryLookup" or "jet://entity/organizations#/properties/id"
    - is returned unchanged.
    """
    raise NotImplementedError("TODO 1")


def merge_variants(items_def: dict, defs: dict) -> tuple[dict, list[str]]:
    """
    TODO 2: Return (merged_properties, discriminators) for an array's items.

    - items with anyOf / oneOf: merge the "properties" of every object
      variant into one dict (first definition of a name wins; a later
      variant with the same field name but a different type may be noted
      but must not break the merge), and collect the "const" of each
      variant's "_discriminator" property in the list.
    - items with plain "properties": return (properties, []).
    - items that are a local $ref: resolve first, then apply the above.
    - items that are a scalar schema or anything else: return ({}, []).

    The merge is only for DISCOVERY of the fields an item can carry; how
    you store the variants is your Part 1 Q2 decision, not the walker's.
    """
    raise NotImplementedError("TODO 2")


def walk(properties: dict, defs: dict, path: str, out: dict) -> None:
    """
    TODO 3: Recursively walk a properties dict and record arrays in out.

    out has two lists: out["arrays"] and out["scalar_arrays"].
    path is the dotted prefix of the current level ("" at the root).

    For each (name, prop_def) in properties (resolve local refs first):
      - object with properties -> descend with path "<path>.<name>" (no
        record of its own; objects fold into the dotted path).
      - array whose items are objects (directly, via $ref, or via anyOf /
        oneOf) -> append a record to out["arrays"]:
            {
              "path": "articles.clauses",        # dotted path of the array
              "parent_array": "articles",         # nearest enclosing array path, or None
              "discriminators": ["hull", ...],    # [] when not polymorphic
              "scalar_fields": ["sequenceNumber", ...], # item fields that are not
                                                        # objects/arrays; include
                                                        # _discriminator when present
              "nested_arrays": ["articles.clauses"],    # array-of-object paths directly
                                                        # inside this item
            }
        and descend into the (merged) item properties with the array's
        path as the new prefix.
      - array whose items are scalars -> append the dotted path to
        out["scalar_arrays"].
      - scalar / non-local $ref / anything else -> ignore.

    Hint: you need to know the nearest enclosing array to fill
    parent_array; pass it along as you recurse (add a parameter with a
    default value if you like).
    """
    raise NotImplementedError("TODO 3")


def discover(schemas: list[dict]) -> dict[str, dict]:
    """
    TODO 4: Run the walk for every configuration row whose schema has
    properties.

    Return {"<KEY>": {"arrays": [...], "scalar_arrays": [...]}}, for
    example {"PERSONS": {...}, "HULLCARAVANINTERMEDIARY": {...}}. The
    dictionary key is to_identifier(row["key"]). Skip rows without
    properties (code lists).
    """
    raise NotImplementedError("TODO 4")


# --- YOUR IMPLEMENTATION: the generator -------------------------------------

def generate_silver_sql(discovery: dict, schemas: list[dict]) -> list[str]:
    """
    TODO 5: Return the Snowflake statements that implement YOUR Part 1
    silver design for the hull-caravan configuration (discovery key
    HULLCARAVANINTERMEDIARY, the same contract you modelled in Part 1),
    reading from the bronze table:

        -- BRONZE.ENTITIES_RAW
        --   LOADED_AT    TIMESTAMP_NTZ   when this row was appended
        --   ENTITY_TYPE  VARCHAR         the configuration key: 'persons',
        --                                'organizations', 'hullCaravanIntermediary'
        --   ENTITY_KEY   VARCHAR         the entityId
        --   VERSION_ID   VARCHAR         the versionId
        --   PAYLOAD      VARIANT         the full API wrapper: envelope fields
        --                                (validFrom, validTo, currentState, ...)
        --                                at the top, entity fields under PAYLOAD:data

    `discovery` is the result of discover(); `schemas` is the parsed
    data/schemas.json (you need it for the field types). Use the
    discovery records for HULLCARAVANINTERMEDIARY to drive what you
    generate; do not hand-write the statements.

    Scope: the root structure plus AT LEAST ONE nested array (for example
    articles, or articles.clauses); more is optional.

    Hard requirements:
      (a) At least one statement is a complete, runnable SELECT (or a
          CREATE ... AS SELECT) that reads nested array items from
          BRONZE.ENTITIES_RAW.PAYLOAD and returns typed columns
          (`path::TYPE` casts). Hint: LATERAL FLATTEN is the usual
          Snowflake tool for this.
      (b) Versions: state in a comment which rows your silver keeps
          (every version, or only the current one) and implement that
          rule. Note that BRONZE is append-only and the loader appends a
          version again when its validTo changed, so the most recently
          loaded row is not necessarily the current version; use the
          envelope fields (validFrom, validTo, currentState, versionId)
          to define 'current'.
      (c) The object type you create (TABLE, DYNAMIC TABLE or VIEW) must
          match the materialisation you chose in Part 1 Q3 for your pilot.
      (d) Polymorphic arrays (articles) are handled the way you answered
          Part 1 Q2: a discriminator column, and your decision on the
          variant-specific fields (typed columns, a VARIANT column, or
          separate structures).

    Allowed simplifications: the type mapping may be hard-coded (integer
    -> NUMBER, number -> FLOAT, string -> VARCHAR, format date -> DATE,
    boolean -> BOOLEAN, non-local $ref -> VARCHAR); output may be limited
    to the root plus the arrays you consider necessary for your design.
    Every statement must be syntactically plausible Snowflake.

    The __main__ block prints every returned statement after the
    discovery summary. Paste the statement for articles.clauses (or the
    array you chose) into notes.md and explain in three lines how it
    reflects your Part 1 design.
    """
    raise NotImplementedError("TODO 5")


# --- tests ------------------------------------------------------------------

def run_tests() -> None:
    """
    TODO 6: Write at least three tests using plain `assert` (no external
    packages). At least two must cover edge cases of the walker, built
    from inline schema fragments - for example: an empty properties dict,
    a $ref chain of two hops (a $defs entry that is itself a $ref), an
    anyOf whose variants are not all objects, an array behind an object
    (with or without "type": "object"; the dotted path must be the same),
    an array whose items are scalars, two variants that share a field
    name, a oneOf of constants on a scalar that must not be reported as
    an array. Do not rely on data/schemas.json alone.

    Which cases you choose tells us what you understood. Print one line
    per test so the output shows what was checked.
    """
    # TODO 6: replace this stub with your tests
    print("run_tests: no tests implemented yet")


# --- main -------------------------------------------------------------------

if __name__ == "__main__":
    run_tests()

    schemas_path = Path(__file__).resolve().parent.parent / "data" / "schemas.json"
    schemas = json.loads(schemas_path.read_text())

    result = discover(schemas)

    total_arrays = 0
    total_scalar_arrays = 0
    for schema_key in sorted(result):
        found = result[schema_key]
        print(f"\n{schema_key}")
        for rec in found["arrays"]:
            total_arrays += 1
            flag = f"  variants={rec['discriminators']}" if rec["discriminators"] else ""
            print(f"  array   {rec['path']:<44} parent={rec['parent_array']}{flag}")
            print(f"          fields={rec['scalar_fields']}")
            if rec["nested_arrays"]:
                print(f"          nested={rec['nested_arrays']}")
        for p in found["scalar_arrays"]:
            total_scalar_arrays += 1
            print(f"  scalars {p}")

    print(f"\nTotals: {len(result)} configurations with properties, "
          f"{total_arrays} array-of-object paths, {total_scalar_arrays} scalar arrays")

    statements = generate_silver_sql(result, schemas)
    print(f"\n{'=' * 78}\nGenerated silver SQL for HULLCARAVANINTERMEDIARY ({len(statements)} statements)\n{'=' * 78}")
    for statement in statements:
        print(f"\n{statement.strip()}\n")
