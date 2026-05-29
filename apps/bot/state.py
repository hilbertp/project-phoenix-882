"""SQLite state store for the live bot.

Tables:
  setups            -- every leg the detector finalized (one row per leg)
  setup_states      -- the FSM state per setup, latest row wins
  state_transitions -- append-only log of every FSM transition
  orders            -- exchange orders keyed by our client_order_id
  fills             -- fill events ingested from the exchange

Write-ahead semantics: the FSM persists its NEW state BEFORE placing the
exchange action. This lets the reconciler at startup decide whether the action
ran. The setup table is the planning record; setup_states + state_transitions
are the executor's truth.

Design choices:
  - One connection per process. SQLite is fine for v1 (single-node operator).
  - Foreign keys ON.
  - WAL mode for crash safety + concurrent reads.
  - All writes go through dataclass-shaped helpers (no raw SQL leaking out).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setups (
    setup_key      TEXT PRIMARY KEY,           -- asset|direction|parent_ts|term_ts
    asset          TEXT NOT NULL,
    direction      TEXT NOT NULL,              -- 'up' | 'down'
    parent_ts      TEXT NOT NULL,
    parent_price   REAL NOT NULL,
    term_ts        TEXT NOT NULL,
    term_price     REAL NOT NULL,
    detector_min_bars INTEGER NOT NULL,
    detector_mult     REAL NOT NULL,
    detected_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_setups_asset_detected
    ON setups (asset, detected_at);

-- setup_states.state: armed | entered | tp1_hit | tp2_hit | done
CREATE TABLE IF NOT EXISTS setup_states (
    setup_key  TEXT PRIMARY KEY REFERENCES setups(setup_key) ON DELETE CASCADE,
    state      TEXT NOT NULL,
    payload    TEXT,                           -- JSON freeform
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_key  TEXT NOT NULL REFERENCES setups(setup_key) ON DELETE CASCADE,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    at         TEXT NOT NULL,
    payload    TEXT
);

CREATE INDEX IF NOT EXISTS idx_transitions_setup
    ON state_transitions (setup_key, id);

-- orders.level_role: entry | init_sl | tp1 | tp2 | tp3 | be_close
-- orders.status:     pending | live | filled | cancelled | rejected
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    setup_key       TEXT NOT NULL REFERENCES setups(setup_key) ON DELETE CASCADE,
    asset           TEXT NOT NULL,
    side            TEXT NOT NULL,             -- buy | sell
    level_role      TEXT NOT NULL,
    qty             REAL NOT NULL,
    price           REAL,                      -- null for market orders
    status          TEXT NOT NULL,
    exchange_order_id TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_setup ON orders (setup_key);

CREATE TABLE IF NOT EXISTS fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
    qty             REAL NOT NULL,
    price           REAL NOT NULL,
    fee             REAL NOT NULL,
    filled_at       TEXT NOT NULL,
    raw             TEXT
);

CREATE INDEX IF NOT EXISTS idx_fills_order ON fills (client_order_id);

-- Per-process runtime state outside the FSM/order lifecycle. Keyed flat
-- store so M4 risk/kill/observability hooks don't need their own tables.
-- Conventional keys:
--   halt            -> non-null when the kill switch has fired
--   pause_asset:<X> -> non-null when asset X is paused (e.g. adverse funding)
--   funding_apy:<X> -> last-observed annualized funding rate (string float)
CREATE TABLE IF NOT EXISTS runtime_flags (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Append-only audit trail for every kill-switch fire(). Lets risk-status
-- and the dashboard show "last halt was at X for reason Y" without
-- parsing log files.
CREATE TABLE IF NOT EXISTS kill_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    halted_at   TEXT NOT NULL,
    reason      TEXT NOT NULL,
    summary     TEXT NOT NULL                  -- JSON serialized summary
);

CREATE INDEX IF NOT EXISTS idx_kill_events_halted_at
    ON kill_events (halted_at);
"""


@dataclass(frozen=True, slots=True)
class SetupRecord:
    setup_key: str
    asset: str
    direction: str
    parent_ts: str
    parent_price: float
    term_ts: str
    term_price: float
    detector_min_bars: int
    detector_mult: float
    detected_at: str


@dataclass(frozen=True, slots=True)
class SetupState:
    setup_key: str
    state: str
    payload: dict | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class OrderRecord:
    client_order_id: str
    setup_key: str
    asset: str
    side: str
    level_role: str
    qty: float
    price: float | None
    status: str
    exchange_order_id: str | None
    created_at: str
    updated_at: str


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def setup_key_for(asset: str, direction: str, parent_ts: str, term_ts: str) -> str:
    return f"{asset}|{direction}|{parent_ts}|{term_ts}"


