# -*- coding: utf-8 -*-
"""
发送回测摘要通知。
"""

from __future__ import annotations

import argparse
import json

import config
import notifier


def parse_args():
    parser = argparse.ArgumentParser(description="发送回测摘要通知")
    parser.add_argument("--summary-1m", required=True, help="近1个月回测 summary json")
    parser.add_argument("--summary-6m", required=True, help="近6个月回测 summary json")
    parser.add_argument(
        "--holding-day",
        type=int,
        default=config.BACKTEST_NOTIFY_HOLDING_DAY,
        help="摘要通知使用的持有周期",
    )
    return parser.parse_args()


def load_summary(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    args = parse_args()
    notifier.notify_backtest_compare(
        summary_1m=load_summary(args.summary_1m),
        summary_6m=load_summary(args.summary_6m),
        holding_day=args.holding_day,
    )
    print("回测摘要通知已发送。")
