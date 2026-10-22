# -*- coding: utf-8 -*-
"""
龙回头 · 五层立体短线交易系统  —  本地行情与策略服务

设计目标
--------
严格落地《炒短线股票实施方案001.docx》的五层结构：
  第一层 核心选股逻辑：非龙头不炒
  第二层 核心战法：右侧「龙回头」与「强势复苏」
  第三层 日内交易与仓位管理
  第四层 铁血纪律：止损与止盈
  第五层 实施准备：每日必做的复盘功课

数据来源（全部为公开实时接口，纯标准库实现，无需第三方依赖）
  实时快照   : http://qt.gtimg.cn/q=                        （腾讯，GBK）
  指数快照   : http://qt.gtimg.cn/q=sh000001,...            （腾讯）
  日K线/日历 : http://money.finance.sina.com.cn/...         （新浪）
  板块排行   : http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php   （行业）
               http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class（概念）
  涨停/跌停池: https://push2ex.eastmoney.com/getTopicZTPool / getTopicDTPool

说明：东方财富 push2 系列接口对高频请求会限流（502 / 连接重置），
本服务不依赖该接口；热点题材改为由涨停池按行业板块聚合，同时更贴合方案
第五层「把涨停股拉出来，归纳出当前最强的 2-3 个概念板块」的复盘要求。

风险边界
--------
本程序只做行情聚合与策略纪律提示，不连接券商、不下单、不读取交易账户。
所有买卖、止损止盈均为「建议与提示」，最终决策与风险由使用者承担。
"""

from __future__ import annotations

import base64
import datetime as _dt
import gzip
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import push as _push                                    # 同目录下的推送通道模块

# ----------------------------------------------------------------------------
# 基础配置
# ----------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
STORE_FILE = os.path.join(DATA_DIR, "store.json")

# 监听地址。本地跑默认只绑 127.0.0.1（安全：不对局域网/公网暴露）；
# 云端平台（Render / Railway / Koyeb …）会注入 PORT，这时自动绑 0.0.0.0，
# 否则从外部永远连不上。
HOST = os.environ.get("LHT_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("LHT_PORT") or os.environ.get("PORT") or "8766")

# 跨域来源白名单。留空 = 不发 CORS 头（本地默认）。
#
# 为什么默认关掉：本服务有 /api/store，会返回用户填的推送密钥（Server酱 SendKey、
# 企业微信 webhook）。如果在本地开着 127.0.0.1:8766 且允许任意来源跨域读取，
# 那么你随手打开一个恶意网页，它就能偷偷把你的推送密钥读走。所以只在
# 「前端部署在别处（如 GitHub Pages）、必须跨域调本 API」时才用环境变量显式打开，
# 并且建议填具体来源而不是 "*"。
CORS_ORIGIN = os.environ.get("LHT_CORS_ORIGIN", "").strip()

# Free 实例的磁盘是临时的：配置存不下去时降级运行，不让接口 500。
DATA_WRITABLE = True

# ----------------------------------------------------------------------------
# 可选：Upstash Redis 持久化
# ----------------------------------------------------------------------------
# Vercel / Render 免费实例的本地磁盘都是临时的：冷启动、扩缩容、重新部署都会
# 把 data/store.json 清空。Vercel 更麻烦 —— 同一时刻多个实例各有一份磁盘，
# 请求打到哪个实例就看到哪份数据，所以「档案」会时有时无。
#
# 配了下面两个环境变量后，store 会改存到 Upstash（Redis 的 REST 接口），
# 本地文件只作为离线备份；没配则保持原来的纯本地行为。
#
# 兼容两种命名：
#   UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN   （Upstash 控制台）
#   KV_REST_API_URL / KV_REST_API_TOKEN                 （Vercel KV / 市场集成自动注入）
_KV_URL = (os.environ.get("UPSTASH_REDIS_REST_URL")
           or os.environ.get("KV_REST_API_URL") or "").strip().rstrip("/")
_KV_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN")
             or os.environ.get("KV_REST_API_TOKEN") or "").strip()
# 键前缀。多套环境共用同一个库时，用 LHT_KV_PREFIX 隔离（例如 lht:dev:）。
_KV_PREFIX = (os.environ.get("LHT_KV_PREFIX") or "lht:").strip()
_KV_ENABLED = bool(_KV_URL and _KV_TOKEN)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 策略默认参数（区间取值来自方案原文，可被前端设置覆盖）
DEFAULT_SETTINGS = {
    "capital": 100000.0,        # 短线总资金（元）
    "maxPositionPct": 50.0,     # 单只股票持仓上限（%）  方案：绝不超过总资金 50%
    "sleeveCount": 3,           # 资金平分份数            方案：平分为 2-3 等份
    "starterPct": 30.0,         # 首笔「观察哨」比例（%） 方案：先下 30%
    "stopLossPct": 4.0,         # 绝对止损线（%）         方案：-3% ~ -5%
    "takeProfitHalfPct": 5.0,   # 一档止盈（%）先落袋一半 方案：5% ~ 10%
    "takeProfitFullPct": 10.0,  # 二档止盈（%）
    "staleDays": 3,             # 未启动退出日数          方案：3 天内没爆发就走
    "floatCapMin": 30.0,        # 流通市值下限（亿）      方案：30 亿 ~ 120 亿
    "floatCapMax": 120.0,
    "pullbackDaysMin": 3,       # 回调周期下限（交易日）  方案：3 ~ 8 个交易日
    "pullbackDaysMax": 8,
    "pullbackPctMin": 20.0,     # 回调幅度下限（%）       方案：20% ~ 30%
    "pullbackPctMax": 30.0,
    "panicLimitDowns": 20,      # 跌停家数退潮预警阈值

    # ---- 微信推送（只做「系统 → 你」的单向提醒，不登录微信、不下单）----
    "notifyChannels": [],       # 生效的通道列表，可多选并行，如 ["serverchan","wecom"]
    "notifyKeys": {},           # {通道: 密钥}
    "notifyChannel": "off",     # 旧版单通道字段，仅用于迁移，不再读取
    "notifyKey": "",            # 旧版单通道密钥，仅用于迁移
    "notifyMinScore": 65,       # 只推该评分以上（默认 B 级）
    "notifyTopN": 8,            # 单条消息最多列几只
    "notifyWecomFormat": "text",  # 企业微信正文格式：text（个人微信可读）/ markdown
    "notifyTimes": "15:05",     # 交易日自动推送时刻，逗号分隔可填多个
    "notifyDays": 10,           # 扫描统计窗口（交易日）
    "notifyScanLimit": 40,      # 扫描候选上限
    # ---- 龙回头档案：自动把每次扫描的 A/B 级命中按「月 → 日 → 标的」封存 ----
    "archiveMinScore": 65,      # 收入档案的最低评分（默认与推送阈值一致：B 级）
    "archiveAuto": True,        # 每次扫描成功后自动存档
}

_QUOTE_TTL = 3.0
_KLINE_TTL = 600.0
_BOARD_TTL = 30.0
_POOL_TTL = 300.0
_OVERVIEW_TTL = 15.0

# 一次扫描各阶段的硬性时间预算（秒）。上游接口抽风时，宁可少评几只，
# 也不能把一次扫描拖到几分钟 —— 定时推送是要准点发出去的。
SCAN_POOL_BUDGET = 20.0     # 涨停池 / 跌停池多日并发抓取
SCAN_KLINE_BUDGET = 25.0    # 个股日K并发抓取


# ----------------------------------------------------------------------------
# 通用工具：带缓存 / 重试的 HTTP
# ----------------------------------------------------------------------------

class _Cache:
    """带 TTL 的内存缓存。

    ``get_or`` 做了**单飞（single-flight）**：同一个 key 过期时，只放一个线程
    真正去上游抓，其余线程等它的结果。否则前端每 3 秒轮询一次 /api/overview，
    一旦缓存过期就会有十几个线程同时去打同一个外部接口 —— 既慢又容易被限流。
    """

    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()
        self._inflight: dict = {}

    def get(self, key, ttl):
        with self._lock:
            item = self._data.get(key)
        if item and (time.monotonic() - item[0]) < ttl:
            return item[1]
        return None

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.monotonic(), value)

    def get_or(self, key, ttl, factory):
        """缓存过期时回调 factory()，失败则回退到旧值。"""
        for _ in range(3):
            hit = self.get(key, ttl)
            if hit is not None:
                return hit

            with self._lock:
                ev = self._inflight.get(key)
                if ev is None:
                    ev = threading.Event()
                    self._inflight[key] = ev
                    mine = True
                else:
                    mine = False

            if mine:
                try:
                    value = factory()
                except Exception:
                    with self._lock:
                        item = self._data.get(key)
                    if item:
                        return item[1]
                    raise
                finally:
                    with self._lock:
                        self._inflight.pop(key, None)
                    ev.set()
                self.set(key, value)
                return value

            # 别人正在抓：等它（最多 40 秒），然后读缓存
            ev.wait(40.0)

        # 等了两轮还没结果（对方失败或超时），自己来一次，不再排队
        hit = self.get(key, ttl)
        if hit is not None:
            return hit
        try:
            value = factory()
        except Exception:
            with self._lock:
                item = self._data.get(key)
            if item:
                return item[1]
            raise
        self.set(key, value)
        return value


_CACHE = _Cache()
_STATS = {"requests": 0, "errors": 0, "last_error": ""}
_STATS_LOCK = threading.Lock()


def _note_error(exc: Exception) -> None:
    with _STATS_LOCK:
        _STATS["errors"] += 1
        _STATS["last_error"] = f"{type(exc).__name__}: {exc}"


def _client_gone(exc: BaseException) -> bool:
    """客户端提前断开连接（刷新页面、切标签、关浏览器）。

    ConnectionAbortedError / ConnectionResetError / BrokenPipeError 都是
    ConnectionError 的子类。这属于**正常现象**，不该算服务端错误，
    更不该把整段 traceback 打到日志里 —— 否则 logs\\server.log 会被刷爆。
    """
    return isinstance(exc, ConnectionError)


_SLOW_HTTP = 4.0            # 单个外部请求超过这个秒数就记一条日志，便于事后定位


def _short_url(url: str) -> str:
    """把长 URL 压成 host + 末段，日志里够看就行。"""
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
        tail = url.split("?", 1)[0].rsplit("/", 1)[-1]
        return f"{host}/{tail}"
    except Exception:                                   # noqa: BLE001
        return url[:60]


def _log_slow(url: str, spent: float) -> None:
    sys.stderr.write("[慢接口] %.1fs  %s\n" % (spent, _short_url(url)))


def http_get(url: str, decode: str = "utf-8", referer: str = None,
             timeout: float = 12.0, retries: int = 2, deadline: float = None) -> str:
    """最简 HTTP GET，带小退避重试。仅使用标准库。

    两个关键保护（没有它们，某个上游接口整体变慢时一次扫描能拖到 3 分钟）：

    * ``deadline``：``time.monotonic()`` 时间戳。整个调用（含重试）不会越过它；
      一旦超出就直接抛错，调用方不会一直等。
    * **慢失败不重试**：如果这次尝试把超时时间基本耗光了，说明对面是「慢」而不是
      「偶发错误」，重试大概率还是慢 —— 立刻放弃。把 40 只股票 × 3 次尝试 = 120 次
      挂起，压成 40 次。
    """
    headers = {"User-Agent": _UA, "Accept": "*/*", "Connection": "close"}
    if referer:
        headers["Referer"] = referer
    last = None
    for attempt in range(retries + 1):
        budget = timeout
        if deadline is not None:
            budget = min(budget, deadline - time.monotonic())
            if budget <= 0.5:
                last = TimeoutError("超出本次扫描时间预算：%s" % _short_url(url))
                break
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=budget) as resp:
                raw = resp.read()
            spent = time.monotonic() - t0
            with _STATS_LOCK:
                _STATS["requests"] += 1
            if spent >= _SLOW_HTTP:
                _log_slow(url, spent)
            return raw.decode(decode, errors="ignore")
        except Exception as exc:                        # noqa: BLE001
            last = exc
            spent = time.monotonic() - t0
            # 慢失败（把超时耗光）不重试；只有「快速失败」才值得再试一次
            if attempt < retries and spent < budget * 0.6:
                time.sleep(0.25 * (attempt + 1))
                continue
            break
    _note_error(last)
    raise last


