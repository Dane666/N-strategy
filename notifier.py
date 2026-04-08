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


def _is_flow_webhook(url: str) -> bool:
    return "/flow/api/trigger-webhook/" in url


def send_feishu_msg(title: str, content: str, webhook_url: str | None = None, enabled: bool = True):
    if not enabled:
        return
    url = webhook_url or config.FEISHU_WEBHOOK_URL
    if not url:
        logger.warning("飞书通知已开启，但未配置 Webhook URL")
        return

    payload_text = f"{title}\n\n{content}".strip()
    if _is_flow_webhook(url):
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {
                    "title": title,
                    "content": content,
                },
                ensure_ascii=False,
            ),
            timeout=5,
        )
    else:
        data = {
            "msg_type": "text",
            "content": {"text": payload_text},
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
    lines = ["结果摘要"]
    formal_rows = [row for row in signal_rows if not row["is_fallback"]]
    fallback_rows = [row for row in signal_rows if row["is_fallback"]]

    lines.append(f"正式命中: {len(formal_rows)} 只")
    lines.append(f"候选观察: {len(fallback_rows)} 只")

    if formal_rows:
        lines.append("")
        lines.append("【正式命中】")
        for idx, row in enumerate(formal_rows, start=1):
            lines.append(f"{idx}. {row['code']} {row['name']}")
            lines.append(f"评级: {row['signal_group']} | 评分: {row['signal_score']}")
            lines.append(f"形态: {row['oversold_level']} | {row['candle_pattern']}")
            lines.append(f"涨幅/量比: {row['signal_gain_pct']}% / {row['signal_volume_ratio_vs_5ma']}")
            lines.append(f"回调: {row['pullback_days']}天 | 回调量比: {row['pullback_volume_ratio']}")
            lines.append(f"触发: {row['trigger_reason']}")
            lines.append(f"说明: {row['notes']}")
            lines.append("")

    if fallback_rows:
        lines.append("【候选观察前三】")
        for idx, row in enumerate(fallback_rows[:3], start=1):
            lines.append(f"{idx}. {row['code']} {row['name']}")
            lines.append(f"评级: {row['signal_group']} | 评分: {row['signal_score']}")
            lines.append(f"形态: {row['oversold_level']} | {row['candle_pattern']}")
            lines.append(f"涨幅/量比: {row['signal_gain_pct']}% / {row['signal_volume_ratio_vs_5ma']}")
            lines.append(f"触发: {row['trigger_reason']}")
            if row.get("fallback_reason"):
                lines.append(f"候选原因: {row['fallback_reason']}")
            lines.append(f"说明: {row['notes']}")
            lines.append("")
    return "\n".join(lines).strip()


def build_empty_message(market_env: dict, scanned_count: int) -> str:
    return (
        "结果摘要\n\n"
        "本轮没有正式命中或候选结果。\n"
        f"扫描数量: {scanned_count}\n"
        f"大盘日期: {market_env['signal_date']}\n"
        f"大盘 MA20 之上: {market_env['above_ma20']}\n"
        f"大盘单日涨幅 >1%: {market_env['gain_gt_1pct']}"
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
                            f"**{row['code']} {row['name']}**  `{row['signal_group']}` `分数 {row['signal_score']}`\n"
                            f"{'候选观察' if row['is_fallback'] else '正式命中'} | "
                            f"{row['oversold_level']} | {row['candle_pattern']} | "
                            f"涨幅 {row['signal_gain_pct']}% | 量比5均 {row['signal_volume_ratio_vs_5ma']}\n"
                            f"{row['trigger_reason']}"
                            + (f"\n候选原因: {row['fallback_reason']}" if row.get('fallback_reason') else "")
                        ),
                    },
                }
            )
    return {"elements": elements}


def send_test_notification():
    send_feishu_msg(
        title="N字策略测试",
        content=(
            "这是纯文本测试消息。\n"
            "如果你看到的是整洁正文，而不是 JSON 字符串，说明当前 webhook 链路适合文本通知。"
        ),
        enabled=config.FEISHU_ENABLED,
    )


def notify_scan_result(signal_rows: list[dict], market_env: dict, scanned_count: int):
    title = f"N字策略盘后扫描 {market_env['signal_date']}"
    if signal_rows:
        content = build_signal_message(signal_rows)
    else:
        content = build_empty_message(market_env, scanned_count)
    send_feishu_msg(title=title, content=content, enabled=config.FEISHU_ENABLED)
