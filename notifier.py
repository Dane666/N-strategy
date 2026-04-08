# -*- coding: utf-8 -*-
"""
复用 adata-main/tests/momentum/notify/feishu.py 的飞书推送方式。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

import requests

import config

logger = logging.getLogger("n_strategy")


def send_feishu_msg(title: str, content: str, webhook_url: str | None = None, enabled: bool = True):
    if not enabled:
        return
    url = webhook_url or config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书通知已开启，但未配置 Webhook URL")
        return

    data = {
        "msg_type": "text",
        "content": {"text": f"{title}\n\n{content}"},
    }
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(data),
        timeout=5,
    )
    response.raise_for_status()


def send_feishu_card(title: str, card: dict, webhook_url: str | None = None, enabled: bool = True):
    if not enabled:
        return
    url = webhook_url or config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书通知已开启，但未配置 Webhook URL")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": card["elements"],
        },
    }
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=5,
    )
    response.raise_for_status()


def build_signal_message(signal_rows: list[dict]) -> str:
    lines = []
    for idx, row in enumerate(signal_rows, start=1):
        lines.append(f"{idx}. {row['code']} {row['name']}")
        lines.append(f"分组/评分: {row['signal_group']} / {row['signal_score']}")
        lines.append(f"信号日期: {row['signal_date']}")
        lines.append(f"超卖等级: {row['oversold_level']}，形态: {row['candle_pattern']}")
        lines.append(f"超卖确认: {'是' if row['oversold_triggered'] else '否'}，J拐头向上: {'是' if row['j_turn_up'] else '否'}")
        lines.append(f"触发涨幅: {row['signal_gain_pct']}%")
        lines.append(f"回调天数: {row['pullback_days']}，回调最小量/启动量: {row['pullback_volume_ratio']}")
        lines.append(f"大盘: {row['market_reason']}")
        lines.append(f"底部区域: {row['bottom_reason']}")
        lines.append(f"启动阳线: {row['surge_reason']}")
        lines.append(f"缩量回调: {row['pullback_reason']}")
        lines.append(f"买点触发: {row['trigger_reason']}")
        lines.append(f"补充说明: {row['notes']}")
        lines.append("")
    return "\n".join(lines).strip()


def build_empty_message(market_env: dict, scanned_count: int) -> str:
    return (
        f"本轮扫描未命中标的。\n"
        f"扫描数量: {scanned_count}\n"
        f"大盘日期: {market_env['signal_date']}\n"
        f"大盘MA20之上: {market_env['above_ma20']}\n"
        f"大盘单日涨幅>1%: {market_env['gain_gt_1pct']}"
    )


def build_grouped_card(signal_rows: list[dict], market_env: dict, scanned_count: int) -> dict:
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"扫描数量: **{scanned_count}**\n"
                    f"命中数量: **{len(signal_rows)}**\n"
                    f"大盘日期: **{market_env['signal_date']}**\n"
                    f"MA20之上: **{market_env['above_ma20']}**\n"
                    f"单日涨幅>1%: **{market_env['gain_gt_1pct']}**"
                ),
            },
        }
    ]

    if not signal_rows:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "本轮未命中符合条件的标的。"},
            }
        )
        return {"elements": elements}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in signal_rows:
        grouped[row["signal_group"]].append(row)

    for group_name in ["A档强信号", "B档观察", "C档埋伏"]:
        rows = grouped.get(group_name, [])
        if not rows:
            continue
        elements.append(
            {
                "tag": "hr",
            }
        )
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{group_name} ({len(rows)}只)**"},
            }
        )
        for row in rows[:8]:
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**{row['code']} {row['name']}**  分数 `{row['signal_score']}`\n"
                            f"超卖: {row['oversold_level']} | 形态: {row['candle_pattern']} | "
                            f"触发涨幅: {row['signal_gain_pct']}% | 量比5均: {row['signal_volume_ratio_vs_5ma']}\n"
                            f"{row['trigger_reason']}"
                        ),
                    },
                }
            )
    return {"elements": elements}


def notify_scan_result(signal_rows: list[dict], market_env: dict, scanned_count: int):
    title = f"N字策略扫描 {market_env['signal_date']}"
    if config.FEISHU_MESSAGE_MODE == "card":
        send_feishu_card(
            title=title,
            card=build_grouped_card(signal_rows, market_env, scanned_count),
            enabled=config.FEISHU_ENABLED,
        )
        return

    if signal_rows:
        content = build_signal_message(signal_rows)
    else:
        content = build_empty_message(market_env, scanned_count)
    send_feishu_msg(title=title, content=content, enabled=config.FEISHU_ENABLED)
