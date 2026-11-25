"""
PART A - Bronze ingestion loader: code review and bug fixing
============================================================
This script simulates the loader that copies entity versions from the
JET Engine API into the append-only BRONZE.ENTITIES_RAW table.

The API pages with keyset pagination:

    GET /entity/key/{configKey}/keyset?size=100&after=<token>
    -> {"content": [wrapper, ...], "nextToken": "<token>" | null}

Every wrapper is one entity VERSION:

    {"configKey": "persons", "entityId": "ent-001", "versionId": "v-001-a",
     "createdAt": "...", "validFrom": "...", "validTo": null,
     "currentState": "final", "data": {...}}

Loader rules (as agreed with the team):
  * BRONZE is append-only. A row is (LOADED_AT, ENTITY_TYPE, ENTITY_KEY,
    VERSION_ID, PAYLOAD) where PAYLOAD is the unchanged wrapper.
  * Re-loading an unchanged version must NOT add a row. A version whose
    validTo changed since it was loaded (the version was closed) MUST be
    appended again, so the dedup key is (VERSION_ID, validTo).
  * Transient API errors (timeouts, 5xx) are retried with backoff;
    permanent errors (4xx) are logged once and the entity type is skipped.
  * One failing entity type must not stop the others.

Everything runs locally: the API is faked from data/api-pages.json and
the bronze table is an in-memory list pre-loaded from
data/bronze-existing.json. No network, no external packages.

    python3 part-a-bronze-loader.py

A junior developer wrote this and it contains at least six bugs or
design issues. Your task is described in the readme.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("bronze-loader")

CONFIG = {
    "base_url": "https://api.example-tenant.anva6.local",
    "client_id": "dataplatform-loader",
    "client_secret": "s3cr3t-do-not-log-8f1c9d",
    "config_keys": ["persons", "organizations", "hullCaravanIntermediary", "claims"],
    "page_size": 100,
    "max_attempts": 3,
}


# --- fake API ---------------------------------------------------------------

class TransientError(Exception):
    """Timeouts, 5xx responses: the same request may succeed when retried."""


class PermanentError(Exception):
    """4xx responses (unknown entity type, bad request): retrying cannot help."""


class FakeApi:
    """Serves the pages in data/api-pages.json with keyset semantics.

    - The first request for organizations page 'organizations-p2' fails with
      a TransientError (simulated 503); the retry succeeds.
    - Any entity type not present in the file raises a PermanentError
      (simulated 422 'entity type is not configured').
    """

    TRANSIENT_ONCE = {("organizations", "organizations-p2")}

    def __init__(self, pages_by_type: dict, token: str):
        self._pages = pages_by_type
        self._token = token
        self._failed_once = set()
        self.calls = 0

    def get_page(self, entity_type: str, after: str | None = None) -> dict:
        self.calls += 1
        if entity_type not in self._pages:
            raise PermanentError(f"422 entity type '{entity_type}' is not configured for this tenant")
        if (entity_type, after) in self.TRANSIENT_ONCE and (entity_type, after) not in self._failed_once:
            self._failed_once.add((entity_type, after))
            raise TransientError(f"503 upstream timeout for {entity_type} after={after}")
        pages = self._pages[entity_type]
        if after is None:
            return pages[0]
        for page in pages:
            if page.get("_token") == after:
                return page
        raise PermanentError(f"400 unknown page token '{after}' for {entity_type}")


def build_api(pages_path: Path, token: str) -> FakeApi:
    raw = json.loads(pages_path.read_text())
    pages_by_type = {}
    for entity_type, pages in raw.items():
        if entity_type.startswith("_"):
            continue
        # give every page after the first the token that the previous page announced
        for i, page in enumerate(pages):
            page["_token"] = None if i == 0 else pages[i - 1]["nextToken"]
        pages_by_type[entity_type] = pages
    return FakeApi(pages_by_type, token)


# --- retry ------------------------------------------------------------------

def with_retry(fn, what: str, max_attempts: int):
    """Call fn(); retry with (simulated) exponential backoff on retryable errors."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except PermanentError as exc:
            wait = 2 ** (attempt - 1)
            log.warning("%s failed (attempt %d/%d): %s - retrying in %ds (simulated)",
                        what, attempt, max_attempts, exc, wait)
            # time.sleep(wait) in the real loader; simulated here
    raise PermanentError(f"{what} failed after {max_attempts} attempts")


