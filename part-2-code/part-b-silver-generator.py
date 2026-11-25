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
from typing import NamedTuple


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

LOCAL_REF_PREFIX = "#/$defs/"


def _resolve_chain(node: dict, defs: dict) -> tuple[dict, list[str]]:
    """Follow local $refs; return the definition reached and the $defs names passed on the way."""
    names: list[str] = []
    while isinstance(node, dict) and str(node.get("$ref", "")).startswith(LOCAL_REF_PREFIX):
        name = node["$ref"][len(LOCAL_REF_PREFIX):]
        if name in names:
            raise ValueError(f"cyclic $ref chain: {' -> '.join(names + [name])}")
        if name not in defs:
            raise ValueError(f"$ref to unknown definition '{node['$ref']}'")
        names.append(name)
        node = defs[name]
    return node, names


def _has_type(node: dict, type_name: str) -> bool:
    declared = node.get("type")
    return declared == type_name or (isinstance(declared, list) and type_name in declared)


def _is_array(node: dict) -> bool:
    return _has_type(node, "array") or "items" in node


def _is_object(node: dict) -> bool:
    return _has_type(node, "object") or "properties" in node


def _variants(items: dict) -> list:
    return items.get("anyOf") or items.get("oneOf") or []


def _items_are_objects(items: dict, defs: dict) -> bool:
    if _is_object(items):
        return True
    return any(_is_object(resolve_ref(variant, defs)) for variant in _variants(items))


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

    Decision: a cycle raises ValueError naming the chain. A cyclic alias has no
    definition to return, and generating views from a guess is worse than a
    failed generator run. A $ref to a missing definition raises as well.
    """
    return _resolve_chain(prop_def, defs)[0]


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
    items = resolve_ref(items_def, defs)
    # properties next to an anyOf are shared by every variant
    merged = dict(items.get("properties", {})) if _is_object(items) else {}
    discriminators: list[str] = []
    for variant in _variants(items):
        variant = resolve_ref(variant, defs)
        if not _is_object(variant):
            continue
        variant_properties = variant.get("properties", {})
        for name, field_def in variant_properties.items():
            merged.setdefault(name, field_def)  # first definition wins, also when a later variant types it differently
        const = variant_properties.get("_discriminator", {}).get("const")
        if const is not None and const not in discriminators:
            discriminators.append(const)
    return merged, discriminators


def walk(properties: dict, defs: dict, path: str, out: dict,
         parent_array: str | None = None, _expanding: tuple = ()) -> None:
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
    # _expanding holds the $defs names being walked on the current branch; a definition that contains
    # itself (a tree of nodes) is recorded once and not descended into again, so the walk terminates.
    for name, raw_def in properties.items():
        prop_def, ref_names = _resolve_chain(raw_def, defs)
        if any(ref in _expanding for ref in ref_names):
            continue
        expanding = _expanding + tuple(ref_names)
        field_path = f"{path}.{name}" if path else name

        if _is_array(prop_def):
            items_def, item_refs = _resolve_chain(prop_def.get("items", {}), defs)
            if not _items_are_objects(items_def, defs):
                out["scalar_arrays"].append(field_path)
                continue
            merged, discriminators = merge_variants(items_def, defs)
            record = {
                "path": field_path,
                "parent_array": parent_array,
                "discriminators": discriminators,
                "scalar_fields": [field for field, field_def in merged.items()
                                  if not _is_array(resolve_ref(field_def, defs))
                                  and not _is_object(resolve_ref(field_def, defs))],
                "nested_arrays": [],
            }
            out["arrays"].append(record)
            if any(ref in expanding for ref in item_refs):
                continue
            walk(merged, defs, field_path, out, field_path, expanding + tuple(item_refs))
            # also arrays inside an object of the item: their nearest enclosing array is this one
            record["nested_arrays"] = [r["path"] for r in out["arrays"] if r["parent_array"] == field_path]
        elif _is_object(prop_def):
            walk(prop_def.get("properties", {}), defs, field_path, out, parent_array, expanding)
        elif any(_is_object(resolve_ref(variant, defs)) for variant in _variants(prop_def)):
            # an object that is itself an anyOf/oneOf of object variants: descend into the merged fields
            walk(merge_variants(prop_def, defs)[0], defs, field_path, out, parent_array, expanding)


def discover(schemas: list[dict]) -> dict[str, dict]:
    """
    TODO 4: Run the walk for every configuration row whose schema has
    properties.

    Return {"<KEY>": {"arrays": [...], "scalar_arrays": [...]}}, for
    example {"PERSONS": {...}, "HULLCARAVANINTERMEDIARY": {...}}. The
    dictionary key is to_identifier(row["key"]). Skip rows without
    properties (code lists).
    """
    result: dict[str, dict] = {}
    for row in schemas:
        properties, defs = schema_root(row)
        if not properties:
            continue
        out = {"arrays": [], "scalar_arrays": []}
        walk(properties, defs, "", out)
        result[to_identifier(row["key"])] = out
    return result


# --- YOUR IMPLEMENTATION: the generator -------------------------------------

ENTITY_REF_PREFIX = "jet://entity/"
ENVELOPE_COLUMNS = ["VERSION_ID", "ENTITY_KEY", "VERSION_TAG", "VALID_FROM", "VALID_TO",
                    "CURRENT_STATE", "IS_DRAFT", "IS_CURRENT", "LAST_LOADED_AT"]

# Tier 1 of the Part 1 design: fixed SQL, the same for every configuration and customer database.
# Emitted with the generated views so the statements run end to end from BRONZE.ENTITIES_RAW.
# Differs from Part 1 in two places found with the Part 2 data (Part D Q6): draft detection and the tie-breaker.
ENTITY_VERSION_SQL = r"""
-- Tier 1, fixed. Versions: SILVER keeps EVERY version, one row per VERSION_ID.
-- BRONZE re-appends a version when its validTo changes, so per VERSION_ID the latest LOADED_AT carries the
-- latest validTo; the latest-loaded row of an entity is not necessarily its current version.
-- IS_CURRENT = not a draft, VALID_FROM <= now < VALID_TO (or open-ended), and the latest VALID_FROM
-- (then VERSION_TAG, CREATED_AT, VERSION_ID) among the versions of that entity in effect now.
CREATE OR REPLACE VIEW SILVER.ENTITY_VERSION AS
WITH latest_load AS (
    SELECT
        r.VERSION_ID,
        r.ENTITY_TYPE,
        r.ENTITY_KEY,
        r.PAYLOAD:versionTag::NUMBER(38,0)              AS VERSION_TAG,
        r.PAYLOAD:createdAt::TIMESTAMP_NTZ              AS CREATED_AT,
        r.PAYLOAD:validFrom::TIMESTAMP_NTZ              AS VALID_FROM,
        r.PAYLOAD:validTo::TIMESTAMP_NTZ                AS VALID_TO,
        r.PAYLOAD:currentState::VARCHAR                 AS CURRENT_STATE,
        -- persons and organizations carry only currentState, no isDraft
        COALESCE(r.PAYLOAD:isDraft::BOOLEAN, FALSE)
            OR COALESCE(r.PAYLOAD:currentState::VARCHAR = 'draft', FALSE)   AS IS_DRAFT,
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
                               -- persons and organizations have no versionTag; the last two keys make ties deterministic
                               ORDER BY e.VALID_FROM DESC, e.VERSION_TAG DESC NULLS LAST,
                                        e.CREATED_AT DESC NULLS LAST, e.VERSION_ID DESC) = 1  AS IS_CURRENT
