# -*- coding: utf-8 -*-
"""
复用 adata-main/tests/momentum/notify/feishu.py 的飞书推送方式。
"""

from __future__ import annotations

import json
import logging

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


def build_signal_message(signal_rows: list[dict]) -> str:
    lines = []
    for idx, row in enumerate(signal_rows, start=1):
        lines.append(f"{idx}. {row['code']} {row['name']}")
        lines.append(f"信号日期: {row['signal_date']}")
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
