"""SQLite 数据层：待办 / 日程 / 账目 / 电脑能力。单文件库，好备份。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import CFG

_DDL = """
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  due TEXT,
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT,
  note TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  amount REAL NOT NULL,
  category TEXT NOT NULL DEFAULT '其他',
  note TEXT,
  occurred_on TEXT NOT NULL DEFAULT (date('now','localtime')),
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  kind TEXT NOT NULL DEFAULT 'expense'
);
CREATE TABLE IF NOT EXISTS capabilities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  how_to TEXT,
  tags TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS reminders_sent (
  ref TEXT PRIMARY KEY,
  sent_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT PRIMARY KEY,
  msgs INTEGER NOT NULL DEFAULT 0,
  added INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0
);
"""


_initialized = False


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ledger)")}
    if "kind" not in cols:
        conn.execute(
            "ALTER TABLE ledger ADD COLUMN kind TEXT NOT NULL DEFAULT 'expense'"
        )


def connect() -> sqlite3.Connection:
    global _initialized
    CFG.hub.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CFG.hub.db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    if not _initialized:
        _migrate(conn)
        _initialized = True
    return conn


@contextmanager
def _conn():
    """事务上下文：正常退出提交，异常回滚，无论哪种都关闭连接。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        _migrate(conn)


# ---------- 待办 ----------

def add_todo(title: str, due: str | None = None, priority: int = 0,
             source: str = "manual") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO todos(title, due, priority, source) VALUES(?,?,?,?)",
            (title, due, priority, source))
        return cur.lastrowid  # type: ignore[return-value]


def complete_todo(tid: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE todos SET status='done', done_at=datetime('now','localtime')"
            " WHERE id=? AND status='open'", (tid,))
        return cur.rowcount > 0


def complete_todo_smart(query: str) -> tuple[int, str] | None:
    """智能完成：支持数字 ID、标题子串或关键词模糊匹配。"""
    query = query.strip().lstrip("#")
    if query.isdigit():
        tid = int(query)
        with _conn() as conn:
            row = conn.execute("SELECT id, title FROM todos WHERE id=? AND status='open'", (tid,)).fetchone()
            if row and complete_todo(tid):
                return row["id"], row["title"]
        return None
    with _conn() as conn:
        rows = conn.execute("SELECT id, title FROM todos WHERE status='open' ORDER BY id DESC").fetchall()
        # 1. 严格子串匹配
        for r in rows:
            if query.lower() in r["title"].lower():
                if complete_todo(r["id"]):
                    return r["id"], r["title"]
        # 2. 关键词包含匹配
        for r in rows:
            # 只要 query 里有连续 2 个字以上包含在待办标题里，或待办标题的关键词在 query 里
            if any(len(part) >= 2 and part in r["title"] for part in [query[i:i+2] for i in range(len(query)-1)]):
                if complete_todo(r["id"]):
                    return r["id"], r["title"]
    return None


def delete_smart(query: str) -> tuple[str, str] | None:
    """智能删除：支持数字 ID 或文本模糊匹配（待办、日程、账目）。"""
    query = query.strip().lstrip("#")
    if query.isdigit():
        tid = int(query)
        for fn, label in ((delete_todo, "待办"), (delete_event, "日程"), (delete_ledger, "账目")):
            title = fn(tid)
            if title:
                return label, title
        return None
    # 文本模糊匹配
    with _conn() as conn:
        # 优先在待办中找
        rows = conn.execute("SELECT id, title FROM todos WHERE status='open' ORDER BY id DESC").fetchall()
        for r in rows:
            if query.lower() in r["title"].lower():
                delete_todo(r["id"])
                return "待办", r["title"]
        # 在日程中找
        rows = conn.execute("SELECT id, title FROM events ORDER BY id DESC").fetchall()
        for r in rows:
            if query.lower() in r["title"].lower():
                delete_event(r["id"])
                return "日程", r["title"]
        # 在账本中找
        rows = conn.execute("SELECT id, note, category FROM ledger ORDER BY id DESC").fetchall()
        for r in rows:
            text = (r["note"] or "") + " " + r["category"]
            if query.lower() in text.lower():
                delete_ledger(r["id"])
                return "账目", r["note"] or r["category"]
    return None


def list_todos(status: str = "open") -> list[sqlite3.Row]:
    order = ("CASE WHEN due IS NULL THEN 1 ELSE 0 END, due, priority DESC, id" if status == "open"
             else "done_at DESC, id DESC")
    with _conn() as conn:
        return conn.execute(
            f"SELECT * FROM todos WHERE status=? ORDER BY {order}", (status,)).fetchall()


def overdue_today_open() -> list[sqlite3.Row]:
    today = date.today().isoformat()
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM todos WHERE status='open' AND due IS NOT NULL AND due<=?"
            " ORDER BY due, priority DESC", (today,)).fetchall()


def todo_stats() -> dict[str, int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT"
            " COALESCE(SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),0) AS open_n,"
            " COALESCE(SUM(CASE WHEN status='done' THEN 1 ELSE 0 END),0) AS done_n,"
            " COUNT(*) AS total"
            " FROM todos"
        ).fetchone()
        return {
            "open": int(row["open_n"]),
            "done": int(row["done_n"]),
            "total": int(row["total"]),
        }


# ---------- 日程 ----------

def add_event(title: str, start_at: str, end_at: str | None = None,
              note: str | None = None, source: str = "manual") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO events(title, start_at, end_at, note, source) VALUES(?,?,?,?,?)",
            (title, start_at, end_at, note, source))
        return cur.lastrowid  # type: ignore[return-value]


