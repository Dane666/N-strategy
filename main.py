"""
N字战法扫描入口。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import config
import data_fetcher
import notifier
import strategy


def parse_args():
    parser = argparse.ArgumentParser(description="底部十字星 + 缩量回调 N 字策略扫描器")
    parser.add_argument("--limit", type=int, default=0, help="仅扫描前 N 只股票")
    parser.add_argument("--workers", type=int, default=config.MAX_WORKERS, help="并发线程数")
    parser.add_argument("--output", type=str, default=config.RESULT_OUTPUT, help="结果输出文件")
    parser.add_argument("--notify", action="store_true", help="扫描完成后推送飞书")
    parser.add_argument("--test-notify", action="store_true", help="仅发送飞书测试消息")
    parser.add_argument("--allow-empty", action="store_true", help="即使无命中也打印结果并正常退出")
    return parser.parse_args()


def run_scan(limit: int, workers: int, output: str, notify: bool = False):
    stock_list = data_fetcher.get_stock_list()
    if stock_list.empty:
        raise RuntimeError("未获取到股票列表，请检查网络或数据源。")

    if limit > 0:
        stock_list = stock_list.head(limit).copy()

    index_df = data_fetcher.fetch_index_daily()
    if index_df is None or index_df.empty:
        raise RuntimeError("未获取到上证指数数据，无法执行大盘过滤。")

    market_env = strategy.check_market_environment(index_df)
    print(f"大盘过滤: {market_env}")
    if not market_env["passed"]:
        print("当前大盘未满足由弱转强条件，本轮不输出选股结果。")
        return pd.DataFrame()

    results = []

    def task(row):
        stock_df = data_fetcher.fetch_stock_ohlcv(row["code"])
        return strategy.find_signal(row["code"], row["name"], stock_df, market_env)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(task, row): row["code"] for _, row in stock_list.iterrows()}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result.__dict__)

    output_df = pd.DataFrame(results)
    if not output_df.empty:
        output_df = output_df.sort_values(
            ["strong_volume_breakout", "breakout_volume_ratio_vs_5ma", "breakout_gain_pct"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        output_df.to_csv(output, index=False, encoding="utf-8-sig")
        if notify:
            notifier.send_feishu_msg(
                title=f"N字策略命中 {len(output_df)} 只",
                content=notifier.build_signal_message(output_df.to_dict(orient="records")),
                enabled=config.FEISHU_ENABLED,
            )
    return output_df


if __name__ == "__main__":
    args = parse_args()
    if args.test_notify:
        notifier.send_feishu_msg(
            title="N-strategy 飞书测试",
            content="飞书 webhook 已接入当前项目，后续将推送选股命中理由。",
            enabled=config.FEISHU_ENABLED,
        )
        print("飞书测试消息已发送。")
        raise SystemExit(0)

    result_df = run_scan(limit=args.limit, workers=args.workers, output=args.output, notify=args.notify)
    if result_df.empty:
        print("未发现满足条件的标的。")
        if not args.allow_empty:
            raise SystemExit(0)
    else:
        print(result_df.to_string(index=False))