# --- dedup ------------------------------------------------------------------

def known_keys(bronze: list, entity_type: str, cache: set = set()) -> set:
    """Return the dedup keys already present in bronze for this entity type.

    Cached so that we scan the bronze table only once per entity type.
    """
    if not cache:
        for row in bronze:
            if row["ENTITY_TYPE"] == entity_type:
                cache.add((row["ENTITY_KEY"], row["PAYLOAD"].get("validTo")))
    return cache


def dedup_key(wrapper: dict) -> tuple:
    return (wrapper["entityId"], wrapper.get("validTo"))


# --- loader -----------------------------------------------------------------

def fetch_pages(api: FakeApi, entity_type: str, max_attempts: int):
    """Yield all pages for an entity type, following nextToken."""
    after = None
    while True:
        page = with_retry(lambda: api.get_page(entity_type, after),
                          f"GET {entity_type} after={after}", max_attempts)
        yield page
        after = page.get("nextToken")
        break


def to_bronze_row(wrapper: dict, entity_type: str, loaded_at: str) -> dict:
    return {
        "LOADED_AT": loaded_at,
        "ENTITY_TYPE": entity_type,
        "ENTITY_KEY": wrapper["entityId"],
        "VERSION_ID": wrapper["versionId"],
        "PAYLOAD": wrapper,
    }


def load_entities(api: FakeApi, config_keys: list, bronze: list, max_attempts: int = 3) -> dict:
    """Load every configured entity type into bronze. Returns a summary per type."""
    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {}
    entity_type = config_keys[0]
    log.info("Run started at %s, first entity type: %s", loaded_at, entity_type)

    for config_key in config_keys:
        stats = {"pages": 0, "read": 0, "appended": 0, "skipped": 0, "errors": 0}
        summary[config_key] = stats
        try:
            seen = known_keys(bronze, config_key)
            for page in fetch_pages(api, config_key, max_attempts):
                stats["pages"] += 1
                for wrapper in page["content"]:
                    stats["read"] += 1
                    key = dedup_key(wrapper)
                    if key in seen:
                        stats["skipped"] += 1
                        continue
                    bronze.append(to_bronze_row(wrapper, entity_type, loaded_at))
                    seen.add(key)
                    stats["appended"] += 1
        except (TransientError, PermanentError) as exc:
            stats["errors"] += 1
            log.error("%s: giving up on this entity type: %s", config_key, exc)
        log.info("%s done: %s", config_key, stats)
        entity_type = config_key

    return summary


# --- main -------------------------------------------------------------------

def print_summary(summary: dict, bronze: list, before: int) -> None:
    print("\nSUMMARY")
    print(f"{'entity type':<26}{'pages':>6}{'read':>6}{'appended':>10}{'skipped':>9}{'errors':>8}")
    tot = {"pages": 0, "read": 0, "appended": 0, "skipped": 0, "errors": 0}
    for entity_type, s in summary.items():
        print(f"{entity_type:<26}{s['pages']:>6}{s['read']:>6}{s['appended']:>10}{s['skipped']:>9}{s['errors']:>8}")
        for k in tot:
            tot[k] += s[k]
    print(f"{'TOTAL':<26}{tot['pages']:>6}{tot['read']:>6}{tot['appended']:>10}{tot['skipped']:>9}{tot['errors']:>8}")
    print(f"\nbronze rows before: {before}, after: {len(bronze)}")
    by_type = {}
    for row in bronze:
        by_type[row["ENTITY_TYPE"]] = by_type.get(row["ENTITY_TYPE"], 0) + 1
    print("bronze rows by ENTITY_TYPE:", dict(sorted(by_type.items())))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    data_dir = Path(__file__).resolve().parent.parent / "data"

    token = f"Bearer {CONFIG['client_id']}:{CONFIG['client_secret']}"
    log.info("Connecting to %s as %s with token %s", CONFIG["base_url"], CONFIG["client_id"], token)

    api = build_api(data_dir / "api-pages.json", token)
    bronze = json.loads((data_dir / "bronze-existing.json").read_text())
    before = len(bronze)

    summary = load_entities(api, CONFIG["config_keys"], bronze, CONFIG["max_attempts"])
    print_summary(summary, bronze, before)