def events_on(day: str) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE substr(start_at,1,10)=? ORDER BY start_at",
            (day,)).fetchall()


def events_between(dt_from: str, dt_to: str) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE start_at BETWEEN ? AND ? ORDER BY start_at",
            (dt_from, dt_to)).fetchall()


def upcoming_events(days: int = 14) -> list[sqlite3.Row]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d 23:59")
    return events_between(now, end)


def event_stats() -> dict[str, int]:
    today = date.today().isoformat()
    with _conn() as conn:
        today_n = conn.execute(
            "SELECT COUNT(*) FROM events WHERE substr(start_at,1,10)=?",
            (today,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {"today": int(today_n), "total": int(total)}


# ---------- 提醒去重 ----------

def reminder_sent(ref: str) -> bool:
    with _conn() as conn:
        return conn.execute("SELECT 1 FROM reminders_sent WHERE ref=?",
                            (ref,)).fetchone() is not None


def mark_reminder(ref: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO reminders_sent(ref) VALUES(?)", (ref,))


# ---------- 删除 ----------

def delete_todo(tid: int) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT title FROM todos WHERE id=?", (tid,)).fetchone()
        if row:
            conn.execute("DELETE FROM todos WHERE id=?", (tid,))
            return row["title"]
        return None


def delete_event(eid: int) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id=?", (eid,)).fetchone()
        if row:
            conn.execute("DELETE FROM events WHERE id=?", (eid,))
            return row["title"]
        return None


def delete_ledger(lid: int) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT note, amount FROM ledger WHERE id=?", (lid,)).fetchone()
        if row:
            conn.execute("DELETE FROM ledger WHERE id=?", (lid,))
            return f"{row['note']} {row['amount']:g}元"
        return None


# ---------- 用量埋点 ----------

def usage_bump(field: str) -> None:
    sql = {
        "msgs": "INSERT INTO usage(day,msgs) VALUES(date('now','localtime'),1)"
                " ON CONFLICT(day) DO UPDATE SET msgs=msgs+1",
        "added": "INSERT INTO usage(day,added) VALUES(date('now','localtime'),1)"
                 " ON CONFLICT(day) DO UPDATE SET added=added+1",
        "done": "INSERT INTO usage(day,done) VALUES(date('now','localtime'),1)"
                " ON CONFLICT(day) DO UPDATE SET done=done+1",
        "deleted": "INSERT INTO usage(day,deleted) VALUES(date('now','localtime'),1)"
                   " ON CONFLICT(day) DO UPDATE SET deleted=deleted+1",
    }.get(field)
    if sql:
        with _conn() as conn:
            conn.execute(sql)


# ---------- 账目 ----------

def add_ledger(amount: float, category: str = "其他", note: str | None = None,
               occurred_on: str | None = None, source: str = "manual",
               kind: str = "expense") -> int:
    if kind not in ("expense", "income"):
        kind = "expense"
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO ledger(amount, category, note, occurred_on, source, kind)"
            " VALUES(?,?,?,?,?,?)",
            (amount, category, note, occurred_on or date.today().isoformat(), source, kind))
        return cur.lastrowid  # type: ignore[return-value]


def spend_between(day_from: str, day_to: str) -> float:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM ledger"
            " WHERE kind='expense' AND occurred_on BETWEEN ? AND ?",
            (day_from, day_to)).fetchone()
        return float(row["s"])


def income_between(day_from: str, day_to: str) -> float:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM ledger"
            " WHERE kind='income' AND occurred_on BETWEEN ? AND ?",
            (day_from, day_to)).fetchone()
        return float(row["s"])


def list_ledger(limit: int = 40, day_from: str | None = None,
                day_to: str | None = None, kind: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM ledger WHERE 1=1"
    args: list[object] = []
    if day_from:
        sql += " AND occurred_on>=?"
        args.append(day_from)
    if day_to:
        sql += " AND occurred_on<=?"
        args.append(day_to)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY occurred_on DESC, id DESC LIMIT ?"
    args.append(limit)
    with _conn() as conn:
        return conn.execute(sql, args).fetchall()


def ledger_by_category(day_from: str, day_to: str, kind: str = "expense") -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT category, COALESCE(SUM(amount),0) AS s, COUNT(*) AS n"
            " FROM ledger WHERE kind=? AND occurred_on BETWEEN ? AND ?"
            " GROUP BY category ORDER BY s DESC",
            (kind, day_from, day_to)).fetchall()


def ledger_stats() -> dict[str, float]:
    today = date.today()
    iso = today.isoformat()
    month_from = today.replace(day=1).isoformat()
    week_from = (today - timedelta(days=today.weekday())).isoformat()
    with _conn() as conn:
        def _sum(kind: str, d0: str | None = None, d1: str | None = None) -> float:
            sql = "SELECT COALESCE(SUM(amount),0) AS s FROM ledger WHERE kind=?"
            args: list[object] = [kind]
            if d0:
                sql += " AND occurred_on>=?"
                args.append(d0)
            if d1:
                sql += " AND occurred_on<=?"
                args.append(d1)
            return float(conn.execute(sql, args).fetchone()["s"])

        return {
            "today_expense": _sum("expense", iso, iso),
            "week_expense": _sum("expense", week_from, iso),
            "month_expense": _sum("expense", month_from, iso),
            "all_expense": _sum("expense"),
            "today_income": _sum("income", iso, iso),
            "month_income": _sum("income", month_from, iso),
            "all_income": _sum("income"),
        }


def fmt_when(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
