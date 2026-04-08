"""
底部十字星 + 缩量回调 N 字突破策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

import config


@dataclass
class SignalResult:
    code: str
    name: str
    signal_date: str
    market_passed: bool
    doji_date: str
    surge_date: str
    breakout_price: float
    breakout_gain_pct: float
    breakout_volume_ratio_vs_5ma: float
    pullback_days: int
    pullback_volume_ratio: float
    strong_volume_breakout: bool
    market_reason: str
    doji_reason: str
    surge_reason: str
    pullback_reason: str
    breakout_reason: str
    notes: str


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy().sort_values("date").reset_index(drop=True)
    result["vol_ma5"] = result["volume"].rolling(5).mean()
    result["close_ma20"] = result["close"].rolling(config.MARKET_MA_PERIOD).mean()
    result["prev_close"] = result["close"].shift(1)
    result["daily_gain_pct"] = (result["close"] / result["prev_close"] - 1) * 100
    return result


def check_market_environment(index_df: pd.DataFrame) -> dict:
    df = enrich_indicators(index_df)
    latest = df.iloc[-1]
    above_ma20 = bool(latest["close"] > latest["close_ma20"]) if pd.notna(latest["close_ma20"]) else False
    gain_gt_1 = bool(latest["daily_gain_pct"] > config.MARKET_DAILY_GAIN_PCT) if pd.notna(latest["daily_gain_pct"]) else False
    return {
        "passed": above_ma20 or gain_gt_1,
        "above_ma20": above_ma20,
        "gain_gt_1pct": gain_gt_1,
        "signal_date": str(latest["date"].date()),
    }


def _is_doji_like(row: pd.Series) -> bool:
    amplitude = row["high"] - row["low"]
    if amplitude <= 0:
        return False
    body = abs(row["close"] - row["open"])
    upper_shadow = row["high"] - max(row["open"], row["close"])
    lower_shadow = min(row["open"], row["close"]) - row["low"]
    if upper_shadow < 0 or lower_shadow < 0:
        return False
    shadow_gap = abs(upper_shadow - lower_shadow)
    return (
        body <= amplitude * config.DOJI_BODY_TO_RANGE_MAX
        and shadow_gap <= amplitude * config.DOJI_SHADOW_SIMILARITY_MAX
    )


def _calc_drop_pct(window: pd.DataFrame) -> Optional[float]:
    if window.empty:
        return None
    start_price = window["close"].iloc[0]
    end_price = window["close"].iloc[-1]
    if start_price <= 0:
        return None
    return (end_price / start_price - 1) * 100


def find_signal(code: str, name: str, stock_df: pd.DataFrame, market_env: dict) -> Optional[SignalResult]:
    if stock_df is None or stock_df.empty or len(stock_df) < 40:
        return None
    if not market_env.get("passed", False):
        return None

    df = enrich_indicators(stock_df)
    today_idx = len(df) - 1
    doji_start = max(0, today_idx - config.DOJI_LOOKBACK_MAX)
    doji_end = today_idx - config.DOJI_LOOKBACK_MIN
    if doji_end <= doji_start:
        return None

    for doji_idx in range(doji_end, doji_start - 1, -1):
        doji = df.iloc[doji_idx]
        if not _is_doji_like(doji):
            continue
        pre_window_start = max(0, doji_idx - config.PREV_DROP_LOOKBACK + 1)
        pre_window = df.iloc[pre_window_start : doji_idx + 1]
        drop_pct = _calc_drop_pct(pre_window)
        if drop_pct is None or drop_pct > config.PREV_DROP_THRESHOLD:
            continue
        if pd.isna(doji["vol_ma5"]) or doji["volume"] >= doji["vol_ma5"]:
            continue

        surge_idx = doji_idx + 1
        if surge_idx >= today_idx:
            continue
        surge = df.iloc[surge_idx]
        if surge["daily_gain_pct"] <= config.SURGE_GAIN_PCT:
            continue
        if pd.isna(surge["vol_ma5"]) or surge["volume"] / surge["vol_ma5"] <= config.SURGE_VOLUME_RATIO:
            continue

        pullback_start = surge_idx + 1
        pullback_end = today_idx - 1
        pullback_days = pullback_end - pullback_start + 1
        if pullback_days < config.PULLBACK_DAYS_MIN or pullback_days > config.PULLBACK_DAYS_MAX:
            continue

        pullback_df = df.iloc[pullback_start : pullback_end + 1].copy()
        if pullback_df.empty:
            continue
        if pullback_df["low"].min() < doji["low"]:
            continue

        min_pullback_volume = pullback_df["volume"].min()
        if min_pullback_volume >= surge["volume"] * config.PULLBACK_VOLUME_SHRINK:
            continue

        if not (df.iloc[today_idx]["close"] > surge["high"]):
            continue
        today = df.iloc[today_idx]
        yesterday = df.iloc[today_idx - 1]
        if today["volume"] <= yesterday["volume"]:
            continue
        if pd.isna(today["vol_ma5"]) or today["volume"] <= today["vol_ma5"]:
            continue

        pullback_avg_volume = pullback_df["volume"].mean()
        strong_volume_breakout = bool(today["volume"] >= pullback_avg_volume * config.BREAKOUT_PULLBACK_VOLUME_MULTIPLIER)

        notes = []
        if min_pullback_volume < pullback_df["vol_ma5"].fillna(float("inf")).min():
            notes.append("回调最低量低于阶段5日均量")
        if strong_volume_breakout:
            notes.append("突破量能达到回调均量2倍以上")

        market_reason = (
            f"大盘过滤通过：上证指数信号日 {market_env['signal_date']}，"
            f"MA20之上={market_env['above_ma20']}，单日涨幅>1%={market_env['gain_gt_1pct']}"
        )
        doji_reason = (
            f"十字星日期 {str(doji['date'].date())}，前{config.PREV_DROP_LOOKBACK}日跌幅 {round(float(drop_pct), 2)}%，"
            f"当日成交量 {int(doji['volume'])} 低于5日均量 {int(doji['vol_ma5'])}"
        )
        surge_reason = (
            f"启动阳线日期 {str(surge['date'].date())}，涨幅 {round(float(surge['daily_gain_pct']), 2)}%，"
            f"量比5日均量 {round(float(surge['volume'] / surge['vol_ma5']), 2)} 倍"
        )
        pullback_reason = (
            f"回调 {pullback_days} 天，最低价 {round(float(pullback_df['low'].min()), 3)} 未跌破十字星低点 {round(float(doji['low']), 3)}；"
            f"最小成交量/启动量 = {round(float(min_pullback_volume / surge['volume']), 3)}"
        )
        breakout_reason = (
            f"当前收盘 {round(float(today['close']), 3)} 突破启动高点 {round(float(surge['high']), 3)}；"
            f"当日量能较昨日放大且高于5日均量，量比5日均量 {round(float(today['volume'] / today['vol_ma5']), 2)}"
        )

        return SignalResult(
            code=code,
            name=name,
            signal_date=str(today["date"].date()),
            market_passed=True,
            doji_date=str(doji["date"].date()),
            surge_date=str(surge["date"].date()),
            breakout_price=round(float(today["close"]), 3),
            breakout_gain_pct=round(float(today["daily_gain_pct"]), 2),
            breakout_volume_ratio_vs_5ma=round(float(today["volume"] / today["vol_ma5"]), 2),
            pullback_days=pullback_days,
            pullback_volume_ratio=round(float(min_pullback_volume / surge["volume"]), 3),
            strong_volume_breakout=strong_volume_breakout,
            market_reason=market_reason,
            doji_reason=doji_reason,
            surge_reason=surge_reason,
            pullback_reason=pullback_reason,
            breakout_reason=breakout_reason,
            notes="；".join(notes) if notes else "满足基础N字突破条件",
        )

    return None
