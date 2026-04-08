"""
SQLite 缓存模块。
"""

import sqlite3
from contextlib import contextmanager
from threading import Lock

import config

_write_lock = Lock()


def get_db_path() -> str:
    return config.DB_PATH


@contextmanager
def get_connection(readonly: bool = False):
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS kline_cache (
            code TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            change_pct REAL,
            PRIMARY KEY (code, trade_date)
        )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS index_cache (
            code TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            change_pct REAL,
            PRIMARY KEY (code, trade_date)
        )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS stock_list_cache (
            code TEXT PRIMARY KEY,
            name TEXT,
            updated_at TEXT
        )"""
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_code ON kline_cache(code)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_index_code ON index_cache(code)")
