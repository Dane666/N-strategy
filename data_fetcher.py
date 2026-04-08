# -*- coding: utf-8 -*-
"""
参考 ma_scanner 的数据获取方式：
1. 腾讯接口抓取 K 线
2. SQLite 做增量缓存
3. 股票列表优先复用腾讯行情接口，东财仅兜底
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

# 必须在 requests 前导入，避免系统代理干扰数据抓取
import proxy_guard  # noqa: F401

import pandas as pd
import requests

import config
import db as cache_db

cache_db.init_db()
ALT_DB_PATHS = [
    os.path.join("/Users/admin/Documents/codeHub/ma_scanner", "ma_scanner.db"),
]


def _get_exchange_prefix(code: str) -> str:
    if code.startswith(("6", "5")):
        return "sh"
    if code.startswith(("0", "1", "3")):
        return "sz"
    return "sh"


def _fetch_kline_tencent(code: str, count: int = 500, is_index: bool = False) -> Optional[pd.DataFrame]:
    try:
        if is_index:
            prefix = "sh" if code in ("000001", "000016", "000300") else "sz"
        else:
            prefix = _get_exchange_prefix(code)

        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={prefix}{code},day,,,{count},qfq"
        )
        response = requests.get(url, headers={"Referer": "https://gu.qq.com/"}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        symbol = f"{prefix}{code}"
        raw = payload.get("data", {}).get(symbol, {}).get("day", [])
        if not raw:
            raw = payload.get("data", {}).get(symbol, {}).get("qfqday", [])
        if not raw:
            return None

        rows = []
        prev_close = None
        for item in raw:
            if len(item) < 6:
                continue
            close_price = float(item[2])
            volume = float(item[5]) * 100
            change_pct = 0.0
            if prev_close and prev_close > 0:
                change_pct = (close_price - prev_close) / prev_close * 100
            rows.append(
                {
                    "date": pd.to_datetime(item[0]),
                    "open": float(item[1]),
                    "close": close_price,
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": volume,
                    "amount": volume * close_price,
                    "change_pct": change_pct,
                }
            )
            prev_close = close_price

        if not rows:
            return None
        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def _normalize_loaded_kline(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df.empty:
        return None
    df = df.rename(columns={"trade_date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop(columns=["code"], errors="ignore")
    return df


def _load_kline_from_sqlite(db_path: str, table: str, code: str, min_date: Optional[str] = None) -> Optional[pd.DataFrame]:
    try:
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            if min_date:
                query = (
                    f"SELECT * FROM {table} WHERE code=? AND trade_date>=? "
                    "ORDER BY trade_date"
                )
                df = pd.read_sql_query(query, conn, params=(code, min_date))
            else:
                query = f"SELECT * FROM {table} WHERE code=? ORDER BY trade_date"
                df = pd.read_sql_query(query, conn, params=(code,))
        return _normalize_loaded_kline(df)
    except Exception:
        return None


def _load_kline_from_db(table: str, code: str, min_date: Optional[str] = None) -> Optional[pd.DataFrame]:
    primary = _load_kline_from_sqlite(config.DB_PATH, table, code, min_date)
    if primary is not None and not primary.empty:
        return primary
    for db_path in ALT_DB_PATHS:
        if not os.path.exists(db_path):
            continue
        cached = _load_kline_from_sqlite(db_path, table, code, min_date)
        if cached is not None and not cached.empty:
            return cached
    return None


def _save_kline_to_db(table: str, code: str, df: pd.DataFrame):
    if df is None or df.empty:
        return
    save_df = df.copy()
    save_df["trade_date"] = save_df["date"].dt.strftime("%Y-%m-%d")
    save_df = save_df.drop(columns=["date"])
    save_df["code"] = code
    columns = ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "change_pct"]

    with cache_db._write_lock:
        with cache_db.get_connection() as conn:
            for trade_date in save_df["trade_date"].unique():
                conn.execute(f"DELETE FROM {table} WHERE code=? AND trade_date=?", (code, trade_date))
            save_df[columns].to_sql(table, conn, if_exists="append", index=False)


def _needs_refresh(cached_df: Optional[pd.DataFrame]) -> bool:
    if cached_df is None or cached_df.empty:
        return True
    last_date = cached_df["date"].iloc[-1]
    if hasattr(last_date, "date"):
        last_date = last_date.date()
    return last_date < datetime.today().date()


def _save_stock_list_to_db(df: pd.DataFrame):
    save_df = df.copy().drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
    save_df["updated_at"] = datetime.now().isoformat()
    with cache_db._write_lock:
        with cache_db.get_connection() as conn:
            conn.execute("DELETE FROM stock_list_cache")
            save_df.to_sql("stock_list_cache", conn, if_exists="append", index=False)


def _load_cached_stock_codes() -> list[str]:
    code_sources = [config.DB_PATH, os.path.join("/Users/admin/Documents/codeHub/ma_scanner", "ma_scanner.db")]
    codes: list[str] = []
    for db_path in code_sources:
        if not os.path.exists(db_path):
            continue
        try:
            import sqlite3

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("SELECT DISTINCT code FROM kline_cache ORDER BY code").fetchall()
                codes.extend(row[0] for row in rows if row and row[0])
        except Exception:
            continue
    return sorted(set(codes))


def _build_candidate_codes() -> list[str]:
    candidates = set(_load_cached_stock_codes())
    for prefix in ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688"):
        upper = 1000 if prefix in {"688"} else 1000
        for num in range(upper):
            candidates.add(f"{prefix}{num:03d}")
    return sorted(candidates)


def _fetch_stock_list_tencent(codes: list[str]) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame(columns=["code", "name"])

    rows = []
    batch_size = 80
    for start in range(0, len(codes), batch_size):
        batch = codes[start : start + batch_size]
        symbols = ",".join(f"{_get_exchange_prefix(code)}{code}" for code in batch)
        try:
            response = requests.get(
                f"http://qt.gtimg.cn/q={symbols}",
                headers={"Referer": "https://gu.qq.com/"},
                timeout=12,
            )
            response.raise_for_status()
        except Exception:
            time.sleep(0.15)
            continue

        for line in response.text.strip().splitlines():
            if "=" not in line:
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip(";")
            if not value:
                continue
            fields = value.split("~")
            if len(fields) < 3:
                continue
            name = fields[1].strip()
            code = fields[2].strip()
            if len(code) != 6 or not code.isdigit() or not name or name == "N/A":
                continue
            rows.append({"code": code, "name": name})
        time.sleep(0.15)

    return pd.DataFrame(rows, columns=["code", "name"]).drop_duplicates(subset=["code"], keep="first")


def _fetch_stock_list_eastmoney() -> pd.DataFrame:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }
    rows = []
    for page in range(1, 80):
        params = {
            "pn": str(page),
            "pz": "100",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23",
            "fields": "f12,f14",
        }
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            diff = response.json().get("data", {}).get("diff", [])
        except Exception:
            break
        if not diff:
            break
        if isinstance(diff, list):
            rows.extend({"code": item["f12"], "name": item["f14"]} for item in diff if item.get("f12"))
            if len(diff) < 100:
                break
        elif isinstance(diff, dict):
            rows.extend(
                {"code": item["f12"], "name": item["f14"]}
                for item in diff.values()
                if item.get("f12")
            )
            if len(diff) < 100:
                break
        else:
            break
        time.sleep(0.1)
    return pd.DataFrame(rows, columns=["code", "name"]).drop_duplicates(subset=["code"], keep="first")


def get_stock_list() -> pd.DataFrame:
    try:
        with cache_db.get_connection(readonly=True) as conn:
            check = pd.read_sql_query("SELECT updated_at FROM stock_list_cache LIMIT 1", conn)
            if not check.empty:
                updated = datetime.fromisoformat(check["updated_at"].iloc[0])
                if (datetime.now() - updated).total_seconds() < config.STOCK_LIST_CACHE_TTL:
                    return pd.read_sql_query("SELECT code, name FROM stock_list_cache", conn)
    except Exception:
        pass

    df = _fetch_stock_list_tencent(_build_candidate_codes())
    if df.empty:
        df = _fetch_stock_list_eastmoney()
    if not df.empty:
        _save_stock_list_to_db(df)
    return df


def fetch_stock_ohlcv(code: str, days: Optional[int] = None) -> Optional[pd.DataFrame]:
    if days is None:
        days = config.HISTORY_DAYS
    min_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    cached = _load_kline_from_db("kline_cache", code, min_date)
    if cached is not None and not _needs_refresh(cached):
        return cached

    for attempt in range(config.MAX_RETRY + 1):
        df = _fetch_kline_tencent(code, count=500, is_index=False)
        if df is not None and not df.empty:
            _save_kline_to_db("kline_cache", code, df)
            return df[df["date"] >= pd.Timestamp(min_date)].reset_index(drop=True)
        if attempt < config.MAX_RETRY:
            time.sleep(0.5 + attempt)
    return cached


def fetch_index_daily(symbol: Optional[str] = None, days: Optional[int] = None) -> Optional[pd.DataFrame]:
    if symbol is None:
        symbol = config.MARKET_INDEX_CODE
    if days is None:
        days = config.HISTORY_DAYS
    min_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    cached = _load_kline_from_db("index_cache", symbol, min_date)
    if cached is not None and not _needs_refresh(cached):
        return cached

    for attempt in range(config.MAX_RETRY + 1):
        df = _fetch_kline_tencent(symbol, count=500, is_index=True)
        if df is not None and not df.empty:
            _save_kline_to_db("index_cache", symbol, df)
            return df[df["date"] >= pd.Timestamp(min_date)].reset_index(drop=True)
        if attempt < config.MAX_RETRY:
            time.sleep(0.5 + attempt)
    return cached
