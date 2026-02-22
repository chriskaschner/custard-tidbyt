#!/usr/bin/env python3
"""Staged Culver's flavor backfill with checkpoints.

Design goals:
- Wisconsin-first workflow.
- Explicit stage boundaries (discover -> wi -> rest).
- Short, resumable runs with meaningful breakpoints.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://custard-calendar.chris-kaschner.workers.dev"
USER_AGENT = "custard-backfill/1.0"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "backfill"
STATE_DIR = DATA_DIR / "state"
CALENDAR_DIR = DATA_DIR / "store_calendars"
DB_PATH = DATA_DIR / "flavors.sqlite"
STORES_PATH = DATA_DIR / "stores.json"
WI_STORES_PATH = DATA_DIR / "stores_wi.json"
REST_STORES_PATH = DATA_DIR / "stores_rest.json"
SNAPSHOT_LOG = DATA_DIR / "snapshot_runs.ndjson"

DISCOVER_STATE = STATE_DIR / "discover_state.json"
WI_STATE = STATE_DIR / "backfill_wi_state.json"
REST_STATE = STATE_DIR / "backfill_rest_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)


def get_json(path: str, params: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    url = f"{API_BASE}{path}{query}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stores (
            slug TEXT PRIMARY KEY,
            name TEXT,
            city TEXT,
            state TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS store_flavors (
            store_slug TEXT,
            flavor_date TEXT,
            title TEXT,
            description TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT,
            PRIMARY KEY (store_slug, flavor_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT,
            segment TEXT,
            store_slug TEXT,
            flavor_count INTEGER,
            min_date TEXT,
            max_date TEXT,
            raw_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def all_discovery_tokens() -> list[str]:
    chars = string.ascii_lowercase + string.digits
    return [a + b for a in chars for b in chars]


def stage_discover(args: argparse.Namespace) -> int:
    ensure_dirs()
    tokens = all_discovery_tokens()

    state = read_json(
        DISCOVER_STATE,
        {
            "started_at": utc_now(),
            "next_index": 0,
            "stores": {},
            "completed_tokens": 0,
            "last_updated_at": None,
        },
    )

    next_index = int(state.get("next_index", 0))
    stores_map: dict[str, dict[str, Any]] = state.get("stores", {})

    processed = 0
    while next_index < len(tokens) and processed < args.tokens_per_run:
        token = tokens[next_index]
        try:
            payload = get_json("/api/v1/stores", {"q": token}, timeout=args.timeout)
        except (urllib.error.URLError, TimeoutError) as err:
            print(f"discover error token={token}: {err}", file=sys.stderr)
            break

        for store in payload.get("stores", []):
            slug = store.get("slug")
            if not slug:
                continue
            stores_map[slug] = {
                "slug": slug,
                "name": store.get("name", ""),
                "city": store.get("city", ""),
                "state": store.get("state", ""),
            }

        next_index += 1
        processed += 1

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    state["stores"] = stores_map
    state["next_index"] = next_index
    state["completed_tokens"] = next_index
    state["last_updated_at"] = utc_now()
    write_json(DISCOVER_STATE, state)

    stores = sorted(stores_map.values(), key=lambda s: s["slug"])
    wi_stores = [s for s in stores if str(s.get("state", "")).upper() == "WI"]
    rest_stores = [s for s in stores if str(s.get("state", "")).upper() != "WI"]
    write_json(STORES_PATH, stores)
    write_json(WI_STORES_PATH, wi_stores)
    write_json(REST_STORES_PATH, rest_stores)

    done = next_index >= len(tokens)
    print(
        "discover",
        json.dumps(
            {
                "done": done,
                "processed_tokens_this_run": processed,
                "completed_tokens_total": next_index,
                "total_tokens": len(tokens),
                "stores_total": len(stores),
                "stores_wi": len(wi_stores),
                "stores_rest": len(rest_stores),
            }
        ),
    )
    return 0


def segment_files(segment: str) -> tuple[Path, Path]:
    if segment == "wi":
        return WI_STORES_PATH, WI_STATE
    if segment == "rest":
        return REST_STORES_PATH, REST_STATE
    raise ValueError(f"unknown segment: {segment}")


def load_segment_stores(segment: str) -> list[dict[str, Any]]:
    stores_path, _ = segment_files(segment)
    if not stores_path.exists():
        raise FileNotFoundError(
            f"Missing {stores_path}. Run the discover stage first: "
            "python scripts/backfill_custard.py discover"
        )
    return read_json(stores_path, [])


def upsert_store(conn: sqlite3.Connection, store: dict[str, Any], seen_at: str) -> None:
    conn.execute(
        """
        INSERT INTO stores(slug, name, city, state, first_seen_at, last_seen_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            name=excluded.name,
            city=excluded.city,
            state=excluded.state,
            last_seen_at=excluded.last_seen_at
        """,
        (
            store.get("slug", ""),
            store.get("name", ""),
            store.get("city", ""),
            store.get("state", ""),
            seen_at,
            seen_at,
        ),
    )


def upsert_flavor(conn: sqlite3.Connection, slug: str, flavor: dict[str, Any], seen_at: str) -> None:
    conn.execute(
        """
        INSERT INTO store_flavors(store_slug, flavor_date, title, description, first_seen_at, last_seen_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_slug, flavor_date) DO UPDATE SET
            title=excluded.title,
            description=excluded.description,
            last_seen_at=excluded.last_seen_at
        """,
        (
            slug,
            flavor.get("date", ""),
            flavor.get("title", ""),
            flavor.get("description", ""),
            seen_at,
            seen_at,
        ),
    )


def backfill_one_store(
    conn: sqlite3.Connection,
    segment: str,
    store: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    slug = store["slug"]
    seen_at = utc_now()
    payload = get_json("/api/v1/flavors", {"slug": slug}, timeout=timeout)
    flavors = payload.get("flavors", [])

    upsert_store(conn, store, seen_at)
    for flavor in flavors:
        upsert_flavor(conn, slug, flavor, seen_at)

    dates = [f.get("date") for f in flavors if f.get("date")]
    min_date = min(dates) if dates else None
    max_date = max(dates) if dates else None

    conn.execute(
        """
        INSERT INTO snapshots(fetched_at, segment, store_slug, flavor_count, min_date, max_date, raw_json)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            seen_at,
            segment,
            slug,
            len(flavors),
            min_date,
            max_date,
            json.dumps(payload, separators=(",", ":")),
        ),
    )

    calendar_out = {
        "fetched_at": seen_at,
        "segment": segment,
        "store": {
            "slug": store.get("slug", ""),
            "name": payload.get("name", store.get("name", "")),
            "address": payload.get("address", ""),
            "city": store.get("city", ""),
            "state": store.get("state", ""),
        },
        "flavors": flavors,
    }
    (CALENDAR_DIR / f"{slug}.json").write_text(
        json.dumps(calendar_out, indent=2, sort_keys=True), encoding="utf-8"
    )

    with SNAPSHOT_LOG.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "fetched_at": seen_at,
                    "segment": segment,
                    "store_slug": slug,
                    "flavor_count": len(flavors),
                    "min_date": min_date,
                    "max_date": max_date,
                }
            )
            + "\n"
        )

    return {
        "slug": slug,
        "count": len(flavors),
        "min_date": min_date,
        "max_date": max_date,
    }