# ----------------------------------------------------------------------------
# 交易日 / 交易时段
# ----------------------------------------------------------------------------

def market_date() -> str:
    """取最近一个交易日的日期，形如 2026-10-16。以腾讯指数行情时间为准。

    带 30 秒缓存：一次扫描里会被调用多次，没必要每次都问一遍腾讯。
    """
    def factory():
        text = http_get("http://qt.gtimg.cn/q=sh000001", decode="gbk",
                        timeout=6, retries=1)
        parts = text.split("~")
        stamp = parts[30] if len(parts) > 30 else ""
        if len(stamp) >= 8 and stamp[:8].isdigit():
            return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
        raise RuntimeError("腾讯行情时间戳不可用")

    try:
        return _CACHE.get_or("market_date", 30.0, factory)
    except Exception:                                   # noqa: BLE001
        return time.strftime("%Y-%m-%d")


def session_state() -> dict:
    """交易时段状态：盘前 / 集合竞价 / 早盘 / 午休 / 尾盘 / 休市。"""
    now = _dt.datetime.now()
    hm = now.hour * 60 + now.minute
    is_weekend = now.weekday() >= 5

    if is_weekend:
        state, label = "closed", "休市（周末）"
    elif hm < 9 * 60 + 15:
        state, label = "pre", "盘前"
    elif hm < 9 * 60 + 30:
        state, label = "auction", "集合竞价"
    elif hm < 11 * 60 + 30:
        state, label = "trading", "早盘交易中"
    elif hm < 13 * 60:
        state, label = "break", "午间休市"
    elif hm < 15 * 60:
        state, label = "trading", "午后交易中"
    else:
        state, label = "closed", "已收盘"

    return {
        "state": state,
        "label": label,
        "is_live": state in ("trading", "auction"),
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_date": market_date(),
    }


# ----------------------------------------------------------------------------
# 数据源 A：腾讯实时快照
# ----------------------------------------------------------------------------

def _tencent_symbol(code: str) -> str:
    return ("sh" if code[:1] in ("6", "9") else "sz") + code


