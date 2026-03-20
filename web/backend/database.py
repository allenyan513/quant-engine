"""SQLite database for session/message/backtest persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "quant_web.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                strategy_code TEXT NOT NULL DEFAULT '',
                params TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'running',
                error TEXT,
                metrics TEXT NOT NULL DEFAULT '{}',
                trade_summary TEXT NOT NULL DEFAULT '{}',
                trades TEXT NOT NULL DEFAULT '[]',
                equity_curve TEXT NOT NULL DEFAULT '[]',
                benchmark_curve TEXT NOT NULL DEFAULT '[]',
                drawdown_curve TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
        """)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

DEFAULT_PARAMS = {
    "symbols": ["AAPL"],
    "start": "2023-01-01",
    "end": "2025-12-31",
    "initial_cash": 100000.0,
    "fee_model": "per_share",
    "slippage_rate": 0.0005,
}


def create_session(title: str = "") -> dict:
    sid = uuid.uuid4().hex[:12]
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, params, created_at, updated_at) VALUES (?,?,?,?,?)",
            (sid, title, json.dumps(DEFAULT_PARAMS), now, now),
        )
    return {"id": sid, "title": title, "created_at": now, "updated_at": now}


def list_sessions() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        session = dict(row)
        session["params"] = json.loads(session["params"])
        msgs = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id",
            (sid,),
        ).fetchall()
        session["messages"] = [dict(m) for m in msgs]
    return session


def delete_session(sid: str) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        return cur.rowcount > 0


def update_session_code(sid: str, code: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET strategy_code=?, updated_at=? WHERE id=?",
            (code, _now(), sid),
        )


def update_session_params(sid: str, params: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET params=?, updated_at=? WHERE id=?",
            (json.dumps(params), _now(), sid),
        )


def update_session_title(sid: str, title: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, _now(), sid),
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def add_message(session_id: str, role: str, content: str) -> dict:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, role, content, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id),
        )
    return {"id": cur.lastrowid, "role": role, "content": content, "created_at": now}


def get_messages(session_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

def save_backtest_result(
    session_id: str,
    status: str = "running",
    error: str | None = None,
    metrics: dict | None = None,
    trade_summary: dict | None = None,
    trades: list | None = None,
    equity_curve: list | None = None,
    benchmark_curve: list | None = None,
    drawdown_curve: list | None = None,
) -> int:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO backtest_results
            (session_id, status, error, metrics, trade_summary, trades,
             equity_curve, benchmark_curve, drawdown_curve, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id, status, error,
                json.dumps(metrics or {}),
                json.dumps(trade_summary or {}),
                json.dumps(trades or []),
                json.dumps(equity_curve or []),
                json.dumps(benchmark_curve or []),
                json.dumps(drawdown_curve or []),
                now,
            ),
        )
    return cur.lastrowid  # type: ignore[return-value]


def update_backtest_result(result_id: int, **kwargs) -> None:
    json_fields = {"metrics", "trade_summary", "trades", "equity_curve", "benchmark_curve", "drawdown_curve"}
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(json.dumps(v) if k in json_fields else v)
    vals.append(result_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE backtest_results SET {','.join(sets)} WHERE id=?", vals,
        )


def get_backtest_results(session_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_results WHERE session_id=? ORDER BY id DESC",
            (session_id,),
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        for k in ("metrics", "trade_summary", "trades", "equity_curve", "benchmark_curve", "drawdown_curve"):
            d[k] = json.loads(d[k])
        results.append(d)
    return results