FROM in_effect AS e;
"""

ENTITY_ARRAY_ITEM_SQL = r"""
-- Tier 1, fixed. One row per item of every array of objects, at any depth, of every version.
CREATE OR REPLACE VIEW SILVER.ENTITY_ARRAY_ITEM AS
SELECT
    v.VERSION_ID,
    v.ENTITY_TYPE,
    f.PATH                                              AS ITEM_PATH,          -- 'articles[0].clauses[0]'
    REGEXP_REPLACE(f.PATH, '\\[[0-9]+\\]', '')          AS ARRAY_PATH,         -- 'articles.clauses'
    REGEXP_SUBSTR(f.PATH, '^(.*\\])\\.', 1, 1, 'e')     AS PARENT_ITEM_PATH,   -- 'articles[0]'
    f.INDEX                                             AS ITEM_INDEX,
    f.VALUE:_discriminator::VARCHAR                     AS DISCRIMINATOR,
    f.VALUE                                             AS ITEM
FROM SILVER.ENTITY_VERSION AS v,
     LATERAL FLATTEN(INPUT => v.DATA, RECURSIVE => TRUE) AS f
WHERE f.INDEX IS NOT NULL
  AND IS_OBJECT(f.VALUE);
"""


class Column(NamedTuple):
    expr: str       # 'i.ITEM:sumInsured::NUMBER(38,8)'
    name: str       # 'SUM_INSURED'
    path: tuple     # ('sumInsured',) - JSON keys below the item or the root
    is_ref: bool    # jet://entity reference, typed everywhere because it is a join key


def _snake(name: str) -> str:
    """'netAnnualPremium' -> 'NET_ANNUAL_PREMIUM'"""
    return to_identifier(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name))


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _json_path(segments: tuple) -> str:
    return ".".join(s if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) else '"' + s.replace('"', '""') + '"'
                    for s in segments)


def _sql_type(field_def: dict) -> str:
    """Part 1 type mapping; code lists and jet:// references are VARCHAR codes."""
    if _has_type(field_def, "integer"):
        return "NUMBER(38,0)"
    if _has_type(field_def, "number"):
        return "NUMBER(38,8)"
    if _has_type(field_def, "boolean"):
        return "BOOLEAN"
    if field_def.get("format") == "date":
        return "DATE"
    if field_def.get("format") == "date-time":
        return "TIMESTAMP_NTZ"
    return "VARCHAR"