def stage_backfill(args: argparse.Namespace) -> int:
    ensure_dirs()
    stores = load_segment_stores(args.segment)
    stores_path, state_path = segment_files(args.segment)

    state = read_json(
        state_path,
        {
            "segment": args.segment,
            "stores_path": str(stores_path.relative_to(ROOT)),
            "started_at": utc_now(),
            "next_index": 0,
            "completed_slugs": [],
            "last_updated_at": None,
        },
    )

    next_index = int(state.get("next_index", 0))
    completed = set(state.get("completed_slugs", []))

    conn = init_db()

    processed = 0
    success = 0
    failures = 0
    counts: list[int] = []

    while next_index < len(stores) and processed < args.stores_per_run:
        store = stores[next_index]
        slug = store.get("slug", "")

        if slug in completed:
            next_index += 1
            continue

        try:
            result = backfill_one_store(conn, args.segment, store, timeout=args.timeout)
            success += 1
            counts.append(result["count"])
            completed.add(slug)
            print(
                f"ok segment={args.segment} index={next_index + 1}/{len(stores)} "
                f"slug={slug} count={result['count']} "
                f"range={result['min_date']}..{result['max_date']}"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            failures += 1
            print(f"error segment={args.segment} slug={slug}: {err}", file=sys.stderr)
            if args.stop_on_error:
                break

        processed += 1
        next_index += 1
        conn.commit()

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    conn.close()

    state["next_index"] = next_index
    state["completed_slugs"] = sorted(completed)
    state["last_updated_at"] = utc_now()
    write_json(state_path, state)

    done = next_index >= len(stores)
    print(
        "backfill",
        json.dumps(
            {
                "segment": args.segment,
                "done": done,
                "stores_total": len(stores),
                "processed_this_run": processed,
                "success_this_run": success,
                "failures_this_run": failures,
                "next_index": next_index,
                "remaining": max(0, len(stores) - next_index),
                "median_flavors": sorted(counts)[len(counts) // 2] if counts else None,
            }
        ),
    )

    if failures > 0 and args.stop_on_error:
        return 2
    return 0


def stage_status(_: argparse.Namespace) -> int:
    ensure_dirs()

    stores = read_json(STORES_PATH, [])
    wi_stores = read_json(WI_STORES_PATH, [])
    rest_stores = read_json(REST_STORES_PATH, [])
    discover_state = read_json(DISCOVER_STATE, {})
    wi_state = read_json(WI_STATE, {})
    rest_state = read_json(REST_STATE, {})

    conn = init_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM stores")
    stores_db = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM store_flavors")
    flavors_db = cur.fetchone()[0]

    cur.execute("SELECT state, COUNT(*) FROM stores GROUP BY state ORDER BY COUNT(*) DESC LIMIT 10")
    state_top = [{"state": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM snapshots")
    snapshots_db = cur.fetchone()[0]

    conn.close()

    print(
        json.dumps(
            {
                "discovery": {
                    "tokens_completed": discover_state.get("completed_tokens", 0),
                    "stores_found_total": len(stores),
                    "stores_found_wi": len(wi_stores),
                    "stores_found_rest": len(rest_stores),
                    "last_updated_at": discover_state.get("last_updated_at"),
                },
                "backfill": {
                    "wi": {
                        "next_index": wi_state.get("next_index", 0),
                        "completed": len(wi_state.get("completed_slugs", [])),
                        "total": len(wi_stores),
                        "last_updated_at": wi_state.get("last_updated_at"),
                    },
                    "rest": {
                        "next_index": rest_state.get("next_index", 0),
                        "completed": len(rest_state.get("completed_slugs", [])),
                        "total": len(rest_stores),
                        "last_updated_at": rest_state.get("last_updated_at"),
                    },
                },
                "database": {
                    "stores": stores_db,
                    "store_flavor_rows": flavors_db,
                    "snapshots": snapshots_db,
                    "top_states": state_top,
                },
                "paths": {
                    "data_dir": str(DATA_DIR.relative_to(ROOT)),
                    "db": str(DB_PATH.relative_to(ROOT)),
                    "wi_state": str(WI_STATE.relative_to(ROOT)),
                    "rest_state": str(REST_STATE.relative_to(ROOT)),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Staged Culver's flavor backfill utility")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover", help="Discover stores and split WI/rest lists")
    p_discover.add_argument("--tokens-per-run", type=int, default=200, help="Discovery tokens to process per run")
    p_discover.add_argument("--sleep-ms", type=int, default=0, help="Optional sleep between API calls")
    p_discover.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    p_discover.set_defaults(func=stage_discover)

    p_backfill = sub.add_parser("backfill", help="Backfill store flavor windows by segment")
    p_backfill.add_argument("--segment", choices=["wi", "rest"], required=True, help="Store segment")
    p_backfill.add_argument("--stores-per-run", type=int, default=50, help="Stores to process per run")
    p_backfill.add_argument("--sleep-ms", type=int, default=0, help="Optional sleep between API calls")
    p_backfill.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    p_backfill.add_argument("--stop-on-error", action="store_true", help="Stop immediately on first fetch error")
    p_backfill.set_defaults(func=stage_backfill)

    p_status = sub.add_parser("status", help="Show discovery/backfill checkpoint status")
    p_status.set_defaults(func=stage_status)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
