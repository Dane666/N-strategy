"""
N字战法 + KDJ J值超卖策略。
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
    bottom_region_passed: bool
    pattern_date: str
    surge_date: str
    signal_price: float
    signal_gain_pct: float
    signal_volume_ratio_vs_5ma: float
    pullback_days: int
    pullback_volume_ratio: float
    j_turn_up: bool
    oversold_triggered: bool
    candle_pattern: str
    oversold_level: str
    signal_score: int
    signal_group: str
    is_fallback: bool
    fallback_reason: str
    market_reason: str
    bottom_reason: str
    surge_reason: str
    pullback_reason: str
    trigger_reason: str
    notes: str


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy().sort_values("date").reset_index(drop=True)
    result["vol_ma5"] = result["volume"].rolling(5).mean()
    result["close_ma20"] = result["close"].rolling(config.MARKET_MA_PERIOD).mean()
    result["prev_close"] = result["close"].shift(1)
    result["daily_gain_pct"] = (result["close"] / result["prev_close"] - 1) * 100
    result["low_n"] = result["low"].rolling(config.KDJ_LOOKBACK).min()
    result["high_n"] = result["high"].rolling(config.KDJ_LOOKBACK).max()
    rsv_base = (result["high_n"] - result["low_n"]).replace(0, pd.NA)
    result["rsv"] = ((result["close"] - result["low_n"]) / rsv_base * 100).fillna(50.0)
    result["k"] = result["rsv"].ewm(
        alpha=1 / config.KDJ_SMOOTH_K,
        adjust=False,
    ).mean()
    result["d"] = result["k"].ewm(
        alpha=1 / config.KDJ_SMOOTH_D,
        adjust=False,
    ).mean()
    result["j"] = 3 * result["k"] - 2 * result["d"]
    result["low_60"] = result["low"].rolling(config.BOTTOM_REGION_LOOKBACK).min()
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


def _is_hammer_like(row: pd.Series) -> bool:
    amplitude = row["high"] - row["low"]
    if amplitude <= 0:
        return False
    body = abs(row["close"] - row["open"])
    upper_shadow = row["high"] - max(row["open"], row["close"])
    lower_shadow = min(row["open"], row["close"]) - row["low"]
    return (
        body <= amplitude * config.DOJI_BODY_TO_RANGE_MAX
        and lower_shadow >= amplitude * config.HAMMER_LOWER_SHADOW_MIN
        and upper_shadow <= amplitude * 0.25
    )


def _is_bottom_reversal_candle(row: pd.Series) -> bool:
    return _is_doji_like(row) or _is_hammer_like(row)


def _calc_drop_pct(window: pd.DataFrame) -> Optional[float]:
    if window.empty:
        return None
    start_price = window["close"].iloc[0]
    end_price = window["close"].iloc[-1]
    if start_price <= 0:
        return None
    return (end_price / start_price - 1) * 100


def _is_bottom_region(df: pd.DataFrame, idx: int) -> tuple[bool, str]:
    window_start = max(0, idx - config.PREV_DROP_LOOKBACK + 1)
    recent_drop = _calc_drop_pct(df.iloc[window_start : idx + 1])
    row = df.iloc[idx]
    if pd.notna(row.get("low_60")) and row["low_60"] > 0:
        distance_to_low = (row["close"] - row["low_60"]) / row["low_60"]
        if distance_to_low <= config.BOTTOM_REGION_BUFFER:
            return True, f"股价位于{config.BOTTOM_REGION_LOOKBACK}日低点上方 {round(distance_to_low * 100, 2)}%"
    if recent_drop is not None and recent_drop <= config.PREV_DROP_THRESHOLD:
        return True, f"近{config.PREV_DROP_LOOKBACK}日跌幅 {round(recent_drop, 2)}%"
    return False, "未处于长期下跌后的底部区域"


def _build_signal_score(
    oversold_row: pd.Series,
    pattern_name: str,
    pullback_days: int,
    pullback_volume_ratio: float,
    market_passed: bool,
    bottom_region_passed: bool,
    today_volume_ratio: float,
) -> tuple[int, str, str]:
    score = 0
    oversold_level = "J<10且K<20"
    if oversold_row["j"] < config.J_OVERSOLD_THRESHOLD:
        score += 35
        oversold_level = "J<0"
    else:
        score += 20

    if pattern_name == "锤头线":
        score += 15
    else:
        score += 10

    if pullback_volume_ratio <= 0.33:
        score += 20
    elif pullback_volume_ratio <= 0.5:
        score += 12

    if pullback_days in (2, 3):
        score += 10
    else:
        score += 6

    if market_passed:
        score += 10
    if bottom_region_passed:
        score += 5

    if today_volume_ratio >= 1.5:
        score += 10
    elif today_volume_ratio >= 1.1:
        score += 5

    if score >= 80:
        signal_group = "A档强信号"
    elif score >= 65:
        signal_group = "B档观察"
    else:
        signal_group = "C档埋伏"
    return score, signal_group, oversold_level


def find_signal(code: str, name: str, stock_df: pd.DataFrame, market_env: dict) -> Optional[SignalResult]:
    if stock_df is None or stock_df.empty or len(stock_df) < 40:
        return None

    df = enrich_indicators(stock_df)
    today_idx = len(df) - 1
    today = df.iloc[today_idx]
    yesterday = df.iloc[today_idx - 1]
    market_passed = bool(market_env.get("passed", False))
    bottom_region_passed, bottom_region_text = _is_bottom_region(df, today_idx)

    if not market_passed and not bottom_region_passed:
        return None

    surge_start = max(1, today_idx - config.SURGE_LOOKBACK_DAYS)
    surge_end = today_idx - config.PULLBACK_DAYS_MIN - 1
    if surge_end < surge_start:
        return None

    best_candidate: Optional[SignalResult] = None

    for surge_idx in range(surge_end, surge_start - 1, -1):
        surge = df.iloc[surge_idx]
        if surge["daily_gain_pct"] <= config.SURGE_GAIN_PCT:
            continue
        if pd.isna(surge["vol_ma5"]) or surge["vol_ma5"] <= 0:
            continue
        surge_volume_ratio = surge["volume"] / surge["vol_ma5"]
        if surge_volume_ratio <= config.SURGE_VOLUME_RATIO:
            continue

        pullback_start = surge_idx + 1
        pullback_end = today_idx - 1
        pullback_days = pullback_end - pullback_start + 1
        if pullback_days < config.PULLBACK_DAYS_MIN or pullback_days > config.PULLBACK_DAYS_MAX:
            continue
        pullback_df = df.iloc[pullback_start : pullback_end + 1].copy()
        if pullback_df.empty:
            continue

        # J值超卖判定：J < 0，或者 J < 10 且 K < 20
        oversold_mask = (
            (pullback_df["j"] < config.J_OVERSOLD_THRESHOLD)
            | (
                (pullback_df["j"] < config.J_LOW_THRESHOLD)
                & (pullback_df["k"] < config.K_LOW_THRESHOLD)
            )
        )
        if not oversold_mask.any():
            continue

        oversold_indices = pullback_df.index[oversold_mask].tolist()
        pattern_idx = None
        oversold_idx = None
        for candidate_idx in oversold_indices:
            if _is_bottom_reversal_candle(df.iloc[candidate_idx]):
                pattern_idx = candidate_idx
                oversold_idx = candidate_idx
                break
            if candidate_idx + 1 <= pullback_end and _is_bottom_reversal_candle(df.iloc[candidate_idx + 1]):
                pattern_idx = candidate_idx + 1
                oversold_idx = candidate_idx
                break
        if pattern_idx is None:
            continue

        pattern_row = df.iloc[pattern_idx]
        pattern_name = "十字星" if _is_doji_like(pattern_row) else "锤头线"

        # 缩量十字星/锤头判定：形态日成交量小于第一笔大阳线一半，或小于5日均量
        pattern_volume_ok = (
            pattern_row["volume"] < surge["volume"] * config.PULLBACK_VOLUME_SHRINK
            or (pd.notna(pattern_row["vol_ma5"]) and pattern_row["volume"] < pattern_row["vol_ma5"])
        )
        if not pattern_volume_ok:
            continue

        if not (pullback_df["volume"].min() < surge["volume"] * config.PULLBACK_VOLUME_SHRINK
                or (pullback_df["volume"] < pullback_df["vol_ma5"]).any()):
            continue

        trigger_price_up = bool(today["close"] > yesterday["close"])
        trigger_j_up = bool(today["j"] > yesterday["j"])
        trigger_volume_up = bool(today["volume"] > yesterday["volume"])

        min_pullback_volume = pullback_df["volume"].min()
        pullback_volume_ratio = float(min_pullback_volume / surge["volume"])
        oversold_row = df.iloc[oversold_idx]
        oversold_triggered = bool(
            oversold_row["j"] < config.J_OVERSOLD_THRESHOLD
            or (
                oversold_row["j"] < config.J_LOW_THRESHOLD
                and oversold_row["k"] < config.K_LOW_THRESHOLD
            )
        )
        today_volume_ratio = (
            float(today["volume"] / today["vol_ma5"])
            if pd.notna(today["vol_ma5"]) and today["vol_ma5"] > 0
            else 0.0
        )
        signal_score, signal_group, oversold_level = _build_signal_score(
            oversold_row=oversold_row,
            pattern_name=pattern_name,
            pullback_days=pullback_days,
            pullback_volume_ratio=pullback_volume_ratio,
            market_passed=market_passed,
            bottom_region_passed=bottom_region_passed,
            today_volume_ratio=today_volume_ratio,
        )

        missing_triggers = []
        if not trigger_price_up:
            missing_triggers.append("今日未收阳")
            signal_score -= 12
        if not trigger_j_up:
            missing_triggers.append("J值未拐头向上")
            signal_score -= 15
        if not trigger_volume_up:
            missing_triggers.append("今日量能未高于昨日")
            signal_score -= 10
        signal_score = max(signal_score, 1)

        if signal_score >= 80:
            signal_group = "A档强信号"
        elif signal_score >= 65:
            signal_group = "B档观察"
        else:
            signal_group = "C档埋伏"

        notes = []
        if oversold_row["j"] < config.J_OVERSOLD_THRESHOLD:
            notes.append("J值进入负值超卖区")
        else:
            notes.append("J<10 且 K<20，处于低位超卖区")
        if _is_doji_like(pattern_row):
            notes.append("超卖日或次日出现缩量十字星")
        elif _is_hammer_like(pattern_row):
            notes.append("超卖日或次日出现缩量锤头线")
        notes.append(f"综合评分 {signal_score}，分组 {signal_group}")

        market_reason = (
            f"大盘过滤：上证指数信号日 {market_env['signal_date']}，"
            f"MA20之上={market_env['above_ma20']}，单日涨幅>1%={market_env['gain_gt_1pct']}"
        )
        bottom_reason = (
            f"个股底部过滤：{bottom_region_text}"
        )
        surge_reason = (
            f"启动阳线日期 {str(surge['date'].date())}，涨幅 {round(float(surge['daily_gain_pct']), 2)}%，"
            f"量比5日均量 {round(float(surge_volume_ratio), 2)} 倍"
        )
        pullback_reason = (
            f"回调 {pullback_days} 天；J值超卖日 {str(oversold_row['date'].date())}，J={round(float(oversold_row['j']), 2)}，"
            f"K={round(float(oversold_row['k']), 2)}；形态确认日 {str(pattern_row['date'].date())} 为{pattern_name}，"
            f"最小成交量/启动量 = {round(float(pullback_volume_ratio), 3)}"
        )
        trigger_reason = (
            f"今日收盘 {round(float(today['close']), 3)} 高于昨日收盘 {round(float(yesterday['close']), 3)}，"
            f"J值 {round(float(today['j']), 2)} > 昨日 {round(float(yesterday['j']), 2)}，"
            f"成交量 {int(today['volume'])} > 昨日 {int(yesterday['volume'])}"
        )

        result = SignalResult(
            code=code,
            name=name,
            signal_date=str(today["date"].date()),
            market_passed=market_passed,
            bottom_region_passed=bottom_region_passed,
            pattern_date=str(pattern_row["date"].date()),
            surge_date=str(surge["date"].date()),
            signal_price=round(float(today["close"]), 3),
            signal_gain_pct=round(float(today["daily_gain_pct"]), 2),
            signal_volume_ratio_vs_5ma=round(today_volume_ratio, 2),
            pullback_days=pullback_days,
            pullback_volume_ratio=round(pullback_volume_ratio, 3),
            j_turn_up=bool(today["j"] > yesterday["j"]),
            oversold_triggered=oversold_triggered,
            candle_pattern=pattern_name,
            oversold_level=oversold_level,
            signal_score=signal_score,
            signal_group=signal_group,
            is_fallback=False,
            fallback_reason="",
            market_reason=market_reason if market_passed else "大盘未站上MA20，依赖个股底部区域信号",
            bottom_reason=bottom_reason,
            surge_reason=surge_reason,
            pullback_reason=pullback_reason,
            trigger_reason=trigger_reason,
            notes="；".join(notes) if notes else "满足基础KDJ超卖N字反转条件",
        )

        if trigger_price_up and trigger_j_up and trigger_volume_up:
            return result

        candidate = SignalResult(
            **{
                **result.__dict__,
                "is_fallback": True,
                "fallback_reason": "；".join(missing_triggers) if missing_triggers else "触发条件略弱",
                "trigger_reason": (
                    f"候选观察：收阳={trigger_price_up}，J拐头={trigger_j_up}，量能放大={trigger_volume_up}"
                ),
                "notes": result.notes + "；当前作为候选观察返回",
            }
        )
        if best_candidate is None or candidate.signal_score > best_candidate.signal_score:
            best_candidate = candidate

    return best_candidate