def _columns(properties: dict, defs: dict, source: str, segments: tuple = (), _expanding: tuple = ()) -> list[Column]:
    """Typed columns for every scalar under properties: objects flatten with '__', arrays get their own view."""
    columns = []
    for name, raw_def in properties.items():
        if name == "_discriminator" and not segments:
            continue  # it is the DISCRIMINATOR column of ENTITY_ARRAY_ITEM
        field_def, refs = _resolve_chain(raw_def, defs)
        if any(ref in _expanding for ref in refs) or _is_array(field_def):
            continue
        path = segments + (name,)
        if _is_object(field_def):
            columns += _columns(field_def.get("properties", {}), defs, source, path, _expanding + tuple(refs))
            continue
        is_ref = str(field_def.get("$ref", "")).startswith(ENTITY_REF_PREFIX)
        column = "__".join(_snake(p) for p in path) + ("_VERSION_ID" if is_ref else "")
        columns.append(Column(f"{source}:{_json_path(path)}::{_sql_type(field_def)}", column, path, is_ref))
    return columns


def _array_items(properties: dict, defs: dict, array_path: str) -> dict:
    """Resolved items schema of the array at a discovered path (objects folded, arrays entered via their items)."""
    node = {"properties": properties}
    for segment in array_path.split("."):
        if _is_array(node):
            node = {"properties": merge_variants(node.get("items", {}), defs)[0]}
        node = resolve_ref(node.get("properties", {})[segment], defs)
    return resolve_ref(node.get("items", {}), defs)


def _variant_properties(items: dict, defs: dict) -> dict[str, dict]:
    """{discriminator: properties of that variant}, including properties declared next to the anyOf."""
    shared = items.get("properties", {})
    result = {}
    for variant in _variants(items):
        variant = resolve_ref(variant, defs)
        const = variant.get("properties", {}).get("_discriminator", {}).get("const")
        if _is_object(variant) and const is not None:
            result[const] = {**shared, **variant.get("properties", {})}
    return result


def _view(name: str, comment: str, select: list[str], source: str) -> str:
    aliases = [line.rsplit(" AS ", 1)[-1].split(".")[-1] for line in select]
    duplicates = sorted({a for a in aliases if aliases.count(a) > 1})
    if duplicates:
        raise ValueError(f"view {name} would get duplicate columns {duplicates}")
    body = ",\n".join(f"    {line}" for line in select)
    return f"-- {comment}\nCREATE OR REPLACE VIEW SILVER.{name} AS\nSELECT\n{body}\n{source};"


def _select(columns: list[Column]) -> list[str]:
    return [f"{c.expr:<70} AS {c.name}" for c in columns]