def fetch_quotes(codes) -> dict:
    """批量实时快照。返回 {code: {...}}。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}

    key = "q:" + ",".join(sorted(codes))

    def factory():
        out = {}
        # 分批，避免 URL 过长
        for i in range(0, len(codes), 60):
            chunk = codes[i:i + 60]
            url = "http://qt.gtimg.cn/q=" + ",".join(_tencent_symbol(c) for c in chunk)
            text = http_get(url, decode="gbk", timeout=8, retries=1)
            for line in text.split(";"):
                line = line.strip()
                if "~" not in line or '="' not in line:
                    continue
                payload = line.split('="', 1)[1].rstrip('"')
                p = payload.split("~")
                if len(p) < 46:
                    continue
                code = p[2].strip()

                def num(idx, default=0.0):
                    try:
                        return float(p[idx]) if idx < len(p) and p[idx] not in ("", "-") else default
                    except (TypeError, ValueError):
                        return default

                price = num(3)
                pre_close = num(4)
                out[code] = {
                    "code": code,
                    "name": p[1].strip(),
                    "price": price,
                    "pre_close": pre_close,
                    "open": num(5),
                    "high": num(33),
                    "low": num(34),
                    "change": num(31),
                    "pct": num(32),
                    "volume": num(6),              # 成交量（手）
                    "amount": num(37),             # 成交额（万元）
                    "vol_ratio": num(49),          # 量比
                    "turnover": num(38),           # 换手率 %
                    "amplitude": num(43),          # 振幅 %
                    "float_cap": num(44),          # 流通市值（亿元）
                    "total_cap": num(45),          # 总市值（亿元）
                    "limit_up": num(47),
                    "limit_down": num(48),
                    "avg_price": num(51) or price,
                    "pe": num(39),
                    "pb": num(46),
                    "bid1": num(9),
                    "bid1_vol": num(10),
                    "ask1": num(19),
                    "ask1_vol": num(20),
                    "stamp": p[30].strip() if len(p) > 30 else "",
                    "updated": time.strftime("%H:%M:%S"),
                }
        if not out:
            raise RuntimeError("腾讯行情返回为空")
        return out

    cached = _CACHE.get(key, _QUOTE_TTL)
    if cached:
        return cached
    try:
        return _CACHE.get_or(key, _QUOTE_TTL, factory)
    except Exception:                                   # noqa: BLE001
        return {}


# ----------------------------------------------------------------------------
# 数据源 B：新浪日K线
# ----------------------------------------------------------------------------

def _sina_symbol(code: str) -> str:
    return ("sh" if code[:1] in ("6", "9") else "sz") + code


def fetch_kline(code: str, count: int = 70, deadline: float = None) -> list:
    """日K线（升序）。附带 MA5 / MA10 / MA20。

    ``deadline`` 是一次扫描的整体时间预算（``time.monotonic()`` 时间戳）。
    扫描 40 只股票时，个别股票慢一点无所谓 —— 与其干等 30 秒，不如直接跳过它。
    """
    key = f"k:{code}:{count}"

    def factory():
        url = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={_sina_symbol(code)}"
               f"&scale=240&ma=no&datalen={count}")
        text = http_get(url, referer="https://finance.sina.com.cn",
                        timeout=8, retries=1, deadline=deadline)
        # 新浪偶尔返回非严格 JSON（键名无引号），做一次规整
        fixed = re.sub(r"(\bday\b|\bopen\b|\bhigh\b|\blow\b|\bclose\b|\bvolume\b)\s*:", r'"\1":', text)
        try:
            raw = json.loads(fixed)
        except json.JSONDecodeError:
            raw = json.loads(text)
        bars = []
        for item in raw or []:
            try:
                bars.append({
                    "day": item["day"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item["volume"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if len(bars) < 5:
            raise RuntimeError(f"{code} K线数据不足")
        return _with_ma(bars)

    try:
        return _CACHE.get_or(key, _KLINE_TTL, factory)
    except Exception:                                   # noqa: BLE001
        return []


def _with_ma(bars: list) -> list:
    closes = [b["close"] for b in bars]
    for i, bar in enumerate(bars):
        for n, tag in ((5, "ma5"), (10, "ma10"), (20, "ma20")):
            if i + 1 >= n:
                bar[tag] = round(sum(closes[i + 1 - n:i + 1]) / n, 3)
            else:
                bar[tag] = None
    return bars


def merge_live_bar(bars: list, quote: dict) -> list:
    """把当日实时快照并入K线尾部（若为同一交易日则替换，否则追加）。"""
    if not bars or not quote:
        return bars
    stamp = quote.get("stamp") or ""
    if len(stamp) >= 8 and stamp[:8].isdigit():
        day = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    else:
        day = market_date()
    if not quote.get("price"):
        return bars
    bar = {
        "day": day,
        "open": quote.get("open") or quote["price"],
        "high": quote.get("high") or quote["price"],
        "low": quote.get("low") or quote["price"],
        "close": quote["price"],
        "volume": float(quote.get("volume") or 0) * 100.0,   # 手 -> 股
    }
    out = list(bars)
    if out and out[-1]["day"] == day:
        bar["volume"] = bar["volume"] or out[-1]["volume"]
        out[-1] = bar
    else:
        out.append(bar)
    return _with_ma(out)


# ----------------------------------------------------------------------------
# 数据源 B2：腾讯分时（1 分钟）
# ----------------------------------------------------------------------------

def fetch_minute(code: str) -> dict:
    """当日分时数据（腾讯）。返回 {date, points:[{t, p, avg}]}。

    原始行格式：``HHMM 价格 累计成交量(手) 累计成交额(元)``。
    分时均价线 = 累计成交额 ÷ (累计成交量 × 100)，直接由原始数据还原，
    不需要额外请求，也不会引入估算误差。
    """
    key = f"min:{code}"

    def factory():
        symbol = _tencent_symbol(code)
        url = f"http://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}"
        data = json.loads(http_get(url, referer="https://gu.qq.com/", timeout=10))
        node = (data.get("data") or {}).get(symbol) or {}
        body = node.get("data") or {}
        qt = (node.get("qt") or {}).get(symbol) or []
        points = []
        for row in body.get("data") or []:
            parts = str(row).split()
            if len(parts) < 3:
                continue
            t = parts[0]
            # 只保留连续竞价时段（09:30~11:30 / 13:00~15:00），
            # 腾讯对部分标的会附带 15:06~15:30 的盘后固价成交段。
            if not ("0930" <= t <= "1130" or "1300" <= t <= "1500"):
                continue
            try:
                price = float(parts[1])
                cum_vol = float(parts[2])
                cum_amt = float(parts[3]) if len(parts) > 3 else 0.0
            except ValueError:
                continue
            if price <= 0:
                continue
            avg = round(cum_amt / (cum_vol * 100), 3) if (cum_vol > 0 and cum_amt > 0) else price
            points.append({"t": t, "p": round(price, 3), "avg": avg})
        if not points:
            raise RuntimeError(f"{code} 分时数据为空")
        return {
            "date": str(body.get("date") or ""),
            "pre_close": _f(qt, 4) if qt else 0.0,
            "points": points,
        }

    try:
        return _CACHE.get_or(key, 60.0, factory)
    except Exception:                                   # noqa: BLE001
        return {"date": "", "pre_close": 0.0, "points": []}


# ----------------------------------------------------------------------------
# 数据源 C：东方财富 涨停 / 跌停池
# ----------------------------------------------------------------------------

_EM_UT = "7eea3edcaed734bea9cbfc24409ed989"


def fetch_limit_pool(date: str, kind: str = "up", deadline: float = None) -> dict:
    """涨停(kind=up) / 跌停(kind=down) 池。date 形如 20261016。"""
    key = f"pool:{kind}:{date}"

    def factory():
        if kind == "up":
            url = (f"https://push2ex.eastmoney.com/getTopicZTPool?ut={_EM_UT}"
                   f"&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fbt%3Aasc&date={date}")
        else:
            url = (f"https://push2ex.eastmoney.com/getTopicDTPool?ut={_EM_UT}"
                   f"&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fund%3Aasc&date={date}")
        data = json.loads(http_get(url, referer="https://quote.eastmoney.com/",
                                   timeout=10, retries=1, deadline=deadline))
        body = data.get("data") or {}
        pool = []
        for it in body.get("pool") or []:
            code = str(it.get("c", "")).strip()
            if not code:
                continue
            zttj = it.get("zttj") or {}
            pool.append({
                "code": code,
                "name": it.get("n", code),
                "price": round(float(it.get("p", 0)) / 100.0, 2),
                "pct": round(float(it.get("zdp", 0)), 2),
                "boards": int(it.get("lbc", 1) or 1),          # 连板数
                "first_seal": _fmt_hm(it.get("fbt")),          # 首次封板
                "last_seal": _fmt_hm(it.get("lbt")),           # 最后封板
                "break_times": int(it.get("zbc", 0) or 0),     # 炸板次数
                "sector": it.get("hybk") or "",                # 行业板块
                "amount": float(it.get("amount", 0) or 0),     # 成交额（元）
                "float_cap": round(float(it.get("ltsz", 0) or 0) / 1e8, 2),  # 流通市值（亿）
                "turnover": round(float(it.get("hs", 0) or 0), 2),
                "seal_fund": float(it.get("fund", 0) or 0),    # 封单资金
                "days": int(zttj.get("days", 0) or 0),         # 几天
                "boards_in_days": int(zttj.get("ct", 0) or 0),  # 几板
            })
        return {"date": date, "count": int(body.get("tc", len(pool)) or 0), "pool": pool}

    try:
        return _CACHE.get_or(key, _POOL_TTL, factory)
    except Exception:                                   # noqa: BLE001
        return {"date": date, "count": 0, "pool": []}


def fetch_pools_parallel(dates, kind: str = "up", deadline: float = None) -> list:
    """并发抓取多日涨停/跌停池（串行 8 天约 11 秒，并发后约 2 秒）。"""
    dates = list(dates)
    if not dates:
        return []
    workers = min(10, len(dates))                       # 10 个日期就 10 线程，一轮抓完
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda d: fetch_limit_pool(d, kind, deadline), dates))


def _fmt_hm(raw) -> str:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"{value // 10000:02d}:{(value // 100) % 100:02d}"


def trading_dates(limit: int = 12) -> list:
    """最近若干个交易日（以上证指数日K为准，仅一次请求）。

    早期版本靠逐日探测涨停池来判断交易日，需要 20~30 次请求（约 80 秒）；
    改用指数K线后一次请求即可拿到完整日历。
    """
    key = f"cal:{limit}"

    def factory():
        url = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no"
               f"&datalen={max(limit + 3, 20)}")
        text = http_get(url, referer="https://finance.sina.com.cn",
                        timeout=8, retries=1)
        fixed = re.sub(r"(\bday\b|\bopen\b|\bhigh\b|\blow\b|\bclose\b|\bvolume\b)\s*:",
                       r'"\1":', text)
        try:
            rows = json.loads(fixed)
        except json.JSONDecodeError:
            rows = json.loads(text)
        days = [str(r["day"]).replace("-", "") for r in rows]
        if not days:
            raise RuntimeError("交易日历为空")
        return days[-limit:]

    try:
        return _CACHE.get_or(key, 600.0, factory)
    except Exception:                                   # noqa: BLE001
        return []


# ----------------------------------------------------------------------------
# 数据源 D：东方财富 板块榜 / 指数 / 排行
# ----------------------------------------------------------------------------

def _f(parts, idx, default=0.0):
    try:
        value = parts[idx]
        return float(value) if value not in ("", "-") else default
    except (IndexError, TypeError, ValueError):
        return default


def fetch_indices() -> list:
    """指数快照（腾讯源）。"""
    key = "indices"

    def factory():
        symbols = "sh000001,sz399001,sz399006,sh000688,bj899050"
        text = http_get(f"http://qt.gtimg.cn/q={symbols}", decode="gbk", timeout=8)
        out = []
        for line in text.split(";"):
            if "~" not in line or '="' not in line:
                continue
            p = line.split('="', 1)[1].rstrip('"').split("~")
            if len(p) < 33 or not p[2].strip():
                continue
            out.append({
                "code": p[2].strip(),
                "name": p[1].strip(),
                "price": _f(p, 3),
                "change": _f(p, 31),
                "pct": _f(p, 32),
            })
        if not out:
            raise RuntimeError("腾讯指数返回为空")
        return out

    try:
        return _CACHE.get_or(key, 15.0, factory)
    except Exception:                                   # noqa: BLE001
        return []


def _sina_board_list(url: str) -> list:
    """解析新浪板块总览接口（GBK）。
    字段：[1]名称 [2]家数 [3]均价 [4]涨跌额 [5]涨跌幅% [6]成交量 [7]成交额
          [8]领涨股代码 [9]领涨股涨幅% [10]领涨股价 [11]领涨股涨跌额 [12]领涨股名称
    """
    raw = http_get(url, decode="gbk", referer="https://finance.sina.com.cn", timeout=12)
    body = raw[raw.find("=") + 1:].strip().rstrip(";")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    out = []
    for _key, val in (data or {}).items():
        p = str(val).split(",")
        if len(p) < 13:
            continue
        try:
            out.append({
                "name": p[1].strip(),
                "count": int(float(p[2] or 0)),
                "pct": round(float(p[5]), 2),
                "amount": float(p[7] or 0),
                "leader_code": p[8].strip()[2:] if len(p[8].strip()) > 2 else "",
                "leader_pct": round(float(p[9]), 2),
                "leader": p[12].strip() if len(p) > 12 else "",
            })
        except (ValueError, IndexError):
            continue
    return out


def fetch_boards(kind: str = "concept", size: int = 12) -> list:
    """板块涨幅榜（新浪源）。kind: concept=概念板块 / industry=行业板块。"""
    key = f"board:{kind}"

    def factory():
        if kind == "concept":
            rows = _sina_board_list(
                "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class")
        else:
            rows = _sina_board_list(
                "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php")
        if not rows:
            raise RuntimeError("新浪板块返回为空")
        rows.sort(key=lambda x: -x["pct"])
        return rows[:max(1, size)]

    try:
        return _CACHE.get_or(key, _BOARD_TTL, factory)
    except Exception:                                   # noqa: BLE001
        return []


def fetch_hot_sectors(date: str, top: int = 10) -> list:
    """第一层「选热点」的核心：从涨停池按行业板块聚合，归纳当日最强题材。

    这正是方案第五层复盘功课的自动化：
    「把今天两市所有的涨停股拉出来，找出涨停原因（归纳出当前最强的 2-3 个概念板块）」。
    """
    pool = fetch_limit_pool(date, "up")["pool"]
    agg = {}
    for item in pool:
        sec = (item.get("sector") or "").strip()
        if not sec:
            continue
        rec = agg.setdefault(sec, {"sector": sec, "limitup_count": 0, "max_boards": 0,
                                   "stocks": [], "seal_fund": 0.0})
        rec["limitup_count"] += 1
        rec["max_boards"] = max(rec["max_boards"], item["boards"])
        rec["seal_fund"] += item.get("seal_fund") or 0.0
        rec["stocks"].append({"code": item["code"], "name": item["name"],
                              "boards": item["boards"], "turnover": item.get("turnover")})
    rows = sorted(agg.values(), key=lambda r: (-r["limitup_count"], -r["max_boards"]))
    for rec in rows:
        rec["stocks"].sort(key=lambda s: -s["boards"])
        rec["seal_fund"] = round(rec["seal_fund"] / 1e8, 2)
    return rows[:max(1, top)]


# ----------------------------------------------------------------------------
# 通用：股票分类
# ----------------------------------------------------------------------------

def is_main_board(code: str) -> bool:
    """沪深主板：沪市 600/601/603/605，深市 000/001/002/003。"""
    code = str(code)
    return len(code) == 6 and code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def board_name(code: str) -> str:
    code = str(code)
    if code.startswith(("688",)):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("4", "8", "920")):
        return "北交所"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    return "其他"


# ----------------------------------------------------------------------------
# 策略引擎 —— 第二层：龙回头 100 分制评分
# ----------------------------------------------------------------------------

LIMIT_UP_PCT = 9.8          # 主板涨停判定阈值（%）
LOOKBACK = 45               # 形态回看窗口（交易日）


def analyze_dragon(bars: list, quote: dict, settings: dict, pool_boards: int = 0) -> dict:
    """
    依据方案第二层「龙回头」四个条件打分：
      前期走牛(连板) / 无量回踩(缩量) / 回调时间(3~8日) / 回调空间(20%~30%)
    并叠加第一层的资金面过滤（流通市值 30~120 亿、拉升期换手 10~20%）
    与均线支撑（10 日 / 20 日均线）。

    总分 100：
      龙头辨识度 25 / 回调时间 15 / 回调幅度 20 / 缩量程度 20
      均线支撑   10 / 流通市值  5 / 拉升期换手 5
    """
    detail = []
    result = {
        "code": quote.get("code", ""),
        "name": quote.get("name", ""),
        "price": quote.get("price"),
        "pct": quote.get("pct"),
        "turnover": quote.get("turnover"),
        "vol_ratio": quote.get("vol_ratio"),
        "float_cap": quote.get("float_cap"),
        "score": 0,
        "grade": "不符合",
        "boards": 0,
        "pullback_days": 0,
        "pullback_pct": 0.0,
        "shrink_ratio": None,
        "ma5": None, "ma10": None, "ma20": None,
        "right_side": False,      # 激进买点：放量起爆
        "stable": False,          # 稳健买点：缩量回踩均线止跌
        "details": detail,
        "advice": "",
        "levels": {},
        "bars": [],
    }

    if len(bars) < 12:
        result["advice"] = "K线数据不足，无法评分"
        return result

    window = bars[-LOOKBACK:]
    closes = [b["close"] for b in window]

    # ---- 1. 识别前期强势（连板）段 ----
    best_run = {"len": 0, "start": 0, "end": 0}
    i = 0
    while i < len(window):
        if i > 0 and window[i - 1]["close"] > 0 and \
           (window[i]["close"] - window[i - 1]["close"]) / window[i - 1]["close"] * 100 >= LIMIT_UP_PCT:
            start = i
            end = i
            j = i + 1
            while j < len(window) and window[j - 1]["close"] > 0 and \
                    (window[j]["close"] - window[j - 1]["close"]) / window[j - 1]["close"] * 100 >= LIMIT_UP_PCT:
                end = j
                j += 1
            if (end - start + 1) > best_run["len"]:
                best_run = {"len": end - start + 1, "start": start, "end": end}
            i = j
        else:
            i += 1

    boards = best_run["len"]
    result["boards"] = boards
    if pool_boards > boards:
        boards = pool_boards
        result["boards"] = pool_boards

    # ---- 2. 回调区间与升浪区间 ----
    run_start = best_run["start"]
    peak_from = max(0, run_start - 1)
    # 真正的最高点要从拉升启动点一路找起。
    # 不能以「连板段结束」为界——炸板/天量阴线当天往往才是最高点。
    peak_idx = max(range(peak_from, len(window)), key=lambda k: window[k]["high"])
    peak_price = window[peak_idx]["high"]

    rally = window[peak_from:peak_idx + 1] or [window[peak_idx]]
    pullback = window[peak_idx + 1:]

    result["pullback_days"] = len(pullback)
    price = quote.get("price") or closes[-1]
    result["pullback_pct"] = round((peak_price - price) / peak_price * 100, 2) if peak_price > 0 else 0.0

    # 缩量比的参照系必须是「拉升期天量」而不是「拉升期均量」：
    # 一字板期间成交量极小（筹码锁死），若用均量作分母，会得出
    # 「回调放量 16 倍」的荒谬结论。用天量作分母才是「缩量」的真实含义。
    rally_peak_vol = max((b["volume"] for b in rally), default=0.0)
    rally_avg_vol = (sum(b["volume"] for b in rally) / len(rally)) if rally else 0.0
    pull_vol = sum(b["volume"] for b in pullback) / len(pullback) if pullback else 0.0
    shrink = (pull_vol / rally_peak_vol) if (rally_peak_vol > 0 and pullback) else None
    result["shrink_ratio"] = round(shrink, 3) if shrink is not None else None
    result["rally_peak_vol"] = round(rally_peak_vol, 0)
    result["rally_avg_vol"] = round(rally_avg_vol, 0)
    result["pull_avg_vol"] = round(pull_vol, 0)

    ma5 = window[-1].get("ma5")
    ma10 = window[-1].get("ma10")
    ma20 = window[-1].get("ma20")
    result.update({"ma5": ma5, "ma10": ma10, "ma20": ma20})

    # ================= 评分 =================
    cap_min = float(settings.get("floatCapMin", 30))
    cap_max = float(settings.get("floatCapMax", 120))

    # A. 龙头辨识度 25
    if boards >= 3:
        a, an = 25, f"前期 {boards} 连板，板块龙头辨识度极高"
    elif boards == 2:
        a, an = 18, "前期 2 连板，具备龙头辨识度"
    elif boards == 1:
        a, an = 8, "仅有 1 个涨停，龙头辨识度不足"
    else:
        a, an = 0, "近期无连板，不符合「非龙头不炒」"
    detail.append({"key": "A", "label": "龙头辨识度", "score": a, "max": 25, "note": an})

    # B. 回调时间 15
    pdays = len(pullback)
    dmin = int(settings.get("pullbackDaysMin", 3))
    dmax = int(settings.get("pullbackDaysMax", 8))
    if dmin <= pdays <= dmax:
        b, bn = 15, f"回调 {pdays} 个交易日，处于 {dmin}~{dmax} 日理想区间"
    elif pdays in (dmin - 1, dmax + 1, dmax + 2, dmax + 3):
        b, bn = 8, f"回调 {pdays} 个交易日，略偏离理想区间"
    elif pdays == 0:
        b, bn = 0, "尚未回调（仍在高位或刚见顶）"
    else:
        b, bn = 0, f"回调 {pdays} 个交易日，不在 {dmin}~{dmax} 日区间"
    detail.append({"key": "B", "label": "回调时间", "score": b, "max": 15, "note": bn})

    # C. 回调幅度 20
    ppct = result["pullback_pct"]
    pmin = float(settings.get("pullbackPctMin", 20))
    pmax = float(settings.get("pullbackPctMax", 30))
    if pmin <= ppct <= pmax:
        c, cn = 20, f"回调 {ppct:.1f}%，处于 {pmin:.0f}%~{pmax:.0f}% 黄金区间"
    elif (pmax < ppct <= pmax + 8) or (max(0.0, pmin - 5) <= ppct < pmin):
        c, cn = 13, f"回调 {ppct:.1f}%，接近理想区间"
    elif 10 <= ppct < pmin:
        c, cn = 6, f"回调 {ppct:.1f}%，幅度偏浅"
    elif ppct <= 0:
        c, cn = 0, "现价高于前期高点，未处于回调状态"
    else:
        c, cn = 0, f"回调 {ppct:.1f}%，偏离 {pmin:.0f}%~{pmax:.0f}% 区间"
    detail.append({"key": "C", "label": "回调幅度", "score": c, "max": 20, "note": cn})

    # D. 缩量程度 20（回调期均量 ÷ 拉升期天量）
    if shrink is None:
        d, dn = 0, "缺乏回调期数据"
    elif shrink <= 0.40:
        d, dn = 20, f"回调期均量仅为拉升天量的 {shrink*100:.0f}%，极度缩量（主力未出逃）"
    elif shrink <= 0.55:
        d, dn = 14, f"回调期均量萎缩至拉升天量的 {shrink*100:.0f}%，缩量充分"
    elif shrink <= 0.75:
        d, dn = 8, f"回调期均量为拉升天量的 {shrink*100:.0f}%，缩量一般"
    else:
        d, dn = 0, f"回调期均量达拉升天量的 {shrink*100:.0f}%，未有效缩量（警惕放量出货）"
    detail.append({"key": "D", "label": "缩量程度", "score": d, "max": 20, "note": dn})

    # E. 均线支撑 10
    dists = []
    for tag, val in (("10日均线", ma10), ("20日均线", ma20)):
        if val:
            dists.append((abs(price - val) / val * 100, tag, val))
    if dists:
        best_dist, best_tag, best_val = min(dists, key=lambda x: x[0])
        if best_dist <= 2:
            e, en = 10, f"现价紧贴{best_tag}({best_val:.2f})，回踩支撑到位"
        elif best_dist <= 4:
            e, en = 7, f"现价距{best_tag}({best_val:.2f}) {best_dist:.1f}%，接近支撑位"
        elif best_dist <= 7:
            e, en = 4, f"现价距{best_tag} {best_dist:.1f}%，尚未完全回踩到位"
        else:
            e, en = 0, f"现价距最近均线 {best_dist:.1f}%，远离支撑位"
    else:
        e, en = 0, "均线数据不足"
    detail.append({"key": "E", "label": "均线支撑", "score": e, "max": 10, "note": en})

    # F. 流通市值 5
    cap = quote.get("float_cap") or 0
    if cap and cap_min <= cap <= cap_max:
        f, fn = 5, f"流通市值 {cap:.1f} 亿，处于 {cap_min:.0f}~{cap_max:.0f} 亿进退自如区间"
    elif cap:
        f, fn = 0, f"流通市值 {cap:.1f} 亿，超出 {cap_min:.0f}~{cap_max:.0f} 亿区间"
    else:
        f, fn = 0, "流通市值未知"
    detail.append({"key": "F", "label": "流通市值", "score": f, "max": 5, "note": fn})

    # G. 拉升期换手 5（用 成交量/流通股本 估算，流通股本由市值与现价推算）
    g, gn = 0, "换手率数据不足"
    if cap and price > 0 and rally_avg_vol > 0:
        float_shares = cap * 1e8 / price
        est_turnover = rally_avg_vol / float_shares * 100 if float_shares > 0 else 0
        if 10 <= est_turnover <= 20:
            g, gn = 5, f"拉升期日均换手约 {est_turnover:.1f}%，换手充分（估算）"
        elif 6 <= est_turnover < 10 or 20 < est_turnover <= 28:
            g, gn = 3, f"拉升期日均换手约 {est_turnover:.1f}%，换手尚可（估算）"
        else:
            g, gn = 0, f"拉升期日均换手约 {est_turnover:.1f}%，偏离 10%~20%（估算）"
    detail.append({"key": "G", "label": "拉升期换手", "score": g, "max": 5, "note": gn})

    total = sum(x["score"] for x in detail)
    result["score"] = total

    # ================= 右侧确认（买点信号）=================
    today_bar = window[-1]
    prev_bar = window[-2]
    today_gain = (today_bar["close"] - prev_bar["close"]) / prev_bar["close"] * 100 if prev_bar["close"] else 0
    # 洗盘箱体上沿：回调期的最高价
    box_top = max((b["high"] for b in pullback), default=peak_price)
    vol_ratio_today = quote.get("vol_ratio") or 0

    # 激进买点：放量反攻，突破洗盘期关键高点
    breakout = bool(pullback) and today_bar["close"] >= box_top * 0.995 and \
        vol_ratio_today >= 1.15 and today_gain > 0
    # 稳健买点：缩量回踩均线，出现止跌小实体
    body = abs(today_bar["close"] - today_bar["open"])
    small_body = body / today_bar["open"] * 100 <= 3.0 if today_bar["open"] else False
    near_ma = any(v and abs(price - v) / v * 100 <= 3.0 for v in (ma10, ma20))
    stable = bool(pullback) and near_ma and small_body and (shrink if shrink is not None else 1) <= 0.75 and today_gain > -3

    result["right_side"] = breakout
    result["stable"] = stable
    result["box_top"] = round(box_top, 2) if box_top else None
    result["rally_high"] = round(peak_price, 2)

    # ================= 分级与建议 =================
    if total >= 80:
        grade = "A 级 · 重点观察"
    elif total >= 65:
        grade = "B 级 · 纳入观察"
    elif total >= 50:
        grade = "C 级 · 等待发酵"
    else:
        grade = "不符合"
    result["grade"] = grade

    if boards == 0:
        advice = "没有前期连板基础，不符合方案「非龙头不炒」的第一层要求，直接排除。"
    elif breakout and total >= 65:
        advice = ("激进买点触发：放量突破洗盘期关键高点（%.2f），右侧资金达成共识。"
                  "按第三层分批建仓规则，首笔仅用观察哨仓位。" % box_top)
    elif stable and total >= 65:
        advice = ("稳健买点触发：缩量回踩均线并出现止跌形态。可逢低分批潜伏，"
                  "但需等待放量确认后才能补足仓位。")
    elif total >= 80:
        advice = "形态高度符合龙回头模型，但右侧尚未确认，等待「放量起爆」信号后再动手。"
    elif total >= 65:
        advice = "具备龙回头雏形，继续跟踪缩量与均线回踩进度。"
    else:
        advice = "多项条件不满足，暂不介入，移出自选或继续观察。"
    result["advice"] = advice

    # ================= 关键价位（供第三、四层使用）=================
    stop_pct = float(settings.get("stopLossPct", 4.0))
    ref = ma10 or price
    result["levels"] = {
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "box_top": result["box_top"],
        "rally_high": result["rally_high"],
        "steady_buy": round(ref, 2),
        "stop_loss": round(ref * (1 - stop_pct / 100.0), 2),
        "take_profit_half": round(ref * (1 + float(settings.get("takeProfitHalfPct", 5)) / 100.0), 2),
        "take_profit_full": round(ref * (1 + float(settings.get("takeProfitFullPct", 10)) / 100.0), 2),
    }

    # 精简K线用于前端画图（最后 30 根）
    result["bars"] = [{"d": b["day"], "o": b["open"], "h": b["high"], "l": b["low"],
                       "c": b["close"], "v": b["volume"],
                       "ma5": b.get("ma5"), "ma10": b.get("ma10"), "ma20": b.get("ma20")}
                      for b in window[-30:]]
    return result


# ----------------------------------------------------------------------------
# 第三层：仓位管理
# ----------------------------------------------------------------------------

def plan_position(price: float, settings: dict, score: int = 0) -> dict:
    """按方案第三层计算观察哨与确认仓。"""
    capital = float(settings.get("capital", 100000))
    max_pct = float(settings.get("maxPositionPct", 50)) / 100.0
    starter_pct = float(settings.get("starterPct", 30)) / 100.0

    budget = capital * max_pct
    first_cash = budget * starter_pct
    if price <= 0:
        return {"ok": False, "reason": "价格无效"}
    first_qty = int(first_cash / price // 100 * 100)
    full_qty = int(budget / price // 100 * 100)
    return {
        "ok": first_qty >= 100,
        "capital": capital,
        "max_cash": round(budget, 2),
        "starter_cash": round(first_cash, 2),
        "starter_qty": first_qty,
        "starter_amount": round(first_qty * price, 2),
        "full_qty": full_qty,
        "full_amount": round(full_qty * price, 2),
        "add_qty": max(0, full_qty - first_qty),
        "note": (f"单股上限 {max_pct*100:.0f}% = {budget:,.0f} 元；"
                 f"首笔观察哨 {starter_pct*100:.0f}% = {first_qty} 股（{first_qty*price:,.0f} 元）。"
                 "右侧放量确认后再补足剩余仓位。"),
    }


# ----------------------------------------------------------------------------
# 第四层：止损止盈纪律检查
# ----------------------------------------------------------------------------

def evaluate_position(pos: dict, quote: dict, settings: dict, ok_days: int = None) -> dict:
    """按方案第四层对单只持仓做纪律诊断（不执行交易，只给提示）。"""
    code = pos.get("code", "")
    name = pos.get("name") or (quote or {}).get("name") or code
    cost = float(pos.get("cost_price") or 0)
    qty = int(pos.get("quantity") or 0)
    price = (quote or {}).get("price") or 0
    pct = (quote or {}).get("pct") or 0

    out = {
        "code": code, "name": name, "cost_price": cost, "quantity": qty,
        "price": price, "pct": pct, "profit_pct": None, "profit_amount": None,
        "hold_days": ok_days if ok_days is not None else 1,
        "action": "持有", "priority": 0, "severity": "normal",
        "rule": "", "reason": "数据不足，无法判断",
    }
    if cost <= 0 or price <= 0:
        return out

    profit = (price - cost) / cost * 100
    out["profit_pct"] = round(profit, 2)
    out["profit_amount"] = round((price - cost) * qty, 2)

    sl = float(settings.get("stopLossPct", 4.0))
    tp_half = float(settings.get("takeProfitHalfPct", 5.0))
    tp_full = float(settings.get("takeProfitFullPct", 10.0))
    stale_days = int(settings.get("staleDays", 3))
    hold_days = out["hold_days"]

    # 1. 硬止损
    if profit <= -sl:
        out.update({
            "action": "清仓", "priority": 1, "severity": "danger",
            "rule": f"绝对止损线 -{sl:.0f}%",
            "reason": f"浮亏 {profit:.2f}% 已触及方案第四层绝对止损线，无条件执行，绝不短线变长线、绝不下跌补仓。",
        })
    # 2. 跌破5日均线（顺势止盈的走弱信号）
    elif profit >= tp_half and (quote or {}).get("price") and \
            (quote or {}).get("ma5") and price < quote["ma5"]:
        out.update({
            "action": "清仓", "priority": 2, "severity": "danger",
            "rule": "跌破5日均线",
            "reason": f"已有浮盈 {profit:.2f}%，但现价跌破5日均线({quote['ma5']})，分时走弱，清仓享受利润。",
        })
    # 3. 二档止盈
    elif profit >= tp_full:
        out.update({
            "action": "清仓", "priority": 3, "severity": "warn",
            "rule": f"二档止盈 +{tp_full:.0f}%",
            "reason": f"浮盈 {profit:.2f}% 达到二档止盈，清仓兑现。",
        })
    # 4. 一档止盈：先落袋一半
    elif profit >= tp_half:
        if qty < 200:
            out.update({
                "action": "持有", "priority": 4, "severity": "info",
                "rule": "单手保护",
                "reason": f"浮盈 {profit:.2f}% 达到一档止盈，但仅 {qty} 股不足一手半仓，继续持有。",
            })
        else:
            out.update({
                "action": "减半", "priority": 4, "severity": "warn",
                "rule": f"一档止盈 +{tp_half:.0f}%",
                "reason": f"浮盈 {profit:.2f}% 达到一档止盈，先落袋一半（约 {int(qty//2//100*100)} 股），立于不败之地。",
            })
    # 5. 时间效率退出
    elif hold_days >= stale_days and profit < 3 and (pct or 0) <= 0:
        out.update({
            "action": "清仓", "priority": 5, "severity": "warn",
            "rule": f"{stale_days} 日未启动",
            "reason": f"已持有 {hold_days} 个交易日仍未启动（浮盈 {profit:.2f}%），按方案释放资金效率。",
        })
    # 6. 盘中走弱预警
    elif (pct or 0) <= -2 and profit < 0:
        out.update({
            "action": "预警", "priority": 6, "severity": "warn",
            "rule": "浮亏且当日走弱",
            "reason": f"当日跌幅 {pct:.2f}% 且浮亏 {profit:.2f}%，盯紧分时与均价线，做好止损准备。",
        })
    else:
        out.update({
            "action": "持有", "priority": 0, "severity": "normal",
            "rule": "持仓健康",
            "reason": f"浮盈 {profit:.2f}%，第 {hold_days} 个交易日，沿5日均线持有观察。",
        })
    return out


# ----------------------------------------------------------------------------
# 实时行情 mojo: 单只股票完整视图（第一~四层共用）
# ----------------------------------------------------------------------------

def stock_view(code: str, settings: dict, pool_boards: int = 0, with_bars: bool = True) -> dict:
    quotes = fetch_quotes([code])
    quote = quotes.get(code)
    if not quote:
        return {"ok": False, "code": code, "error": "未能获取该股票实时行情（可能是停牌或代码有误）"}
    bars = fetch_kline(code, 75)
    bars = merge_live_bar(bars, quote)
    view = analyze_dragon(bars, quote, settings, pool_boards=pool_boards)
    view["ok"] = True
    view["board"] = board_name(code)
    view["is_main_board"] = is_main_board(code)
    view["plan"] = plan_position(quote.get("price") or 0, settings, view["score"])
    if not with_bars:
        view.pop("bars", None)
    return view


# ----------------------------------------------------------------------------
# API 处理
# ----------------------------------------------------------------------------

def api_overview() -> dict:
    warnings = []
    session = session_state()

    indices = fetch_indices()
    if not indices:
        warnings.append("指数行情源不可用")

    mdate = session["market_date"].replace("-", "")
    pool_deadline = time.monotonic() + SCAN_POOL_BUDGET
    up_pool = fetch_limit_pool(mdate, "up", deadline=pool_deadline)
    down_pool = fetch_limit_pool(mdate, "down", deadline=pool_deadline)
    if not up_pool["pool"]:
        warnings.append("涨停池数据源不可用")

    ladder = {}
    for item in up_pool["pool"]:
        ladder[item["boards"]] = ladder.get(item["boards"], 0) + 1
    max_board = max(ladder) if ladder else 0

    # 情绪温度：以跌停家数与最高连板高度为核心（方案第五层）
    ld_count = down_pool["count"]
    panic = int(DEFAULT_SETTINGS["panicLimitDowns"])
    if ld_count >= panic:
        temperature, status = 20, "退潮避险 · 跌停激增，次日空仓或大幅减仓"
    elif up_pool["count"] >= 60 and max_board >= 5:
        temperature, status = 90, "主线亢奋 · 连板梯队完整，聚焦龙一龙二"
    elif up_pool["count"] >= 35:
        temperature, status = 75, "结构性行情 · 资金聚焦少数热点"
    elif up_pool["count"] >= 15:
        temperature, status = 55, "震荡分化 · 谨慎追高，只做龙头"
    else:
        temperature, status = 35, "情绪冰点 · 降低仓位，等待新题材"

    return {
        "ok": True,
        "session": session,
        "settings": load_store().get("settings", {}),
        "indices": indices,
        "limitup": {"count": up_pool["count"], "max_board": max_board, "ladder": ladder},
        "limitdown": {"count": ld_count},
        "sentiment": {
            "temperature": temperature,
            "status": status,
            "panic_threshold": panic,
            "is_panic": ld_count >= panic,
        },
        "sources": {
            "快照 / 指数": "腾讯 qt.gtimg.cn",
            "K线 / 交易日历": "新浪 CN_MarketData",
            "涨停 / 跌停池": "东财 push2ex",
            "热点聚合": "涨停池按板块聚合",
            "requests": _STATS["requests"],
            "errors": _STATS["errors"],
        },
        "warnings": warnings,
    }


def api_hot_boards(days: int = 5) -> dict:
    """第一层「选热点」数据。

    主视图 hottest：由涨停池按行业板块聚合（真实资金共识，贴合方案原文）；
    辅视图 concept/industry：新浪板块涨幅榜，用于交叉验证题材热度。
    """
    warnings = []
    mdate = market_date().replace("-", "")
    hottest = fetch_hot_sectors(mdate, top=12)
    if not hottest:
        warnings.append("涨停池不可用，热点聚合暂无数据")

    # 近 N 日涨停次数，用于判断题材是「今天爆发」还是「持续发酵」
    recent = {}
    for pool in fetch_pools_parallel(trading_dates(limit=max(2, min(days, 10))), "up"):
        for item in pool["pool"]:
            sec = (item.get("sector") or "").strip()
            if sec:
                recent[sec] = recent.get(sec, 0) + 1
    for rec in hottest:
        rec["recent_limitups"] = recent.get(rec["sector"], rec["limitup_count"])

    concept = fetch_boards("concept", 14)
    industry = fetch_boards("industry", 14)
    if not concept and not industry:
        warnings.append("新浪板块榜暂不可用")

    return {
        "ok": True,
        "date": mdate,
        "hottest": hottest,
        "concept": concept,
        "industry": industry,
        "updated": time.strftime("%H:%M:%S"),
        "warnings": warnings,
    }


def api_limitup(date: str = None) -> dict:
    date = date or market_date().replace("-", "")
    pool = fetch_limit_pool(date, "up")
    ladder = {}
    for item in pool["pool"]:
        ladder[item["boards"]] = ladder.get(item["boards"], 0) + 1
    # 按连板数降序
    items = sorted(pool["pool"], key=lambda x: (-x["boards"], x["first_seal"] or "99:99"))
    return {
        "ok": True,
        "date": date,
        "count": pool["count"],
        "ladder": ladder,
        "max_board": max(ladder) if ladder else 0,
        "items": items,
    }


def api_dragons(days: int = 10) -> dict:
    """近 N 个交易日涨停池聚合出的「龙头池」——对应方案第五层的每日功课。"""
    dates = trading_dates(limit=max(1, min(days, 15)))
    agg = {}
    for pool in fetch_pools_parallel(dates, "up"):
        pool_date = pool["date"]
        for item in pool["pool"]:
            rec = agg.setdefault(item["code"], {
                "code": item["code"],
                "name": item["name"],
                "max_boards": 0,
                "limitup_days": 0,
                "last_date": pool_date,
                "sectors": set(),
                "best_days": 0,
            })
            rec["max_boards"] = max(rec["max_boards"], item["boards"])
            rec["limitup_days"] += 1
            if item["sector"]:
                rec["sectors"].add(item["sector"])
            rec["best_days"] = max(rec["best_days"], item["days"])
            if pool_date > rec["last_date"]:
                rec["last_date"] = pool_date

    items = []
    for rec in agg.values():
        if not is_main_board(rec["code"]):
            continue
        rec["sectors"] = sorted(rec["sectors"])
        rec["board"] = board_name(rec["code"])
        items.append(rec)

    items.sort(key=lambda r: (-r["max_boards"], -r["limitup_days"]))
    items = items[:80]

    # 补充实时行情
    quotes = fetch_quotes([r["code"] for r in items])
    for rec in items:
        q = quotes.get(rec["code"]) or {}
        rec["price"] = q.get("price")
        rec["pct"] = q.get("pct")
        rec["turnover"] = q.get("turnover")
        rec["vol_ratio"] = q.get("vol_ratio")
        rec["float_cap"] = q.get("float_cap")
        rec["limit_up"] = q.get("limit_up")
        rec["ma10"] = None
        rec["distance_to_ma10_pct"] = None

    return {
        "ok": True,
        "window": dates,
        "items": items,
        "note": ("由近 %d 个交易日涨停池聚合，用于方案第五层「建立龙回头股票池」。"
                 "max_boards 表示窗口内最高连板数。" % len(dates)),
    }


def api_scan(limit: int = 40, days: int = 10, mode: str = "dragon") -> dict:
    """对候选池做龙回头评分（第一层→第二层）。

    每个阶段都有**硬性时间预算** —— 上游接口抽风时，宁可少评几只股票，
    也不能让一次扫描拖到几分钟（定时推送必须准点发出）。
    """
    settings = load_store().get("settings", {})
    warnings = []
    started = time.time()

    candidates = {}
    mdate = market_date().replace("-", "")

    # 候选来源 1：近 N 日涨停池中的连板股（前期走牛）
    pool_deadline = time.monotonic() + SCAN_POOL_BUDGET
    for pool in fetch_pools_parallel(trading_dates(limit=max(3, min(days, 15))),
                                     "up", deadline=pool_deadline):
        for item in pool["pool"]:
            if not is_main_board(item["code"]):
                continue
            rec = candidates.setdefault(item["code"], {"boards": 0, "sector": ""})
            if item["boards"] >= 2:
                rec["boards"] = max(rec["boards"], item["boards"])
                if item["sector"]:
                    rec["sector"] = item["sector"]

    if not candidates:
        warnings.append("涨停池来源不可用，已降级为仅扫描当日强势股")

    # 候选来源 2：当日涨停池全部主板股
    for item in fetch_limit_pool(mdate, "up", deadline=pool_deadline)["pool"]:
        if is_main_board(item["code"]):
            rec = candidates.setdefault(item["code"], {"boards": 0, "sector": ""})
            rec["boards"] = max(rec["boards"], item["boards"])
            if item["sector"]:
                rec["sector"] = item["sector"]

    # 候选来源 3：自选池
    for item in load_store().get("watchlist", []):
        if item.get("code"):
            candidates.setdefault(str(item["code"]), {"boards": 0, "sector": ""})

    codes = list(candidates)[:max(10, min(limit, 80))]
    codes = [c for c in codes if is_main_board(c)]

    # 并发抓取K线 + 快照（串行 40~80 只约需 30 秒，并发后约 3 秒）
    views = []
    quotes = fetch_quotes(codes)
    kline_deadline = time.monotonic() + SCAN_KLINE_BUDGET

    def build(code, deadline):
        quote = quotes.get(code)
        if not quote or not quote.get("price"):
            return None
        try:
            bars = fetch_kline(code, 75, deadline=deadline)
            if not bars:
                return None
            bars = merge_live_bar(bars, quote)
            return analyze_dragon(bars, quote, settings,
                                  pool_boards=candidates[code]["boards"])
        except Exception as exc:                        # noqa: BLE001
            _note_error(exc)
            return None

    def run_pass(subset, deadline):
        """并发跑一轮，返回成功的 view 列表。"""
        got = []
        if not subset:
            return got
        # 线程数略高于 CPU 数：这里是纯等待网络 I/O，不是计算
        with ThreadPoolExecutor(max_workers=min(16, max(2, len(subset)))) as pool:
            for view in pool.map(lambda c: build(c, deadline), subset):
                if view:
                    got.append(view)
        return got

    views = run_pass(codes, kline_deadline)

    # 补一轮：第一轮没成功的再试一次。单个请求偶发失败很常见，而一次扫描平白
    # 掉 2~3 只股票会直接影响排名。只在时间预算还有富余时才做，所以最坏情况
    # 仍然被 SCAN_KLINE_BUDGET 卡死，不会把 178 秒那种事放回来。
    done = {v["code"] for v in views}
    retry = [c for c in codes if c not in done]
    left = kline_deadline - time.monotonic()
    if retry and left > 5.0:
        views.extend(run_pass(retry, time.monotonic() + min(10.0, left)))

    miss = [c for c in codes if c not in {v["code"] for v in views}]
    if miss:
        warnings.append("以下 %d 只未能在时间预算内取到K线，已跳过：%s"
                        % (len(miss), " ".join(miss[:8])
                           + (" …" if len(miss) > 8 else "")))

    # 只保留有连板基础的（方案第一层：非龙头不炒）
    dragons = [v for v in views if v["boards"] >= 2]
    dragons.sort(key=lambda v: (-v["score"], -v.get("boards", 0)))
    others = [v for v in views if v["boards"] < 2]
    others.sort(key=lambda v: -v["score"])

    for v in dragons:
        v["plan"] = plan_position(v.get("price") or 0, settings, v["score"])
        v["sector"] = candidates.get(v["code"], {}).get("sector", "")
    for v in others[:12]:
        v["plan"] = plan_position(v.get("price") or 0, settings, v["score"])
        v["sector"] = candidates.get(v["code"], {}).get("sector", "")

    # 精简K线：列表页只用最后 18 根，详情页按需再取；档案里也保留同一份用于缩略图
    for v in dragons + others[:12]:
        v["bars"] = v.get("bars", [])[-18:]

    result = {
        "ok": True,
        "date": market_date(),
        "elapsed": round(time.time() - started, 2),
        "scanned": len(views),
        "total_candidates": len(candidates),
        "count": len(dragons),
        "items": dragons,
        "others": others[:12],
        "warnings": warnings,
        "settings": settings,
    }

    # 每次成功扫描后自动归档：同一天同一只股票只留一条，更新「最近命中」，
    # 同时保留首次命中的时间与价格，形成可回看的龙回头时间轴。
    try:
        result["archive"] = _archive_scan(result)
    except Exception as exc:                            # noqa: BLE001
        _note_error(exc)
        result["archive"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def api_quote(codes) -> dict:
    quotes = fetch_quotes(codes)
    return {"ok": True, "items": [quotes[c] for c in codes if c in quotes],
            "missing": [c for c in codes if c not in quotes]}


def api_preview(code: str) -> dict:
    """悬停预览的日K部分。

    只返回快照与末 40 根日K（不含分时），因为日K 有 600 秒缓存、
    扫描过后基本已命中，前端可以先秒出 K 线，再异步补分时。
    """
    code = str(code or "").strip()
    if not code:
        return {"ok": False, "code": code, "error": "缺少股票代码"}

    quote = fetch_quotes([code]).get(code)
    if not quote or not quote.get("price"):
        return {"ok": False, "code": code, "error": "未获取到该股票实时行情"}

    bars = merge_live_bar(fetch_kline(code, 60), quote)

    return {
        "ok": True,
        "code": code,
        "name": quote.get("name") or code,
        "price": quote.get("price"),
        "pct": quote.get("pct"),
        "pre_close": quote.get("pre_close") or 0.0,
        "turnover": quote.get("turnover"),
        "vol_ratio": quote.get("vol_ratio"),
        "float_cap": quote.get("float_cap"),
        "limit_up": quote.get("limit_up"),
        "bars": [{"d": b["day"], "o": b["open"], "h": b["high"], "l": b["low"],
                  "c": b["close"], "v": b["volume"],
                  "ma5": b.get("ma5"), "ma10": b.get("ma10")} for b in bars[-40:]],
    }


def api_minute(code: str) -> dict:
    """悬停预览的分时部分（独立接口，便于前端分两步渲染）。"""
    code = str(code or "").strip()
    if not code:
        return {"ok": False, "code": code, "error": "缺少股票代码"}
    minute = fetch_minute(code)
    if not minute.get("points"):
        return {"ok": False, "code": code, "error": "分时数据不可用"}
    quote = fetch_quotes([code]).get(code) or {}
    return {
        "ok": True,
        "code": code,
        "date": minute.get("date") or "",
        "pre_close": quote.get("pre_close") or minute.get("pre_close") or 0.0,
        "points": minute.get("points") or [],
    }


def api_evaluate(payload: dict) -> dict:
    settings = {**DEFAULT_SETTINGS, **load_store().get("settings", {}), **payload.get("settings", {})}
    positions = payload.get("positions", [])
    quotes = fetch_quotes([p.get("code") for p in positions if p.get("code")])
    # 补 5 日均线
    results = []
    for p in positions:
        code = str(p.get("code") or "")
        q = dict(quotes.get(code) or {})
        if code:
            bars = fetch_kline(code, 30)
            if bars:
                q["ma5"] = bars[-1].get("ma5")
        ok_days = _count_trading_days(p.get("buy_date"))
        results.append(evaluate_position(p, q, settings, ok_days))
    return {"ok": True, "settings": settings, "items": results}


def _count_trading_days(buy_date) -> int:
    if not buy_date:
        return 1
    try:
        d0 = _dt.datetime.strptime(str(buy_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return 1
    today = _dt.date.today()
    n = 0
    d = d0
    while d < today:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return max(1, n)


# ----------------------------------------------------------------------------
# 微信推送：把龙回头扫描结果单向往外发
# ----------------------------------------------------------------------------

def _num(value, digits: int = 2) -> str:
    try:
        return ("%%.%df" % digits) % float(value)
    except (TypeError, ValueError):
        return "—"


def _money(value) -> str:
    try:
        return "{:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return "—"


def _mood_line() -> str:
    """一行市场情绪摘要；任何失败都返回空串，不影响推送主流程。"""
    try:
        ov = api_overview()
        lp = ov.get("limitup") or {}
        ld = ov.get("limitdown") or {}
        st = ov.get("sentiment") or {}
        return ("涨停 %s 家 · 最高 %s 板 · 跌停 %s 家 · 情绪温度 %s（%s）"
                % (lp.get("count", "?"), lp.get("max_board", "?"), ld.get("count", "?"),
                   st.get("temperature", "?"), st.get("status", "")))
    except Exception as exc:                            # noqa: BLE001
        _note_error(exc)
        return ""


def build_scan_message(scan: dict, selected: list = None, market: str = None,
                       site: str = None) -> tuple:
    """把一次扫描结果整理成 (标题, markdown 正文)。两个推送通道都用 markdown。"""
    items = scan.get("items") or []
    picked = items if selected is None else selected
    others = scan.get("others") or []
    mdate = market or market_date()
    stamp = _dt.datetime.now().strftime("%m-%d %H:%M")

    title = "龙回头扫描 · %s · 命中 %d 只" % (mdate, len(items))

    L = ["## 龙回头扫描", "",
         "**交易日** %s　**跑批** %s" % (mdate, stamp)]
    mood = _mood_line()
    if mood:
        L += ["", "**市场情绪**　" + mood]
    L += ["", "**扫描概况**　候选 %s 只 · 实际评分 %s 只 · B 级以上 **%d** 只 · 耗时 %ss"
          % (scan.get("total_candidates", "?"), scan.get("scanned", "?"),
             len(items), scan.get("elapsed", "?"))]

    if not picked:
        L += ["", "---", "",
              "本批次**没有**达标的龙回头标的。方案第一层：非龙头不炒，"
              "宁可空仓等下一次机会。"]
    else:
        if len(picked) < len(items):
            L += ["", "*本消息只推送评分 ≥ 阈值的 %d 只，完整榜单请在系统里查看。*" % len(picked)]
        for idx, v in enumerate(picked, 1):
            L += ["", "---", "",
                  "**%d. %s %s**　`%s 分 · %s`"
                  % (idx, v.get("name") or "", v.get("code") or "",
                     v.get("score"), v.get("grade") or "")]
            tags = []
            if v.get("boards"):
                tags.append("%s 连板" % v["boards"])
            if v.get("pullback_days"):
                tags.append("回调 %s 日" % v["pullback_days"])
            if v.get("pullback_pct"):
                tags.append("回调 %s%%" % _num(v["pullback_pct"], 1))
            if v.get("shrink_ratio") is not None:
                tags.append("缩量比 %d%%" % round(v["shrink_ratio"] * 100))
            if v.get("sector"):
                tags.append(str(v["sector"]))
            if tags:
                L.append("> " + " · ".join(tags))

            quote = []
            if v.get("price"):
                quote.append("现价 **%s**" % _num(v.get("price"), 2))
            if v.get("pct") is not None:
                quote.append("%+.2f%%" % float(v["pct"]))
            if v.get("turnover") is not None:
                quote.append("换手 %s%%" % _num(v.get("turnover"), 2))
            if v.get("vol_ratio") is not None:
                quote.append("量比 %s" % _num(v.get("vol_ratio"), 2))
            if v.get("float_cap"):
                quote.append("流通 %s 亿" % _num(v.get("float_cap"), 0))
            if quote:
                L.append("- " + "　".join(quote))

            if v.get("right_side"):
                buy = "**激进买点已触发**：放量突破洗盘箱体上沿"
            elif v.get("stable"):
                buy = "**稳健买点已触发**：缩量回踩均线止跌"
            else:
                buy = "买点未触发，仅观察"
            if v.get("ma5"):
                buy += "（MA5 %s）" % _num(v["ma5"], 2)
            L.append("- 买点：" + buy)

            plan = v.get("plan") or {}
            if plan.get("ok"):
                L.append("- 仓位：首笔 %s 股 ≈ %s 元，上限补至 %s 股"
                         % (plan.get("starter_qty"), _money(plan.get("starter_amount")),
                            plan.get("full_qty")))

        if others:
            L += ["", "---", "",
                  "另有 %d 只未达连板基础或评分不足，已过滤（非龙头不炒）。" % len(others)]

    if site:
        L += ["", "**系统入口**　" + site]
    L += ["", "> 本消息为纪律提示，不构成投资建议。系统不连接券商、不读取账户、不发送任何委托。"]

    return title, "\n".join(L)


def resolve_notify(settings: dict, override: dict = None) -> list:
    """决定这次要发给哪些通道。返回 ``[(通道, 密钥), ...]``。

    支持两种临时覆盖写法（只在本次生效，不写回设置）：
      * 多通道：``{"channels": ["serverchan","wecom"], "keys": {...}}``
      * 单通道：``{"channel": "serverchan", "key": "..."}``（命令行用）
    """
    override = override or {}
    out = []

    def add(channel, key):
        ch = str(channel or "").strip().lower()
        key = str(key or "").strip()
        if ch and ch not in ("off", "none", "close") and key and ch not in [c for c, _ in out]:
            out.append((ch, key))

    if isinstance(override.get("channels"), list):
        keys = override.get("keys") or {}
        for ch in override["channels"]:
            add(ch, keys.get(str(ch).strip().lower()) if isinstance(keys, dict) else None)
        return out

    if override.get("channel"):
        add(override["channel"], override.get("key"))
        return out

    keys = settings.get("notifyKeys") or {}
    for ch in settings.get("notifyChannels") or []:
        ch = str(ch or "").strip().lower()
        add(ch, keys.get(ch) if isinstance(keys, dict) else None)
    return out


def resolve_formats(settings: dict, override: dict = None) -> dict:
    """每个通道该用什么格式发。目前只有企业微信需要区分。

    企业微信群机器人的 markdown 同步到个人微信（微信插件）会显示成
    「[链接] 暂不支持此消息类型」，所以默认走 text。
    """
    override = override or {}
    fmt = str(override.get("wecomFormat")
              or settings.get("notifyWecomFormat") or "text").strip().lower()
    if fmt not in _push.WECOM_FORMATS:
        fmt = "text"
    return {"wecom": fmt}


def notify_scan(settings: dict, override: dict = None) -> dict:
    """跑一次扫描并按设置推送。override 里的项只对本次生效。"""
    override = override or {}
    min_score = int(override.get("minScore") or settings.get("notifyMinScore") or 65)
    top_n = int(override.get("top") or settings.get("notifyTopN") or 8)
    limit = int(override.get("limit") or settings.get("notifyScanLimit") or 40)
    days = int(override.get("days") or settings.get("notifyDays") or 10)

    scan = api_scan(limit, days)
    hits = scan.get("items") or []
    picked = [v for v in hits if (v.get("score") or 0) >= min_score][:max(1, top_n)]

    site = "http://%s:%d" % (HOST, PORT)
    if HOST in ("0.0.0.0", "::"):
        site = "http://%s:%d" % (_lan_ip(), PORT)
    title, body = build_scan_message(scan, selected=picked, site=site)

    res = _push.push_many(resolve_notify(settings, override), title, body,
                          resolve_formats(settings, override))
    return {
        "ok": bool(res.get("ok")),
        "mode": "scan",
        "channel": res.get("channel"),
        "detail": res.get("detail"),
        "results": res.get("results"),
        "title": title,
        "hit": len(hits),
        "picked": len(picked),
        "minScore": min_score,
        "scanned": scan.get("scanned"),
        "elapsed": scan.get("elapsed"),
        "preview": body,
    }


def api_notify(payload: dict) -> dict:
    """POST /api/notify

    * ``{"test": true}``            → 只发一条连通性测试
    * ``{"scan": true}`` 或缺省     → 跑一次扫描并推送
    * 可临时覆盖 channels/keys（多通道）或 channel/key（单通道），
      以及 minScore / top / limit / days，均不写回设置。
    """
    payload = payload or {}
    settings = load_store().get("settings", {})

    if payload.get("test"):
        pairs = resolve_notify(settings, payload)
        fmts = resolve_formats(settings, payload)
        title = "龙回头 · 推送通道测试"
        body = ("## 推送通道测试\n\n"
                "如果你在微信里看到这条消息，说明通道已经打通。\n\n"
                "- 通道：`%s`\n- 时间：%s\n- 交易日：%s\n\n"
                "> 本条为测试消息，不含任何交易指令。"
                % (" + ".join(c for c, _ in pairs) or "未配置",
                   _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), market_date()))
        res = _push.push_many(pairs, title, body, fmts)
        return {"ok": bool(res.get("ok")), "mode": "test", "channel": res.get("channel"),
                "detail": res.get("detail"), "results": res.get("results"), "title": title}

    return notify_scan(settings, payload)


# ----------------------------------------------------------------------------
# 本地存储
# ----------------------------------------------------------------------------

_DEFAULT_STORE = {
    "settings": dict(DEFAULT_SETTINGS),
    "watchlist": [],
    "positions": [],
    "reviews": [],
    "trades": [],
    # 结构：{"YYYY-MM": {"YYYY-MM-DD": {"date": ..., "items": {code: {...}}}}}
    "dragonArchive": {},
}

# 本地存储的读改写锁。扫描线程（手动 / 定时推送）可能同时归档，而持仓、复盘也会写
# store.json；没有锁时 load→改→save 会互相覆盖。RLock 允许 save_store 内部再次
# 调用 load_store，不会死锁。
_STORE_LOCK = threading.RLock()


def _normalize_store(data: dict) -> dict:
    """把磁盘 / Redis 读到的原始结构补齐成前端期望的 store。"""
    data = data if isinstance(data, dict) else {}
    merged = dict(_DEFAULT_STORE)
    merged.update(data)
    raw = dict(data.get("settings") or {})
    if "notifyChannels" not in raw:
        # 旧版是单通道（notifyChannel / notifyKey），升级成列表 + 字典。
        # 只在「存储里还没有新字段」时迁移，这样用户清空勾选后不会被旧值复活。
        ch = str(raw.get("notifyChannel") or "off").strip().lower()
        key = str(raw.get("notifyKey") or "").strip()
        live = ch not in ("", "off", "none") and bool(key)
        raw["notifyChannels"] = [ch] if live else []
        raw["notifyKeys"] = {ch: key} if live else {}
    merged["settings"] = {**DEFAULT_SETTINGS, **raw}
    merged["persisted"] = DATA_WRITABLE
    return merged


# --- Upstash REST 读写 ------------------------------------------------------
# 为什么不直接用 redis-py：本项目坚持零第三方依赖，而 Upstash 的 REST 接口
# 用标准库 urllib 就能调用。所有命令都走根路径的 POST（命令数组），
# 这样 GET / SET / KEYS / DEL 不需要分别记一套 URL 规则。

def _kv_cmd(*args, timeout: float = 8.0):
    body = json.dumps(list(args), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _KV_URL, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + _KV_TOKEN,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError("Upstash: %s" % payload["error"])
    return payload.get("result") if isinstance(payload, dict) else payload


def _kv_encode(value) -> str:
    """JSON → gzip → base64。档案里 K 线快照很占空间，压缩后通常只剩 1/5。"""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "gz:" + base64.b64encode(gzip.compress(raw, 6)).decode("ascii")


def _kv_decode(text):
    if text is None:
        return None
    text = str(text)
    if text.startswith("gz:"):
        return json.loads(gzip.decompress(base64.b64decode(text[3:])).decode("utf-8"))
    return json.loads(text)


def _kv_meta_key() -> str:
    return _KV_PREFIX + "meta"


def _kv_archive_prefix() -> str:
    return _KV_PREFIX + "archive:"


def _kv_load_cloud():
    """从 Redis 读回完整 store；键不存在（空库）时返回 None。"""
    meta = _kv_decode(_kv_cmd("GET", _kv_meta_key()))
    if not isinstance(meta, dict):
        return None
    archive = {}
    prefix = _kv_archive_prefix()
    for key in _kv_cmd("KEYS", prefix + "*") or []:
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        month = key[len(prefix):]
        if not month:
            continue
        part = _kv_decode(_kv_cmd("GET", key))
        if isinstance(part, dict):
            archive[month] = part
    return {"meta": meta, "archive": archive}


def _kv_save_cloud(meta: dict, archive: dict) -> None:
    """元数据存一个键，档案按月各存一个键，并清掉已删除的月份。"""
    clean_meta = {k: v for k, v in meta.items()
                  if k not in ("persisted", "dragonArchive")}
    _kv_cmd("SET", _kv_meta_key(), _kv_encode(clean_meta))

    prefix = _kv_archive_prefix()
    old_keys = set(_kv_cmd("KEYS", prefix + "*") or [])
    for month, month_map in (archive or {}).items():
        key = prefix + str(month)
        _kv_cmd("SET", key, _kv_encode(month_map))
        old_keys.discard(key)
    for key in old_keys:
        _kv_cmd("DEL", key)


def _load_local_store():
    """读本地 data/store.json；不存在或损坏时返回 None。"""
    try:
        if os.path.exists(STORE_FILE):
            # utf-8-sig：用户手工改 store.json（或用 PowerShell 生成）时很容易带上 BOM，
            # 用纯 "utf-8" 读会让 json.load 直接抛异常，于是整个配置被静默重置成默认值
            # （推送密钥、持仓、复盘全"丢"）。utf-8-sig 读没有 BOM 的文件也完全正常。
            with open(STORE_FILE, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception as exc:                            # noqa: BLE001
        _note_error(exc)
    return None


def load_store() -> dict:
    global DATA_WRITABLE
    with _STORE_LOCK:
        if _KV_ENABLED:
            try:
                cloud = _kv_load_cloud()
                DATA_WRITABLE = True
                if cloud is not None:
                    data = dict(cloud["meta"])
                    data["dragonArchive"] = cloud["archive"]
                    return _normalize_store(data)
                # 空库：允许第一次用本地文件里的数据做迁移（Vercel 上通常没有）。
            except Exception as exc:                    # noqa: BLE001
                _note_error(exc)
                DATA_WRITABLE = False

        data = _load_local_store()
        if data is None:
            data = {}
        return _normalize_store(data)


def save_store(payload: dict) -> dict:
    global DATA_WRITABLE
    with _STORE_LOCK:
        current = load_store()
        for key in ("watchlist", "positions", "reviews", "trades", "dragonArchive"):
            if key in payload:
                current[key] = payload[key]
        if "settings" in payload:
            # 设置项按「字段」合并，而不是整体替换：前端只提交表单里渲染出来的字段，
            # 整体替换会把没渲染的项（例如微信 SendKey）静默抹掉。
            merged = dict(DEFAULT_SETTINGS)
            merged.update(current.get("settings") or {})
            for key, value in (payload.get("settings") or {}).items():
                if value is not None:
                    merged[key] = value
            current["settings"] = merged

        # 本地文件始终写成一份备份（本地开发时它就是主存储；云端只读时忽略失败）。
        local_ok = False
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(STORE_FILE, "w", encoding="utf-8") as fh:
                json.dump(current, fh, ensure_ascii=False, indent=2)
            local_ok = True
        except OSError as exc:
            if not _KV_ENABLED:
                if DATA_WRITABLE:
                    _note_error(exc)
                DATA_WRITABLE = False

        if _KV_ENABLED:
            try:
                _kv_save_cloud(
                    {k: v for k, v in current.items() if k != "persisted"},
                    current.get("dragonArchive") or {},
                )
                DATA_WRITABLE = True
            except Exception as exc:                    # noqa: BLE001
                _note_error(exc)
                DATA_WRITABLE = False
        else:
            DATA_WRITABLE = local_ok

        current["persisted"] = DATA_WRITABLE
        return current


# ----------------------------------------------------------------------------
# 龙回头档案：把「月 → 日 → 标的」封存成可展开的卡片
# ----------------------------------------------------------------------------

_ARCHIVE_SNAPSHOT_LIMIT = 24
_ARCHIVE_BAR_LIMIT = 18


def _archive_stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _archive_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _archive_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _archive_snapshot(view: dict, at: str) -> dict:
    """一次命中的瞬时快照：时间 + 股价 + 涨幅 + 评分。"""
    return {
        "at": at,
        "price": _archive_float(view.get("price")),
        "pct": _archive_float(view.get("pct")),
        "score": _archive_int(view.get("score")),
        "vol_ratio": _archive_float(view.get("vol_ratio")),
    }


def _archive_record(view: dict, now: str, prev: dict = None) -> dict:
    """把扫描结果压缩成档案记录。同一天重复命中时保留首次时间与价格。"""
    prev = prev or {}
    snapshots = [s for s in (prev.get("snapshots") or []) if isinstance(s, dict)]
    snapshots.append(_archive_snapshot(view, now))

    details = []
    for d in view.get("details") or []:
        if isinstance(d, dict):
            details.append({k: d.get(k) for k in
                            ("key", "label", "score", "max", "note")})

    levels = {}
    raw_levels = view.get("levels")
    if isinstance(raw_levels, dict):
        levels = {k: raw_levels.get(k) for k in
                  ("ma5", "ma10", "ma20", "box_top", "rally_high",
                   "steady_buy", "stop_loss", "take_profit_half", "take_profit_full")}

    plan = {}
    raw_plan = view.get("plan")
    if isinstance(raw_plan, dict):
        plan = {k: raw_plan.get(k) for k in
                ("ok", "max_cash", "starter_qty", "starter_amount",
                 "add_qty", "full_qty", "full_amount", "reason")}

    bars = []
    for b in (view.get("bars") or [])[-_ARCHIVE_BAR_LIMIT:]:
        if isinstance(b, dict):
            bars.append({k: b.get(k) for k in
                         ("d", "o", "h", "l", "c", "v", "ma5", "ma10", "ma20")})

    price = _archive_float(view.get("price"))
    return {
        "code": str(view.get("code") or "").strip(),
        "name": str(view.get("name") or "").strip(),
        "price": price,
        "pct": _archive_float(view.get("pct")),
        "turnover": _archive_float(view.get("turnover")),
        "vol_ratio": _archive_float(view.get("vol_ratio")),
        "float_cap": _archive_float(view.get("float_cap")),
        "score": _archive_int(view.get("score")),
        "grade": str(view.get("grade") or ""),
        "boards": _archive_int(view.get("boards")),
        "pullback_days": _archive_int(view.get("pullback_days")),
        "pullback_pct": _archive_float(view.get("pullback_pct")),
        "shrink_ratio": _archive_float(view.get("shrink_ratio")),
        "ma5": _archive_float(view.get("ma5")),
        "ma10": _archive_float(view.get("ma10")),
        "ma20": _archive_float(view.get("ma20")),
        "right_side": bool(view.get("right_side")),
        "stable": bool(view.get("stable")),
        "box_top": _archive_float(view.get("box_top")),
        "rally_high": _archive_float(view.get("rally_high")),
        "sector": str(view.get("sector") or "").strip(),
        "advice": str(view.get("advice") or ""),
        "details": details,
        "levels": levels,
        "plan": plan,
        "bars": bars,
        # 首次命中：时间与价格永远不覆盖；之后每次扫描只追加快照。
        "firstMatchedAt": (prev.get("firstMatchedAt")
                           or prev.get("matchedAt") or now),
        "lastMatchedAt": now,
        "firstPrice": (prev.get("firstPrice")
                       if prev.get("firstPrice") is not None else price),
        "lastPrice": price,
        "hitCount": _archive_int(prev.get("hitCount")) + 1,
        "snapshots": snapshots[-_ARCHIVE_SNAPSHOT_LIMIT:],
    }


def _archive_scan(scan: dict, force: bool = False) -> dict:
    """把一次扫描中达到档案评分线的标的写入 store。"""
    settings = load_store().get("settings", {})
    if not force and not settings.get("archiveAuto", True):
        return {"ok": True, "saved": False, "skipped": True,
                "reason": "自动存档已关闭"}

    now = _archive_stamp()
    date = str(scan.get("date") or market_date())[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        date = _dt.date.today().strftime("%Y-%m-%d")
    month = date[:7]
    min_score = _archive_int(settings.get("archiveMinScore"), 65)

    hits = [v for v in (scan.get("items") or [])
            if isinstance(v, dict) and _archive_int(v.get("score")) >= min_score]

    with _STORE_LOCK:
        store = load_store()
        archive = store.get("dragonArchive")
        if not isinstance(archive, dict):
            archive = {}
        month_map = archive.get(month)
        if not isinstance(month_map, dict):
            month_map = {}
        day = month_map.get(date)
        if not isinstance(day, dict):
            day = {"date": date, "month": month, "createdAt": now, "items": {}}

        items = day.get("items")
        if isinstance(items, list):                     # 兼容早期手写格式
            items = {str(it.get("code")): it for it in items if isinstance(it, dict)}
        if not isinstance(items, dict):
            items = {}

        added = updated = 0
        for view in hits:
            code = str(view.get("code") or "").strip()
            if not code:
                continue
            prev = items.get(code)
            items[code] = _archive_record(view, now, prev if isinstance(prev, dict) else None)
            if isinstance(prev, dict):
                updated += 1
            else:
                added += 1

        if not items:
            return {"ok": True, "saved": False, "date": date, "month": month,
                    "added": 0, "updated": 0, "count": 0, "minScore": min_score}

        day["items"] = items
        day["count"] = len(items)
        day["bestScore"] = max(_archive_int(v.get("score")) for v in items.values())
        day["updatedAt"] = now
        day["lastScan"] = {
            "at": now,
            "scanned": _archive_int(scan.get("scanned")),
            "candidates": _archive_int(scan.get("total_candidates")),
            "minScore": min_score,
        }
        month_map[date] = day
        archive[month] = month_map
        saved = save_store({"dragonArchive": archive}).get("persisted", False)

    return {
        "ok": True,
        "saved": bool(saved),
        "date": date,
        "month": month,
        "added": added,
        "updated": updated,
        "count": len(items),
        "minScore": min_score,
    }


def _archive_sorted_items(raw) -> list:
    if isinstance(raw, dict):
        values = list(raw.values())
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    values = [v for v in values if isinstance(v, dict) and v.get("code")]
    values.sort(key=lambda v: (-_archive_int(v.get("score")), str(v.get("code"))))
    return values


def api_archive() -> dict:
    """返回完整档案树：月份倒序 → 日期倒序 → 标的按评分倒序。"""
    store = load_store()
    settings = store.get("settings", {})
    raw = store.get("dragonArchive")
    if not isinstance(raw, dict):
        raw = {}

    months = []
    for month_key in sorted(raw.keys(), reverse=True):
        month_map = raw.get(month_key)
        if not isinstance(month_map, dict):
            continue
        days = []
        for date_key in sorted(month_map.keys(), reverse=True):
            day = month_map.get(date_key)
            if not isinstance(day, dict):
                continue
            items = _archive_sorted_items(day.get("items"))
            if not items:
                continue
            sectors = []
            for item in items:
                sector = str(item.get("sector") or "").strip()
                if sector and sector not in sectors:
                    sectors.append(sector)
            stamps = [str(i.get("lastMatchedAt") or i.get("firstMatchedAt") or "")
                      for i in items]
            stamps = [s for s in stamps if s]
            days.append({
                "date": str(day.get("date") or date_key),
                "count": len(items),
                "bestScore": max(_archive_int(i.get("score")) for i in items),
                "sectors": sectors[:6],
                "updatedAt": day.get("updatedAt") or (max(stamps) if stamps else ""),
                "lastMatchedAt": max(stamps) if stamps else "",
                "items": items,
            })
        if not days:
            continue
        total = sum(d["count"] for d in days)
        months.append({
            "month": str(month_key),
            "days": days,
            "daysCount": len(days),
            "count": total,
            "bestScore": max(d["bestScore"] for d in days),
            "firstDate": days[-1]["date"],
            "lastDate": days[0]["date"],
        })

    total_records = sum(m["count"] for m in months)
    total_days = sum(m["daysCount"] for m in months)
    best_score = max((m["bestScore"] for m in months), default=0)
    last_date = months[0]["lastDate"] if months else ""
    last_match = ""
    if months and months[0]["days"]:
        last_match = months[0]["days"][0].get("lastMatchedAt") or ""

    return {
        "ok": True,
        "generatedAt": _archive_stamp(),
        "minScore": _archive_int(settings.get("archiveMinScore"), 65),
        "auto": bool(settings.get("archiveAuto", True)),
        # 前端用它告诉用户「这份档案到底存哪儿了」：
        # upstash = 云端持久化；file = 本地文件；persisted=False = 临时存储，重启会丢。
        "storage": "upstash" if _KV_ENABLED else "file",
        "persisted": bool(store.get("persisted", DATA_WRITABLE)),
        "totals": {
            "months": len(months),
            "days": total_days,
            "records": total_records,
            "bestScore": best_score,
            "lastDate": last_date,
            "lastMatchedAt": last_match,
        },
        "months": months,
    }


def api_archive_update(payload: dict) -> dict:
    """档案维护：保存指定扫描 / 删除单条 / 删除整日 / 清空。"""
    payload = payload or {}
    action = str(payload.get("action") or "save").strip().lower()

    if action == "save":
        scan = payload.get("scan")
        if not isinstance(scan, dict) or not isinstance(scan.get("items"), list):
            return {"ok": False, "error": "缺少扫描结果，无法存档"}
        info = _archive_scan(scan, force=True)
        return {**info, **api_archive()}

    if action not in ("delete", "clear"):
        return {"ok": False, "error": "未知操作：" + action}

    with _STORE_LOCK:
        store = load_store()
        archive = store.get("dragonArchive")
        if not isinstance(archive, dict):
            archive = {}

        if action == "clear":
            save_store({"dragonArchive": {}})
            return api_archive()

        date = str(payload.get("date") or "")[:10]
        code = str(payload.get("code") or "").strip()
        month = date[:7]
        month_map = archive.get(month)
        deleted = False
        if isinstance(month_map, dict) and date in month_map:
            day = month_map.get(date)
            if isinstance(day, dict):
                items = day.get("items")
                if isinstance(items, list):
                    items = {str(it.get("code")): it for it in items if isinstance(it, dict)}
                if not isinstance(items, dict):
                    items = {}
                if code:
                    if code in items:
                        items.pop(code, None)
                        deleted = True
                    if items:
                        day["items"] = items
                        day["count"] = len(items)
                        day["bestScore"] = max(_archive_int(v.get("score"))
                                               for v in items.values())
                        day["updatedAt"] = _archive_stamp()
                        month_map[date] = day
                    else:
                        month_map.pop(date, None)
                        deleted = True
                else:
                    month_map.pop(date, None)
                    deleted = True
            else:
                month_map.pop(date, None)
                deleted = True
            if month_map:
                archive[month] = month_map
            else:
                archive.pop(month, None)
            if deleted:
                save_store({"dragonArchive": archive})

    return api_archive()


# ----------------------------------------------------------------------------
# HTTP 服务
# ----------------------------------------------------------------------------

ROUTES = {
    # 极轻量的存活探针：守护进程 watchdog.py 每秒都在打它，所以不能碰任何外部接口
    "/api/ping": lambda q, b: {"ok": True, "service": "longhuitou",
                               "time": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               "pid": os.getpid()},
    "/api/overview": lambda q, b: api_overview(),
    "/api/hot": lambda q, b: api_hot_boards(int(_q1(q, "days") or 5)),
    "/api/limitup": lambda q, b: api_limitup(_q1(q, "date")),
    "/api/dragons": lambda q, b: api_dragons(int(_q1(q, "days") or 10)),
    "/api/scan": lambda q, b: api_scan(int(_q1(q, "limit") or 40), int(_q1(q, "days") or 10)),
    "/api/quote": lambda q, b: api_quote(
        [c for c in (_q1(q, "codes") or "").split(",") if c.strip()]),
    "/api/preview": lambda q, b: api_preview(_q1(q, "code") or ""),
    "/api/minute": lambda q, b: api_minute(_q1(q, "code") or ""),
    "/api/stock": lambda q, b: stock_view(_q1(q, "code") or "", load_store().get("settings", {})),
    "/api/evaluate": lambda q, b: api_evaluate(b or {}),
    "/api/notify": lambda q, b: (api_notify(b) if b is not None
                                 else {"ok": False, "error": "请用 POST 调用 /api/notify"}),
    "/api/store": lambda q, b: (save_store(b) if b else load_store()),
    "/api/archive": lambda q, b: (api_archive_update(b) if b is not None else api_archive()),
}


def _q1(query: dict, key: str):
    values = query.get(key) or []
    return values[0] if values else None


_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "LongHuitou/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # --- 跨域（默认关闭，见 CORS_ORIGIN 的说明）---
    def _cors(self):
        if CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):                               # noqa: N802
        """前端部署在别处时，浏览器发 POST(JSON) 前会先来一次预检。"""
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- 静态文件 ---
    def _serve_static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        if rel in ("", "/"):
            rel = "index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        handler = ROUTES.get(path)
        if handler is None:
            if path.startswith("/api/"):
                self._json({"ok": False, "error": "未知接口 " + path}, 404)
            else:
                try:
                    self._serve_static(path)
                except ConnectionError:
                    pass                                # 客户端已走，静默收场
            return
        try:
            self._json(handler(query, None))
        except ConnectionError:
            pass                                        # 客户端已走，静默收场
        except Exception as exc:                        # noqa: BLE001
            _note_error(exc)
            try:
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            except ConnectionError:
                pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        handler = ROUTES.get(parsed.path)
        if handler is None:
            self._json({"ok": False, "error": "未知接口 " + parsed.path}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        try:
            self._json(handler(urllib.parse.parse_qs(parsed.query), payload))
        except ConnectionError:
            pass                                        # 客户端已走，静默收场
        except Exception as exc:                        # noqa: BLE001
            _note_error(exc)
            try:
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            except ConnectionError:
                pass


def _notify_worker():
    """常驻线程：到点自动扫描并推送。

    只在「有可用通道 + 今天确实是交易日 + 当前分钟命中配置时刻」时才动作。
    market_date() 会走一次网络，所以只在命中时刻才调用，避免空转。
    """
    fired = {}
    while True:
        try:
            settings = load_store().get("settings", {})
            if resolve_notify(settings):
                now = _dt.datetime.now()
                hm = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")
                slots = [s.strip() for s in str(settings.get("notifyTimes") or "").split(",")
                         if s.strip()]
                if hm in slots and fired.get(hm) != today and now.weekday() < 5:
                    if market_date() == today:      # 双重校验：今天确实是交易日
                        fired[hm] = today
                        res = api_notify({"scan": True})
                        print("[微信推送] %s → %s  %s"
                              % (hm, "成功" if res.get("ok") else "失败", res.get("detail", "")))
        except Exception as exc:                        # noqa: BLE001
            _note_error(exc)
        time.sleep(20.0)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:                                   # noqa: BLE001
        return "127.0.0.1"


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """客户端断开连接时不要往控制台/日志里打整段 traceback。

    socketserver 默认在 handle_error() 里把异常打印到 stderr。浏览器刷新、
    切标签、关窗口都会触发 ConnectionAbortedError，属于正常现象。
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):    # noqa: D102
        exc = sys.exc_info()[1]
        if _client_gone(exc):
            return
        super().handle_error(request, client_address)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # type: ignore[attr-defined]
    except Exception:                                   # noqa: BLE001
        pass
    for _d in (DATA_DIR, WEB_DIR):
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            pass                                        # 只读文件系统：由 save_store 降级处理
    if not os.path.exists(STORE_FILE):
        save_store({})

    threading.Thread(target=_notify_worker, daemon=True, name="notify").start()

    _st = load_store().get("settings", {})
    _on = [(_push.CHANNELS.get(ch, ch)) for ch, _ in resolve_notify(_st)]

    server = QuietThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("=" * 64)
    print("  龙回头 · 五层立体短线交易系统")
    print("  本机访问 : http://%s:%d" % (HOST, PORT))
    print("  局域网   : http://%s:%d" % (_lan_ip(), PORT))
    print("  数据目录 : %s" % DATA_DIR)
    print("  微信推送 : %s" % (
        " + ".join(_on) + "　定时 " + str(_st.get("notifyTimes") or "") if _on else "（未开启）"))
    print("  按 Ctrl+C 停止服务")
    print("=" * 64)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
