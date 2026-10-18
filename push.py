#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""微信推送通道 —— Server酱 / PushPlus / 企业微信群机器人。

设计约束（与整个项目一致）：
  * 纯标准库，不引入任何第三方依赖；
  * 只做「系统 → 你」的单向推送。不登录微信客户端、不接收消息、
    不使用 itchat / wechaty 之类的模拟客户端方案（那类做法违反微信使用
    协议且有封号风险）；
  * 所有失败都收敛成返回值，不向上抛异常，避免拖垮定时任务或 HTTP 接口。

对外只有一个入口：``push(channel, key, title, markdown)``。

关于「企业微信 + 个人微信」的一个重要坑：企业微信群机器人发 ``markdown``
时，**微信插件同步到个人微信会显示成「[链接] 暂不支持此消息类型」**——
微信客户端不认识 markdown 这种消息类型。所以想真正推到个人微信，
企业微信这条必须改发 ``text``（纯文本）。纯文本上限只有 2048 字节，
比 markdown 的 4096 小一半，因此长消息会自动分片连发。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["CHANNELS", "WECOM_FORMATS", "md_to_text", "push", "push_many",
           "serverchan_url", "split_bytes", "truncate"]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TIMEOUT = 12.0

#: 通道标识 → 中文名（前端下拉框与设置项共用）
CHANNELS = {
    "off": "关闭",
    "serverchan": "Server酱",
    "pushplus": "PushPlus",
    "wecom": "企业微信群机器人",
}

#: 企业微信群机器人的正文格式。
#:   text     —— 纯文本，企业微信和个人微信（微信插件）都能正常显示，上限 2048 字节
#:   markdown —— 企业微信里排版好看，但同步到个人微信会变成「暂不支持此消息类型」
WECOM_FORMATS = {
    "text": "纯文本（个人微信也能读）",
    "markdown": "Markdown（仅企业微信内好看）",
}

#: 正文长度上限（字节，按 UTF-8 粗略折算）。企业微信 markdown 上限 4096 字节。
_MAX_BYTES = {
    "wecom": 3800,
    "serverchan": 30000,
    "pushplus": 30000,
}

#: 企业微信 text 上限 2048 字节，留点余量给分片标记
_WECOM_TEXT_BYTES = 1900

#: 单条消息最多拆几片，避免把手机刷屏（企业微信 20 条/分钟，这里远低于上限）
_WECOM_MAX_CHUNKS = 6


def truncate(text: str, max_bytes: int, note: str = "\n\n…（内容过长已截断）") -> str:
    """按 UTF-8 字节数截断，保证不会把多字节字符切碎。"""
    raw = (text or "").encode("utf-8")
    if len(raw) <= max_bytes:
        return text or ""
    room = max(0, max_bytes - len(note.encode("utf-8")))
    cut = raw[:room].decode("utf-8", errors="ignore") if room else ""
    return cut + (note if room else "")


def split_bytes(text: str, limit: int, max_chunks: int = 0) -> list:
    """按**行**切分，让每片的 UTF-8 字节数不超过 ``limit``。

    单行本身就超限时（真实场景里几乎不会发生）会退化成硬截断，
    保证一定能切得动、不死循环。

    ``max_chunks > 0`` 时最多只产出这么多片，多出来的内容**截断**进最后一片
    （带省略标记）——绝不能把它们合并成一片，那会直接超出接口上限被拒。
    """
    lines = (text or "").split("\n")
    chunks, cur = [], ""
    for line in lines:
        cand = line if not cur else cur + "\n" + line
        if len(cand.encode("utf-8")) <= limit:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(line.encode("utf-8")) <= limit:
            cur = line
        else:                                           # 单行超长：硬切
            chunks.append(line.encode("utf-8")[:limit].decode("utf-8", errors="ignore"))
    if cur:
        chunks.append(cur)
    if max_chunks and len(chunks) > max_chunks:
        head = chunks[:max_chunks - 1]
        tail = "\n".join(chunks[max_chunks - 1:])
        head.append(truncate(tail, limit, "\n\n…（剩余内容过长已省略）"))
        chunks = head
    return chunks or [""]


_RE_MD_CODE = re.compile(r"`([^`]+)`")
_RE_MD_BOLD = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}")
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_RE_MD_HEAD = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.M)
_RE_MD_RULE = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.M)
_RE_MD_QUOTE = re.compile(r"^[ \t]*>+[ \t]?", re.M)