def _array_views(view_prefix: str, entity_type: str, record: dict, properties: dict, defs: dict) -> list[str]:
    path = record["path"]
    view = f"{view_prefix}_{'_'.join(_snake(part) for part in path.split('.'))}"
    items = _array_items(properties, defs, path)
    keys = ["i.VERSION_ID", "i.ITEM_PATH"] + (["i.PARENT_ITEM_PATH"] if record["parent_array"] else []) + ["i.ITEM_INDEX"]
    source = (f"FROM SILVER.ENTITY_ARRAY_ITEM AS i\n"
              f"WHERE i.ENTITY_TYPE = {_sql_literal(entity_type)}\n"
              f"  AND i.ARRAY_PATH  = {_sql_literal(path)}")
    parent = f"; PARENT_ITEM_PATH joins the {record['parent_array']} item's ITEM_PATH" if record["parent_array"] else ""

    if not record["discriminators"]:
        columns = _columns(merge_variants(items, defs)[0], defs, "i.ITEM")
        return [_view(view, f"{path}: one row per item of every version, every field typed{parent}",
                      keys + _select(columns), source)]

    # Part 1 Q2: union view with the columns every variant shares plus the entity references, the rest
    # in VARIANT_FIELDS; and one fully typed view per variant.
    by_variant = {d: _columns(props, defs, "i.ITEM") for d, props in _variant_properties(items, defs).items()}
    variants = [d for d in record["discriminators"] if d in by_variant]
    all_columns = [c for d in variants for c in by_variant[d]]
    union = []
    for c in all_columns:
        top_level = len(c.path) == 1
        shared = all(c in by_variant[d] for d in variants)
        if top_level and (shared or c.is_ref) and c.name not in {u.name for u in union}:
            union.append(c)
    nested_keys = [p[len(path) + 1:] for p in record["nested_arrays"] if "." not in p[len(path) + 1:]]
    delete_keys = list(dict.fromkeys(["_discriminator"] + [c.path[0] for c in union] + nested_keys))
    variant_fields = f"OBJECT_DELETE(i.ITEM::OBJECT, {', '.join(_sql_literal(k) for k in delete_keys)})"
    statements = [_view(view, f"{path}: one row per item of every version; shared fields and entity references typed, "
                              f"the rest in VARIANT_FIELDS{parent}",
                        keys + ["i.DISCRIMINATOR"] + _select(union) + [f"{variant_fields:<70} AS VARIANT_FIELDS"],
                        source)]
    for d in variants:
        statements.append(_view(f"{view}__{to_identifier(d)}", f"{path}, variant {d}: every field of the variant typed",
                                keys + _select(by_variant[d]),
                                f"{source}\n  AND i.DISCRIMINATOR = {_sql_literal(d)}"))
    return statements


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
    key = "HULLCARAVANINTERMEDIARY"
    row = next(r for r in schemas if to_identifier(r.get("key", "")) == key)
    entity_type = row["key"]
    properties, defs = schema_root(row)

    root = _view(key, "root: one row per version (all versions kept, IS_CURRENT marks the current one); "
                      "1:1 objects flattened with '__'",
                 [f"v.{c}" for c in ENVELOPE_COLUMNS] + _select(_columns(properties, defs, "v.DATA")),
                 f"FROM SILVER.ENTITY_VERSION AS v\nWHERE v.ENTITY_TYPE = {_sql_literal(entity_type)}")

    statements = [ENTITY_VERSION_SQL, ENTITY_ARRAY_ITEM_SQL, root]
    for record in discovery[key]["arrays"]:
        statements.extend(_array_views(key, entity_type, record, properties, defs))
    return statements


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
    def run_walk(properties: dict, defs: dict | None = None) -> dict:
        out = {"arrays": [], "scalar_arrays": []}
        walk(properties, defs or {}, "", out)
        return out

    def by_path(out: dict) -> dict:
        return {r["path"]: r for r in out["arrays"]}

    item = {"type": "object", "properties": {"amount": {"type": "number"}}}

    # 1. $ref alias chain: items -> bankAccount -> paymentAccount (the persons.bankAccounts case)
    defs = {"bankAccount": {"$ref": "#/$defs/paymentAccount"},
            "paymentAccount": {"type": "object", "properties": {"iban": {"type": "string"}}}}
    out = run_walk({"bankAccounts": {"type": "array", "items": {"$ref": "#/$defs/bankAccount"}}}, defs)
    assert by_path(out)["bankAccounts"]["scalar_fields"] == ["iban"], out
    assert resolve_ref({"$ref": "jet://schema/CountryLookup"}, defs) == {"$ref": "jet://schema/CountryLookup"}
    print("ok  two-hop $ref chain resolves to the object; jet:// refs stay unchanged")

    # 2. cycles: an alias loop fails loudly; a recursive tree is recorded once and the walk terminates
    try:
        resolve_ref({"$ref": "#/$defs/a"}, {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}})
        raise AssertionError("cyclic alias chain did not raise")
    except ValueError as exc:
        assert "a -> b -> a" in str(exc), exc
    tree = {"node": {"type": "object", "properties": {"label": {"type": "string"},
                                                     "children": {"type": "array", "items": {"$ref": "#/$defs/node"}}}}}
    out = run_walk({"root": {"$ref": "#/$defs/node"}}, tree)
    assert [r["path"] for r in out["arrays"]] == ["root.children"], out
    print("ok  alias cycle a -> b -> a raises; self-referencing tree gives one array and terminates")

    # 3. arrays behind objects: with or without "type": "object" the dotted path is the same, and an
    #    array inside an object inside an item has that item's array as parent
    for wrapper in ({"type": "object", "properties": {"lines": {"type": "array", "items": item}}},
                    {"properties": {"lines": {"type": "array", "items": item}}}):
        assert list(by_path(run_walk({"controlData": wrapper}))) == ["controlData.lines"]
    articles = {"type": "array", "items": {"properties": {
        "commission": {"type": "object", "properties": {"tiers": {"type": "array", "items": item}}}}}}
    found = by_path(run_walk({"articles": articles}))
    assert found["articles.commission.tiers"]["parent_array"] == "articles", found
    assert found["articles"]["nested_arrays"] == ["articles.commission.tiers"], found
    assert found["articles"]["scalar_fields"] == [], found
    print("ok  array behind an object (typed or untyped) and array inside an item's object get the right path and parent")

    # 4. polymorphic items: variants share a field with different types (first wins), a scalar variant is
    #    ignored, and the variants' nested arrays are all found
    parties = {"type": "array", "items": {"anyOf": [
        {"type": "object", "properties": {"_discriminator": {"const": "a"}, "code": {"type": "string"},
                                          "lines": {"type": "array", "items": item}}},
        {"type": "string"},
        {"type": "object", "properties": {"_discriminator": {"const": "b"}, "code": {"type": "integer"},
                                          "extra": {"type": "boolean"}}}]}}
    merged, discriminators = merge_variants(parties["items"], {})
    assert discriminators == ["a", "b"] and merged["code"] == {"type": "string"}, (merged, discriminators)
    found = by_path(run_walk({"parties": parties}))
    assert found["parties"]["scalar_fields"] == ["_discriminator", "code", "extra"], found
    assert found["parties.lines"]["parent_array"] == "parties", found
    print("ok  anyOf merge: first type wins on a shared name, non-object variant skipped, variant's nested array found")

    # 5. not arrays of objects: scalar items, a oneOf code list, an anyOf of scalars, empty properties
    out = run_walk({"tradeNames": {"type": "array", "items": {"type": "string"}},
                    "status": {"type": "string", "oneOf": [{"const": "ACTIVE"}, {"const": "TERMINATED"}]},
                    "codes": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
                    "empty": {"type": "object", "properties": {}}})
    assert out == {"arrays": [], "scalar_arrays": ["tradeNames", "codes"]}, out
    assert run_walk({}) == {"arrays": [], "scalar_arrays": []}
    print("ok  scalar arrays reported as scalar_arrays; oneOf code list and empty properties give nothing")

    # 6. the generator follows the Part 1 design for a polymorphic array
    schema_row = {"key": "hullCaravanIntermediary", "schema": {"properties": {"articles": parties}}}
    statements = generate_silver_sql(discover([schema_row]), [schema_row])
    union = next(s for s in statements if "VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES AS" in s)
    assert "i.DISCRIMINATOR" in union and "AS VARIANT_FIELDS" in union and "AS CODE" not in union, union
    assert any("VIEW SILVER.HULLCARAVANINTERMEDIARY_ARTICLES__B AS" in s and "AS EXTRA" in s for s in statements)
    print("ok  generator: union view keeps a type-conflicting field in VARIANT_FIELDS, variant view types it")


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