class StateStore:
    """Thin SQLite wrapper. Use as a context manager or call close() explicitly."""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False allows the connection to be shared
        # across threads (the dashboard's ThreadingHTTPServer hits it
        # from worker threads). Safe because:
        #   - WAL mode handles concurrent reads
        #   - All writes go through self.transaction() which BEGINs +
        #     COMMITs explicitly and serializes via Python's GIL
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._migrate()

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        cur = self._conn.execute("SELECT MAX(version) FROM schema_meta;")
        latest = cur.fetchone()[0]
        if latest is None:
            self._conn.execute(
                "INSERT INTO schema_meta (version, applied_at) VALUES (?, ?);",
                (SCHEMA_VERSION, now_iso()),
            )
        elif latest < SCHEMA_VERSION:
            # Migrations would go here when SCHEMA_VERSION bumps.
            self._conn.execute(
                "INSERT INTO schema_meta (version, applied_at) VALUES (?, ?);",
                (SCHEMA_VERSION, now_iso()),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN;")
        try:
            yield self._conn
        except Exception:
            self._conn.execute("ROLLBACK;")
            raise
        else:
            self._conn.execute("COMMIT;")

    # --- setups ------------------------------------------------------------

    def upsert_setup(self, rec: SetupRecord) -> bool:
        """Insert a setup or no-op if its setup_key already exists.

        Returns True if a new row was written, False if it already existed.
        Detector idempotency relies on this: re-running over the same candles
        re-produces the same setup_key and must not duplicate the row.
        """
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO setups (
              setup_key, asset, direction, parent_ts, parent_price,
              term_ts, term_price, detector_min_bars, detector_mult, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                rec.setup_key, rec.asset, rec.direction,
                rec.parent_ts, rec.parent_price,
                rec.term_ts, rec.term_price,
                rec.detector_min_bars, rec.detector_mult,
                rec.detected_at,
            ),
        )
        return cur.rowcount == 1

    def get_setup(self, setup_key: str) -> SetupRecord | None:
        row = self._conn.execute(
            "SELECT * FROM setups WHERE setup_key = ?;", (setup_key,)
        ).fetchone()
        return _setup_from_row(row) if row else None

    def list_setups(
        self, asset: str | None = None, limit: int = 100,
    ) -> list[SetupRecord]:
        if asset is None:
            rows = self._conn.execute(
                "SELECT * FROM setups ORDER BY detected_at DESC LIMIT ?;",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM setups WHERE asset = ?"
                " ORDER BY detected_at DESC LIMIT ?;",
                (asset, limit),
            ).fetchall()
        return [_setup_from_row(r) for r in rows]

    # --- FSM state ---------------------------------------------------------

    def set_state(
        self,
        setup_key: str,
        new_state: str,
        payload: dict | None = None,
    ) -> None:
        """Write the new FSM state AND append a transition row, in one txn."""
        ts = now_iso()
        payload_json = json.dumps(payload) if payload is not None else None
        with self.transaction():
            prev = self._conn.execute(
                "SELECT state FROM setup_states WHERE setup_key = ?;",
                (setup_key,),
            ).fetchone()
            prev_state = prev["state"] if prev else None
            self._conn.execute(
                """
                INSERT INTO setup_states (setup_key, state, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(setup_key) DO UPDATE SET
                  state = excluded.state,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at;
                """,
                (setup_key, new_state, payload_json, ts),
            )
            self._conn.execute(
                """
                INSERT INTO state_transitions (
                  setup_key, from_state, to_state, at, payload
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (setup_key, prev_state, new_state, ts, payload_json),
            )

    def get_state(self, setup_key: str) -> SetupState | None:
        row = self._conn.execute(
            "SELECT * FROM setup_states WHERE setup_key = ?;", (setup_key,)
        ).fetchone()
        if not row:
            return None
        return SetupState(
            setup_key=row["setup_key"],
            state=row["state"],
            payload=json.loads(row["payload"]) if row["payload"] else None,
            updated_at=row["updated_at"],
        )

    # --- orders ------------------------------------------------------------

    def upsert_order(self, rec: OrderRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO orders (
              client_order_id, setup_key, asset, side, level_role,
              qty, price, status, exchange_order_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_order_id) DO UPDATE SET
              status = excluded.status,
              exchange_order_id = COALESCE(
                excluded.exchange_order_id, orders.exchange_order_id
              ),
              updated_at = excluded.updated_at;
            """,
            (
                rec.client_order_id, rec.setup_key, rec.asset, rec.side, rec.level_role,
                rec.qty, rec.price, rec.status, rec.exchange_order_id,
                rec.created_at, rec.updated_at,
            ),
        )

    def open_orders_for(self, setup_key: str) -> list[OrderRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM orders
            WHERE setup_key = ? AND status IN ('pending', 'live')
            ORDER BY created_at;
            """,
            (setup_key,),
        ).fetchall()
        return [_order_from_row(r) for r in rows]

    def get_order(self, client_order_id: str) -> OrderRecord | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE client_order_id = ?;",
            (client_order_id,),
        ).fetchone()
        return _order_from_row(row) if row else None

    # --- runtime_flags ---------------------------------------------------

    def set_flag(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO runtime_flags (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              updated_at = excluded.updated_at;
            """,
            (key, value, now_iso()),
        )

    def get_flag(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM runtime_flags WHERE key = ?;", (key,),
        ).fetchone()
        return row["value"] if row else None

    def clear_flag(self, key: str) -> None:
        self._conn.execute(
            "DELETE FROM runtime_flags WHERE key = ?;", (key,),
        )

    def list_flags_prefix(self, prefix: str) -> dict[str, str]:
        """Return all `runtime_flags` whose key starts with `prefix`."""
        rows = self._conn.execute(
            "SELECT key, value FROM runtime_flags WHERE key LIKE ? || '%';",
            (prefix,),
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # --- kill_events -----------------------------------------------------

    def record_kill_event(self, halted_at: str, reason: str,
                          summary_json: str) -> None:
        self._conn.execute(
            """
            INSERT INTO kill_events (halted_at, reason, summary)
            VALUES (?, ?, ?);
            """,
            (halted_at, reason, summary_json),
        )

    def list_kill_events(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, halted_at, reason, summary
              FROM kill_events
             ORDER BY halted_at DESC
             LIMIT ?;
            """,
            (limit,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                summary = json.loads(r["summary"])
            except json.JSONDecodeError:
                summary = {"_raw": r["summary"]}
            out.append({
                "id": r["id"], "halted_at": r["halted_at"],
                "reason": r["reason"], "summary": summary,
            })
        return out

    # --- queries used by the risk engine --------------------------------

    def count_setups_in_state(self, states: tuple[str, ...]) -> int:
        if not states:
            return 0
        placeholders = ",".join("?" * len(states))
        row = self._conn.execute(
            f"""
            SELECT COUNT(*) AS n
              FROM setup_states
             WHERE state IN ({placeholders});
            """,
            states,
        ).fetchone()
        return int(row["n"] or 0)

    def count_setups_per_asset_since(
        self, asset: str, since_ts: str,
    ) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n
              FROM setups
             WHERE asset = ? AND detected_at >= ?;
            """,
            (asset, since_ts),
        ).fetchone()
        return int(row["n"] or 0)

    def sum_realized_r_since(
        self, since_ts: str,
        terminal_states: tuple[str, ...] = (
            "wipeout", "tp1_then_scratch", "tp2_then_scratch", "tp3_full",
        ),
    ) -> float:
        """Sum realized_r (from setup_states.payload JSON) over terminal
        setups updated at or after `since_ts`."""
        if not terminal_states:
            return 0.0
        placeholders = ",".join("?" * len(terminal_states))
        rows = self._conn.execute(
            f"""
            SELECT payload FROM setup_states
             WHERE state IN ({placeholders}) AND updated_at >= ?;
            """,
            (*terminal_states, since_ts),
        ).fetchall()
        total = 0.0
        for r in rows:
            if not r["payload"]:
                continue
            try:
                obj = json.loads(r["payload"])
            except json.JSONDecodeError:
                continue
            total += float(obj.get("realized_r", 0.0) or 0.0)
        return total

    def recent_terminal_outcomes(
        self, limit: int,
        terminal_states: tuple[str, ...] = (
            "wipeout", "tp1_then_scratch", "tp2_then_scratch", "tp3_full",
        ),
    ) -> list[tuple[str, float]]:
        """Most-recent triggered setups newest-first, as (state, realized_r)."""
        if not terminal_states:
            return []
        placeholders = ",".join("?" * len(terminal_states))
        rows = self._conn.execute(
            f"""
            SELECT state, payload FROM setup_states
             WHERE state IN ({placeholders})
             ORDER BY updated_at DESC
             LIMIT ?;
            """,
            (*terminal_states, limit),
        ).fetchall()
        out: list[tuple[str, float]] = []
        for r in rows:
            try:
                obj = json.loads(r["payload"]) if r["payload"] else {}
            except json.JSONDecodeError:
                obj = {}
            out.append((r["state"], float(obj.get("realized_r", 0.0) or 0.0)))
        return out


def _setup_from_row(row: sqlite3.Row) -> SetupRecord:
    return SetupRecord(
        setup_key=row["setup_key"],
        asset=row["asset"],
        direction=row["direction"],
        parent_ts=row["parent_ts"],
        parent_price=row["parent_price"],
        term_ts=row["term_ts"],
        term_price=row["term_price"],
        detector_min_bars=row["detector_min_bars"],
        detector_mult=row["detector_mult"],
        detected_at=row["detected_at"],
    )


def _order_from_row(row: sqlite3.Row) -> OrderRecord:
    return OrderRecord(
        client_order_id=row["client_order_id"],
        setup_key=row["setup_key"],
        asset=row["asset"],
        side=row["side"],
        level_role=row["level_role"],
        qty=row["qty"],
        price=row["price"],
        status=row["status"],
        exchange_order_id=row["exchange_order_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
