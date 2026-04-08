# -*- coding: utf-8 -*-
"""
N字战法历史回测入口。
"""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

import config
import data_fetcher
import strategy


def _log(message: str) -> None:
    print(message, flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="N字战法历史回测")
    parser.add_argument("--start-date", type=str, help="回测开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="回测结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--months", type=int, default=0, help="按最近 N 个月自动推导回测区间")
    parser.add_argument("--limit", type=int, default=0, help="仅回测前 N 只股票")
    parser.add_argument("--workers", type=int, default=config.MAX_WORKERS, help="并发线程数")
    parser.add_argument("--top", type=int, default=20, help="终端输出前 N 条结果")
    parser.add_argument("--holding-days", type=int, nargs="+", default=[1, 3, 5, 10], help="统计持有天数")
    parser.add_argument("--include-fallback", action="store_true", help="回测时包含候选观察信号")
    parser.add_argument("--progress-every", type=int, default=100, help="每处理 N 只股票打印一次进度")
    parser.add_argument("--detail-output", type=str, default="backtest_trades.csv", help="交易明细输出文件")
    parser.add_argument("--summary-output", type=str, default="backtest_summary.json", help="统计汇总输出文件")
    return parser.parse_args()


def resolve_date_range(args) -> tuple[str, str]:
    if args.start_date and args.end_date:
        return args.start_date, args.end_date
    if args.months > 0:
        end_dt = datetime.now().date()
        start_dt = end_dt - timedelta(days=args.months * 30)
        return start_dt.isoformat(), end_dt.isoformat()
    raise ValueError("请提供 --start-date 和 --end-date，或使用 --months 自动推导区间。")


def _calc_forward_return(df: pd.DataFrame, signal_idx: int, holding_days: int) -> tuple[float | None, str | None]:
    entry_idx = signal_idx + 1
    exit_idx = entry_idx + holding_days - 1
    if exit_idx >= len(df):
        return None, None
    entry_price = float(df.iloc[entry_idx]["open"])
    if entry_price <= 0:
        return None, None
    exit_price = float(df.iloc[exit_idx]["close"])
    exit_date = str(df.iloc[exit_idx]["date"].date())
    return round((exit_price / entry_price - 1) * 100, 2), exit_date


def _calc_excursions(df: pd.DataFrame, signal_idx: int, holding_days: int) -> tuple[float | None, float | None]:
    entry_idx = signal_idx + 1
    exit_idx = entry_idx + holding_days - 1
    if exit_idx >= len(df):
        return None, None
    entry_price = float(df.iloc[entry_idx]["open"])
    if entry_price <= 0:
        return None, None
    window = df.iloc[entry_idx : exit_idx + 1]
    mfe = (float(window["high"].max()) / entry_price - 1) * 100
    mae = (float(window["low"].min()) / entry_price - 1) * 100
    return round(mfe, 2), round(mae, 2)


def _compute_equity_metrics(valid_returns: pd.Series) -> dict:
    if valid_returns.empty:
        return {
            "samples": 0,
            "win_rate_pct": None,
            "avg_return_pct": None,
            "cumulative_return_pct": None,
            "max_drawdown_pct": None,
            "equity_slope_pct_per_trade": None,
        }

    equity = []
    equity_value = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for ret in valid_returns.tolist():
        equity_value *= 1 + ret / 100
        equity.append(equity_value)
        peak = max(peak, equity_value)
        if peak > 0:
            drawdown = equity_value / peak - 1
            max_drawdown = min(max_drawdown, drawdown)

    slope = None
    if len(equity) >= 2:
        x = list(range(len(equity)))
        x_mean = sum(x) / len(x)
        y_mean = sum(equity) / len(equity)
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, equity))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        if denominator > 0:
            slope = numerator / denominator

    return {
        "samples": int(valid_returns.shape[0]),
        "win_rate_pct": round(float((valid_returns > 0).mean() * 100), 2),
        "avg_return_pct": round(float(valid_returns.mean()), 2),
        "cumulative_return_pct": round((equity[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "equity_slope_pct_per_trade": round(slope * 100, 4) if slope is not None else None,
    }


def _build_summary(trades_df: pd.DataFrame, holding_days: list[int]) -> dict:
    summary: dict[str, object] = {
        "total_signals": int(len(trades_df)),
        "formal_signals": int((~trades_df["is_fallback"]).sum()) if not trades_df.empty else 0,
        "fallback_signals": int(trades_df["is_fallback"].sum()) if not trades_df.empty else 0,
        "avg_signal_score": round(float(trades_df["signal_score"].mean()), 2) if not trades_df.empty else 0.0,
        "by_group": {},
        "returns": {},
    }

    if trades_df.empty:
        return summary

    for group_name, group_df in trades_df.groupby("signal_group"):
        summary["by_group"][group_name] = {
            "count": int(len(group_df)),
            "avg_score": round(float(group_df["signal_score"].mean()), 2),
        }

    for holding in holding_days:
        column = f"ret_{holding}d"
        valid = trades_df[column].dropna()
        summary["returns"][f"{holding}d"] = _compute_equity_metrics(valid)

    return summary


def _backtest_single_stock(
    stock: dict,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    holding_days: list[int],
    include_fallback: bool,
    market_env_map: dict[str, dict],
    fetch_days: int,
) -> list[dict]:
    stock_df = data_fetcher.fetch_stock_ohlcv(stock["code"], days=fetch_days)
    if stock_df is None or stock_df.empty or len(stock_df) < 80:
        return []

    enriched_df = strategy.enrich_indicators(stock_df)
    date_strings = enriched_df["date"].dt.strftime("%Y-%m-%d")
    trade_rows: list[dict] = []

    for signal_idx in range(40, len(enriched_df) - max(holding_days)):
        signal_ts = enriched_df.iloc[signal_idx]["date"]
        if signal_ts < start_ts or signal_ts > end_ts:
            continue

        signal_date = date_strings.iloc[signal_idx]
        market_env = market_env_map.get(signal_date)
        if not market_env:
            continue

        result = strategy.find_signal_on_date(
            code=stock["code"],
            name=stock["name"],
            enriched_stock_df=enriched_df,
            signal_date=signal_date,
            market_env=market_env,
        )
        if result is None or result.signal_date != signal_date:
            continue
        if result.is_fallback and not include_fallback:
            continue

        trade = result.__dict__.copy()
        trade["entry_date"] = str(enriched_df.iloc[signal_idx + 1]["date"].date())
        trade["entry_price"] = round(float(enriched_df.iloc[signal_idx + 1]["open"]), 3)

        max_holding = max(holding_days)
        mfe, mae = _calc_excursions(enriched_df, signal_idx, max_holding)
        trade["mfe_pct"] = mfe
        trade["mae_pct"] = mae

        for holding in holding_days:
            ret, exit_date = _calc_forward_return(enriched_df, signal_idx, holding)
            trade[f"ret_{holding}d"] = ret
            trade[f"exit_{holding}d"] = exit_date

        trade_rows.append(trade)

    return trade_rows


def run_backtest(
    start_date: str,
    end_date: str,
    limit: int = 0,
    workers: int = config.MAX_WORKERS,
    holding_days: list[int] | None = None,
    include_fallback: bool = False,
    progress_every: int = 100,
) -> tuple[pd.DataFrame, dict]:
    if holding_days is None:
        holding_days = [1, 3, 5, 10]

    start_clock = time.perf_counter()
    stock_list = data_fetcher.get_stock_list()
    if limit > 0:
        stock_list = stock_list.head(limit).copy()

    index_df = data_fetcher.fetch_index_daily(days=max(config.HISTORY_DAYS, 800))
    if index_df is None or index_df.empty:
        raise RuntimeError("未获取到上证指数数据，无法执行回测。")

    market_env_map = strategy.build_market_environment_map(index_df)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    fetch_days = max(config.HISTORY_DAYS, 800)
    trade_rows: list[dict] = []
    processed = 0

    _log(
        f"开始回测: 区间 {start_date} 至 {end_date} | "
        f"股票数 {len(stock_list)} | 并发 {workers} | "
        f"{'包含候选观察' if include_fallback else '仅正式命中'}"
    )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _backtest_single_stock,
                stock=row.to_dict(),
                start_ts=start_ts,
                end_ts=end_ts,
                holding_days=holding_days,
                include_fallback=include_fallback,
                market_env_map=market_env_map,
                fetch_days=fetch_days,
            ): row["code"]
            for _, row in stock_list.iterrows()
        }

        for future in as_completed(futures):
            processed += 1
            rows = future.result()
            if rows:
                trade_rows.extend(rows)

            if processed % progress_every == 0 or processed == len(futures):
                elapsed = round(time.perf_counter() - start_clock, 1)
                _log(
                    f"进度: {processed}/{len(futures)} | "
                    f"累计信号 {len(trade_rows)} | "
                    f"耗时 {elapsed}s"
                )

    trades_df = pd.DataFrame(trade_rows)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["signal_date", "signal_score"], ascending=[True, False]).reset_index(drop=True)

    summary = _build_summary(trades_df, holding_days)
    summary["start_date"] = start_date
    summary["end_date"] = end_date
    summary["include_fallback"] = include_fallback
    summary["scanned_stocks"] = int(len(stock_list))
    summary["workers"] = workers
    summary["elapsed_seconds"] = round(time.perf_counter() - start_clock, 2)
    return trades_df, summary