def md_to_text(markdown: str) -> str:
    """把 markdown 拍成纯文本。

    只处理我们自己生成消息时用到的那几种语法（标题、加粗、行内代码、
    斜体、引用、链接、分隔线），不追求通用 markdown 解析器。
    """
    text = (markdown or "").replace("\r\n", "\n")
    text = _RE_MD_LINK.sub(lambda m: ("%s %s" % (m.group(1), m.group(2))).strip(), text)
    text = _RE_MD_HEAD.sub("", text)                    # 去掉行首的 #
    text = _RE_MD_BOLD.sub(r"\1", text)                 # 去掉 ** * 强调
    text = _RE_MD_CODE.sub(r"\1", text)                 # 去掉反引号
    text = _RE_MD_QUOTE.sub("", text)                   # 去掉行首引用符
    text = _RE_MD_RULE.sub("\n──────────────────\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _post(url: str, data: dict, as_json: bool) -> str:
    if as_json:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ctype = "application/json; charset=utf-8"
    else:
        body = urllib.parse.urlencode(data).encode("utf-8")
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": _UA,
        "Content-Type": ctype,
        "Accept": "*/*",
        "Connection": "close",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def serverchan_url(key: str) -> str:
    """把 SendKey（或直接粘贴的完整地址）归一成可 POST 的 send 地址。

    兼容三种写法：
      * 完整地址                https://sctapi.ftqq.com/SCTxxxx.send
      * Server酱 Turbo  SendKey  SCTxxxxxxxx
      * Server酱³      SendKey  sctp12345txxxxxxxx
                                → https://12345.push.ft07.com/send/<key>.send
    """
    key = (key or "").strip()
    if key.startswith("http://") or key.startswith("https://"):
        return key
    m = re.match(r"^sctp(\d+)t", key, re.I)
    if m:
        return "https://%s.push.ft07.com/send/%s.send" % (m.group(1), key)
    return "https://sctapi.ftqq.com/%s.send" % key


def pushplus_target(key: str) -> tuple:
    """返回 (地址, token)。允许直接粘贴带 token 的完整地址。"""
    key = (key or "").strip()
    if key.startswith("http://") or key.startswith("https://"):
        parsed = urllib.parse.urlparse(key)
        token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        if not token:
            token = parsed.path.rstrip("/").split("/")[-1]
        base = "%s://%s%s" % (parsed.scheme, parsed.netloc, parsed.path)
        return base, token
    return "https://www.pushplus.plus/send", key


def _send_serverchan(key: str, title: str, markdown: str, fmt: str = None) -> tuple:
    raw = _post(serverchan_url(key), {"title": title, "desp": markdown}, as_json=False)
    try:
        obj = json.loads(raw)
    except ValueError:
        return False, "返回非 JSON：" + raw[:180]
    if obj.get("code") == 0:
        return True, "已提交（Server酱返回 code=0）"
    return False, str(obj.get("message") or obj.get("msg") or raw[:180])


def _send_pushplus(key: str, title: str, markdown: str, fmt: str = None) -> tuple:
    url, token = pushplus_target(key)
    raw = _post(url, {"token": token, "title": title,
                      "content": markdown, "template": "markdown"}, as_json=True)
    try:
        obj = json.loads(raw)
    except ValueError:
        return False, "返回非 JSON：" + raw[:180]
    if str(obj.get("code")) in ("200", "0"):
        return True, "已提交（PushPlus 返回 code=%s）" % obj.get("code")
    return False, str(obj.get("msg") or raw[:180])


def _wecom_url(key: str) -> str:
    return key if key.startswith("http") else \
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + key


def _wecom_post(url: str, payload: dict) -> tuple:
    """POST 一次并解析企业微信的统一返回结构。"""
    raw = _post(url, payload, as_json=True)
    try:
        obj = json.loads(raw)
    except ValueError:
        return False, "返回非 JSON：" + raw[:180]
    if obj.get("errcode") == 0:
        return True, "errcode=0"
    return False, "errcode=%s %s" % (obj.get("errcode"), obj.get("errmsg") or "")


def _send_wecom_markdown(key: str, title: str, markdown: str, fmt: str = None) -> tuple:
    content = "## %s\n\n%s" % (title, markdown) if title else markdown
    ok, detail = _wecom_post(_wecom_url(key),
                             {"msgtype": "markdown", "markdown": {"content": content}})
    return (True, "已提交（企业微信 %s）" % detail) if ok else (False, detail)


def _send_wecom_text(key: str, title: str, markdown: str, fmt: str = None) -> tuple:
    """纯文本模式：微信插件（个人微信）唯一能正常显示的类型。

    text 上限 2048 字节，超长就按行拆成多片连发——宁可多收几条，
    也不静默截断把后面的标的丢掉。
    """
    url = _wecom_url(key)
    plain = md_to_text(markdown)
    if title:
        plain = "%s\n%s" % (title, plain)

    chunks = split_bytes(plain, _WECOM_TEXT_BYTES, _WECOM_MAX_CHUNKS)
    total = len(chunks)
    sent = 0
    for i, chunk in enumerate(chunks, 1):
        body = "(%d/%d)\n%s" % (i, total, chunk) if total > 1 else chunk
        ok, detail = _wecom_post(url, {"msgtype": "text", "text": {"content": body}})
        if not ok:
            return (sent > 0), ("第 %d/%d 片失败：%s" % (i, total, detail))
        sent += 1
    return True, "已提交（企业微信 errcode=0，纯文本 %d 片）" % total


def _send_wecom(key: str, title: str, markdown: str, fmt: str = None) -> tuple:
    if (fmt or "text").strip().lower() == "markdown":
        return _send_wecom_markdown(key, title, markdown, fmt)
    return _send_wecom_text(key, title, markdown, fmt)


_SENDERS = {
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
    "wecom": _send_wecom,
}


def push(channel: str, key: str, title: str, markdown: str, fmt: str = None) -> dict:
    """发送一条消息。

    ``fmt`` 只对企业微信有意义（``text`` / ``markdown``），其余通道忽略。
    返回 ``{"ok": bool, "channel": str, "detail": str}``，永不抛异常。
    """
    channel = (channel or "off").strip().lower()
    key = (key or "").strip()
    if channel in ("", "off", "none", "close"):
        return {"ok": False, "channel": channel or "off", "detail": "未开启推送通道，已跳过"}
    if not key:
        return {"ok": False, "channel": channel, "detail": "未填写 SendKey / token"}
    sender = _SENDERS.get(channel)
    if sender is None:
        return {"ok": False, "channel": channel, "detail": "未知通道：" + channel}

    title = (title or "龙回头提醒").strip().replace("\n", " ")[:100] or "龙回头提醒"
    # 企业微信纯文本自己分片，不在这里截断
    if not (channel == "wecom" and (fmt or "text").strip().lower() != "markdown"):
        markdown = truncate(markdown or "", _MAX_BYTES.get(channel, 30000))

    try:
        ok, detail = sender(key, title, markdown, fmt)
    except urllib.error.HTTPError as exc:              # noqa: PERF203
        body = ""
        try:
            body = exc.read().decode("utf-8", "ignore")[:180]
        except Exception:                              # noqa: BLE001
            pass
        return {"ok": False, "channel": channel, "detail": "HTTP %s %s" % (exc.code, body)}
    except Exception as exc:                           # noqa: BLE001
        return {"ok": False, "channel": channel,
                "detail": "%s: %s" % (type(exc).__name__, exc)}

    return {"ok": bool(ok), "channel": channel, "detail": detail}


def push_many(pairs, title: str, markdown: str, formats: dict = None) -> dict:
    """并行发到多个通道。``pairs`` 是 ``[(通道, 密钥), ...]``。

    ``formats`` 是 ``{通道: 格式}``，只影响企业微信。任意一个通道成功即视为
    整体成功——多通道的意义就是冗余，某个通道挂了不应该影响另一个。
    所有结果都放进 ``results`` 供前端展示。
    """
    formats = formats or {}
    results = [push(ch, key, title, markdown, formats.get(ch)) for ch, key in (pairs or [])]
    if not results:
        return {"ok": False, "channel": "off", "results": [],
                "detail": "未开启推送通道，已跳过"}
    detail = "；".join("%s：%s" % (r["channel"], r["detail"]) for r in results)
    return {
        "ok": any(r["ok"] for r in results),
        "channel": ",".join(r["channel"] for r in results),
        "results": results,
        "detail": detail,
    }
