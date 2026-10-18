#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行跑一次「龙回头扫描 → 推送微信」。

不启动网站也能用；适合挂到 Windows 任务计划程序，例如每个交易日 15:05 触发。

用法：
    python scan_push.py                     # 用系统里保存的设置扫描并推送（所有已开启通道）
    python scan_push.py --test              # 只发一条测试消息，验证通道是否打通
    python scan_push.py --test --channel serverchan --key SCTxxxx
    python scan_push.py --top 5 --min-score 70
    python scan_push.py --channel pushplus --key <token>   # 临时覆盖，不写回设置

说明：默认会发到设置里勾选的**每一个**通道（可多选并行）。
加了 --channel/--key 则只发这一个通道，用来单独验证某个通道是否通。

退出码：0 = 推送成功，1 = 推送失败，2 = 参数错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import server                                            # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="龙回头扫描并推送到微信（Server酱 / PushPlus / 企业微信机器人）")
    ap.add_argument("--test", action="store_true", help="只发一条测试消息")
    ap.add_argument("--channel", help="只发这一个通道（临时覆盖，不读设置里的勾选）")
    ap.add_argument("--key", help="配合 --channel 使用的 SendKey / token / webhook")
    ap.add_argument("--min-score", type=int, dest="min_score", help="只推该评分以上")
    ap.add_argument("--top", type=int, help="最多列几只")
    ap.add_argument("--limit", type=int, help="扫描候选上限")
    ap.add_argument("--days", type=int, help="扫描统计窗口（交易日）")
    ap.add_argument("--force", action="store_true",
                    help="非交易日也照发（默认会跳过周末与节假日）")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结果，便于任务计划程序记日志")
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # type: ignore[attr-defined]
    except Exception:                                   # noqa: BLE001
        pass

    args = build_parser().parse_args(argv)

    # 非交易日直接跳过：否则节假日会重复推上一个交易日的数据。
    # --test 只验证通道连通性，不受此限制。
    if not args.test and not args.force:
        import datetime as _dt

        today = _dt.date.today().strftime("%Y-%m-%d")
        try:
            latest = server.market_date()
        except Exception:                               # noqa: BLE001
            latest = today
        if latest != today:
            print("跳过：今天不是交易日（最新交易日 %s，本地 %s）。要强制执行请加 --force。"
                  % (latest, today))
            return 0

    payload = {"test": True} if args.test else {"scan": True}
    if args.channel:
        payload["channel"] = args.channel
    if args.key:
        payload["key"] = args.key
    if args.min_score is not None:
        payload["minScore"] = args.min_score
    if args.top is not None:
        payload["top"] = args.top
    if args.limit is not None:
        payload["limit"] = args.limit
    if args.days is not None:
        payload["days"] = args.days

    result = server.api_notify(payload)

    if args.quiet:
        print("%s %s %s" % ("OK  " if result.get("ok") else "FAIL",
                            result.get("channel", ""), result.get("detail", "")))
    else:
        shown = dict(result)
        shown.pop("preview", None)                      # 正文太长，不往控制台刷
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        if result.get("preview"):
            print("\n--- 消息正文预览 ------------------------------")
            print(result["preview"])

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