def print_summary(summary: dict, trades_df: pd.DataFrame, top: int) -> None:
    _log(f"回测区间: {summary['start_date']} 至 {summary['end_date']}")
    _log(f"扫描股票: {summary['scanned_stocks']} 只")
    _log(f"并发线程: {summary['workers']}")
    _log(f"运行耗时: {summary['elapsed_seconds']} 秒")
    _log(f"信号总数: {summary['total_signals']} 只")
    _log(f"正式命中: {summary['formal_signals']} 只")
    _log(f"候选观察: {summary['fallback_signals']} 只")
    _log(f"平均评分: {summary['avg_signal_score']}")

    _log("收益统计:")
    for label, stats in summary["returns"].items():
        _log(
            f"- {label}: 样本 {stats['samples']} | "
            f"胜率 {stats['win_rate_pct']}% | "
            f"平均收益 {stats['avg_return_pct']}% | "
            f"累计收益 {stats['cumulative_return_pct']}% | "
            f"斜率 {stats['equity_slope_pct_per_trade']} | "
            f"最大回撤 {stats['max_drawdown_pct']}%"
        )

    if trades_df.empty:
        _log("没有生成可用于回测的历史信号。")
        return

    _log("样例信号:")
    display_cols = [col for col in ["ret_1d", "ret_3d", "ret_5d", "ret_10d"] if col in trades_df.columns]
    for _, row in trades_df.head(top).iterrows():
        ret_parts = " | ".join(f"{col}={row[col]}" for col in display_cols)
        _log(
            f"- {row['signal_date']} {row['code']} {row['name']} | "
            f"{'候选观察' if row['is_fallback'] else '正式命中'} | "
            f"{row['signal_group']} | 分数 {row['signal_score']} | {ret_parts}"
        )


if __name__ == "__main__":
    args = parse_args()
    start_date, end_date = resolve_date_range(args)
    trades_df, summary = run_backtest(
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        workers=args.workers,
        holding_days=args.holding_days,
        include_fallback=args.include_fallback,
        progress_every=args.progress_every,
    )

    if not trades_df.empty:
        trades_df.to_csv(args.detail_output, index=False, encoding="utf-8-sig")
    with open(args.summary_output, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print_summary(summary, trades_df, top=args.top)
