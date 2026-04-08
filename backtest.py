# -*- coding: utf-8 -*-
"""
N字战法历史回测入口。
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

import config
import data_fetcher
import strategy


def parse_args():
    parser = argparse.ArgumentParser(description="N字战法历史回测")
    parser.add_argument("--start-date", type=str, required=True, help="回测开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="回测结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="仅回测前 N 只股票")
    parser.add_argument("--top", type=int, default=20, help="终端输出前 N 条结果")
    parser.add_argument("--holding-days", type=int, nargs="+", default=[1, 3, 5, 10], help="统计持有天数")
    parser.add_argument("--include-fallback", action="store_true", help="回测时包含候选观察信号")
    parser.add_argument("--detail-output", type=str, default="backtest_trades.csv", help="交易明细输出文件")
    parser.add_argument("--summary-output", type=str, default="backtest_summary.json", help="统计汇总输出文件")
    return parser.parse_args()


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
        win_rate = round(float((valid > 0).mean() * 100), 2) if not valid.empty else None
        avg_ret = round(float(valid.mean()), 2) if not valid.empty else None
        summary["returns"][f"{holding}d"] = {
            "samples": int(valid.shape[0]),
            "win_rate_pct": win_rate,
            "avg_return_pct": avg_ret,
        }

    return summary


def run_backtest(
    start_date: str,
    end_date: str,
    limit: int = 0,
    holding_days: list[int] | None = None,
    include_fallback: bool = False,
) -> tuple[pd.DataFrame, dict]:
    if holding_days is None:
        holding_days = [1, 3, 5, 10]

    stock_list = data_fetcher.get_stock_list()
    if limit > 0:
        stock_list = stock_list.head(limit).copy()

    index_df = data_fetcher.fetch_index_daily(days=max(config.HISTORY_DAYS, 600))
    if index_df is None or index_df.empty:
        raise RuntimeError("未获取到上证指数数据，无法执行回测。")

    market_env_map = strategy.build_market_environment_map(index_df)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    trade_rows: list[dict] = []

    for _, stock in stock_list.iterrows():
        stock_df = data_fetcher.fetch_stock_ohlcv(stock["code"], days=max(config.HISTORY_DAYS, 600))
        if stock_df is None or stock_df.empty or len(stock_df) < 80:
            continue

        enriched_df = strategy.enrich_indicators(stock_df)
        date_strings = enriched_df["date"].dt.strftime("%Y-%m-%d")

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
            if result is None:
                continue
            if result.signal_date != signal_date:
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

    trades_df = pd.DataFrame(trade_rows)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["signal_date", "signal_score"], ascending=[True, False]).reset_index(drop=True)
    summary = _build_summary(trades_df, holding_days)
    summary["start_date"] = start_date
    summary["end_date"] = end_date
    summary["include_fallback"] = include_fallback
    summary["scanned_stocks"] = int(len(stock_list))
    return trades_df, summary


def print_summary(summary: dict, trades_df: pd.DataFrame, top: int) -> None:
    print(f"回测区间: {summary['start_date']} 至 {summary['end_date']}")
    print(f"扫描股票: {summary['scanned_stocks']} 只")
    print(f"信号总数: {summary['total_signals']} 只")
    print(f"正式命中: {summary['formal_signals']} 只")
    print(f"候选观察: {summary['fallback_signals']} 只")
    print(f"平均评分: {summary['avg_signal_score']}")

    print("收益统计:")
    for label, stats in summary["returns"].items():
        print(
            f"- {label}: 样本 {stats['samples']} | "
            f"胜率 {stats['win_rate_pct']}% | 平均收益 {stats['avg_return_pct']}%"
        )

    if trades_df.empty:
        print("没有生成可用于回测的历史信号。")
        return

    print("样例信号:")
    for _, row in trades_df.head(top).iterrows():
        print(
            f"- {row['signal_date']} {row['code']} {row['name']} | "
            f"{'候选观察' if row['is_fallback'] else '正式命中'} | "
            f"{row['signal_group']} | 分数 {row['signal_score']} | "
            f"5日收益 {row.get('ret_5d')}"
        )


if __name__ == "__main__":
    args = parse_args()
    trades_df, summary = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        holding_days=args.holding_days,
        include_fallback=args.include_fallback,
    )

    if not trades_df.empty:
        trades_df.to_csv(args.detail_output, index=False, encoding="utf-8-sig")
    with open(args.summary_output, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print_summary(summary, trades_df, top=args.top)
