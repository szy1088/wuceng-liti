#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""龙回头服务守护进程 —— 保证 http://127.0.0.1:8766 随时可用。

采用「主守护 + 保镖」双进程互保，两个角色都活不长就互为备份：

::

    ┌──────────────┐  探活 /api/ping    ┌──────────────┐
    │  主守护       │ ─────────────────► │  server.py   │
    │  (primary)   │  挂了就重新拉起      │  127.0.0.1   │
    └──────┬───────┘                    └──────────────┘
           │ 互保：谁死了另一个负责拉起来
    ┌──────┴───────┐
    │  保镖         │  只做一件事：主守护还在吗？不在就拉起来。
    │  (guard)     │
    └──────────────┘

* 主守护：每 ``INTERVAL`` 秒向 ``/api/ping`` 探活；连续 ``FAIL_THRESHOLD`` 次失败
  → 清理占着端口的僵死进程 → 重新拉起 ``server.py``；顺带看住保镖。
* 保镖：每 2 秒确认主守护还活着，不在就立刻拉起一个新的。

再叠加两层不依赖管理员的「开机自启」：

1. 「启动」文件夹快捷方式（由 ``task.ps1 -Action watchdog-install`` 创建）
2. ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` 注册表项

注册表项由主守护每 5 分钟自检一次，被谁删了都会自动补写回来。

设计取舍：

* 纯标准库（不依赖 psutil / pywin32），和项目其余部分保持一致；
* 探活必须有「连续失败」阈值，避免一次网络抖动就误杀健康服务；
* 重启有冷却时间，避免配置写错时疯狂重启把日志刷爆；
* 循环整体包在 ``try`` 里，任何意外异常都不允许让守护自己退出。

命令行：

    python watchdog.py                    # 前台跑主守护（调试用，Ctrl+C 退出）
    python watchdog.py --status           # 只探活一次，打印结果（退出码 0/1）
    python watchdog.py --ensure-autostart # 只写开机自启项
    python watchdog.py --remove-autostart # 只删开机自启项
    python watchdog.py --stopped          # 打印各角色 PID（供脚本判断）

想临时停掉守护做维护：``powershell -File task.ps1 -Action watchdog-pause``
（等价于在 ``data`` 目录建一个空文件 ``watchdog.off``）。
待机期间两个角色都只睡觉、不拉起任何东西；删掉文件立刻恢复。
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")

LOG_FILE = os.path.join(LOG_DIR, "watchdog.log")
SERVER_LOG = os.path.join(LOG_DIR, "server.log")
PAUSE_FILE = os.path.join(DATA_DIR, "watchdog.off")
SERVER_SCRIPT = os.path.join(BASE_DIR, "server.py")
SELF_SCRIPT = os.path.abspath(__file__)

PORT = int(os.environ.get("LHT_PORT", "8766"))
INTERVAL = float(os.environ.get("LHT_WATCH_INTERVAL", "5"))        # 主守护探活间隔（秒）
GUARD_INTERVAL = float(os.environ.get("LHT_GUARD_INTERVAL", "2"))  # 保镖巡检间隔（秒）
PROBE_TIMEOUT = float(os.environ.get("LHT_PROBE_TIMEOUT", "5"))    # 单次探活超时
FAIL_THRESHOLD = int(os.environ.get("LHT_FAIL_THRESHOLD", "2"))    # 连续失败几次才动手
COOLDOWN = float(os.environ.get("LHT_RESTART_COOLDOWN", "10"))     # 两次重启的最小间隔
SELF_HEAL_EVERY = 300.0                                            # 自启项自检间隔
LOG_MAX_BYTES = 1_000_000

ROLE_PRIMARY = "primary"
ROLE_GUARD = "guard"
ROLE_LABEL = {ROLE_PRIMARY: "主守护", ROLE_GUARD: "保镖"}

PID_FILE = {
    ROLE_PRIMARY: os.path.join(DATA_DIR, "watchdog.pid"),
    ROLE_GUARD: os.path.join(DATA_DIR, "watchdog.guard.pid"),
}
# 兼容旧路径（早期版本只有主守护用这个名字）
LEGACY_PID_FILE = os.path.join(DATA_DIR, "watchdog.pid")

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "LongHuitouWatchdog"

# ---------------------------------------------------------------------------
# Windows：绝不弹出控制台黑窗
# ---------------------------------------------------------------------------
#
# 这个坑很隐蔽：watchdog.py 是由 pythonw.exe 启动的，**它自己没有控制台**。
# 于是每当它调用 tasklist / netstat / taskkill 这类「控制台子系统」程序时，
# Windows 都会给子进程**新建一个控制台窗口** —— 屏幕上一闪一闪的黑窗就是这么来的。
#
# 两处修法：
#   1. 判断进程是否存活改用 Win32 API（OpenProcess + WaitForSingleObject），
#      连子进程都不用起 —— 既没有窗口，也比解析 tasklist 文本可靠得多
#      （之前就因为解析偶发失败，误判活着的保镖已死，白拉起好几个进程）；
#   2. 剩下确实要起子进程的地方，统统加 CREATE_NO_WINDOW。

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0        # CREATE_NO_WINDOW
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5

_kernel32 = None
if os.name == "nt":
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _kernel32.OpenProcess.restype = wintypes.HANDLE
        _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        _kernel32.WaitForSingleObject.restype = wintypes.DWORD
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
    except Exception:                                   # noqa: BLE001
        _kernel32 = None


def _run_quiet(args, timeout: float = 20.0):
    """跑一个外部命令，并且**绝不弹出控制台窗口**。"""
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="ignore",
                              creationflags=_NO_WINDOW)
    except Exception:                                   # noqa: BLE001
        return None


def _pid_alive(pid: int) -> bool:
    """进程是否还活着。纯 Win32 API，不起子进程、不弹窗。

    注意：Windows 上**绝不能**用 ``os.kill(pid, 0)`` 判断存活 —— 那会真的把进程杀掉。
    """
    if not pid:
        return False
    if _kernel32 is None:
        return False
    handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
    if not handle:
        # 打不开句柄有两种情况，不能一律当成「已死」：
        #   ERROR_ACCESS_DENIED(5)      → 进程存在，只是没权限打开（受保护进程）
        #   ERROR_INVALID_PARAMETER(87) → 这个 PID 根本不存在
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        # 信号量已触发(WAIT_OBJECT_0) = 进程已退出；超时(WAIT_TIMEOUT) = 还活着
        return _kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str, role: str = "") -> None:
    """写日志文件（超过 1MB 自动轮转），有控制台时同时打到屏幕。"""
    tag = ROLE_LABEL.get(role, role)
    line = "[%s]%s %s" % (_now(), ("[%s]" % tag) if tag else "", msg)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:                                   # noqa: BLE001
        pass
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            print(line, flush=True)
    except Exception:                                   # noqa: BLE001
        pass


def _python_exe() -> str:
    """优先用同目录下的 pythonw.exe —— 后台运行不弹黑窗口。"""
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        cand = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.isfile(cand):
            return cand
    return exe or "python"


def _read_pid(path: str) -> int:
    try:
        # 用 utf-8-sig 而不是 utf-8：万一这个文件被 PowerShell / 记事本带 BOM 保存过，
        # 用 "utf-8" 读会在 int() 处抛异常，于是守护进程误判"该角色没在跑"，
        # 反复拉起重复进程。凡是用户可能碰过的文本文件，一律用 utf-8-sig 更稳
        # （utf-8-sig 读没有 BOM 的文件也完全正常）。
        with open(path, encoding="utf-8-sig") as fh:
            return int((fh.read() or "0").strip() or 0)
    except Exception:                                   # noqa: BLE001
        return 0


def _write_pid(path: str, pid: int) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(pid))
    except Exception:                                   # noqa: BLE001
        pass


def _role_pid(role: str) -> int:
    pid = _read_pid(PID_FILE[role])
    return pid if _pid_alive(pid) else 0


def _listening_pids(port: int) -> set:
    """解析 netstat，返回正在 LISTEN 该端口的 PID 集合。"""
    pids = set()
    out = _run_quiet(["netstat", "-ano", "-p", "TCP"], 20)
    if out is None:
        return pids
    suffix = ":%d" % port
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" \
                and parts[3].upper() == "LISTENING" and parts[1].endswith(suffix):
            try:
                pids.add(int(parts[4]))
            except ValueError:
                pass
    return pids


def _spawn(args: list) -> int:
    """后台拉起一个 python 进程（不弹窗、不属于当前进程树）。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) \
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [_python_exe()] + args,
        cwd=BASE_DIR, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags, close_fds=True)
    return proc.pid


def _spawn_role(role: str) -> int:
    return _spawn([SELF_SCRIPT, "--role", role])


def _spawn_server() -> int:
    """拉起 server.py，输出重定向到 logs/server.log。返回新进程 PID。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    fh = open(SERVER_LOG, "a", encoding="utf-8", errors="replace")
    fh.write("\n%s\n[%s] 守护拉起 server.py\n" % ("-" * 60, _now()))
    fh.flush()
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) \
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [_python_exe(), SERVER_SCRIPT], cwd=BASE_DIR, env=env,
        stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
        creationflags=flags, close_fds=True)
    return proc.pid


def _paused() -> bool:
    return os.path.exists(PAUSE_FILE)


# ---------------------------------------------------------------------------
# 探活 / 重启服务
# ---------------------------------------------------------------------------

def probe() -> tuple:
    """返回 ``(是否健康, 说明)``。必须有 service 字段，避免误认别的程序。"""
    url = "http://127.0.0.1:%d/api/ping" % PORT
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LHT-Watchdog/1.0"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            body = resp.read(8192).decode("utf-8", errors="ignore")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return False, "HTTP %s" % exc.code
    except Exception as exc:                            # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)
    if status != 200:
        return False, "HTTP %s" % status
    try:
        obj = json.loads(body)
    except ValueError:
        return False, "返回非 JSON：" + body[:80]
    if obj.get("service") != "longhuitou":
        return False, "端口 %d 被别的程序占用：%s" % (PORT, body[:80])
    return True, "PID %s" % obj.get("pid")


def restart_server(reason: str, role: str) -> None:
    _log("准备重启服务（原因：%s）" % reason, role)
    for pid in _listening_pids(PORT):
        if pid == os.getpid():
            continue
        _log("清理占着 %d 端口的旧进程 PID %d" % (PORT, pid), role)
        _run_quiet(["taskkill", "/PID", str(pid), "/F", "/T"], 20)
    time.sleep(1.0)
    try:
        _log("已拉起 server.py，PID=%d" % _spawn_server(), role)
    except Exception as exc:                            # noqa: BLE001
        _log("拉起失败：%s: %s" % (type(exc).__name__, exc), role)


# ---------------------------------------------------------------------------
# 角色抢占 / 开机自启
# ---------------------------------------------------------------------------

def claim_role(role: str) -> tuple:
    """抢占角色，保证同一时刻每个角色只有一个进程。

    先随机错开一点时间再读 PID 文件，两个实例同时启动时不会双活。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    path = PID_FILE[role]
    me = os.getpid()
    time.sleep(random.uniform(0.0, 0.8))                # 错峰，降低抢跑概率
    owner = _read_pid(path)
    if owner and owner != me and _pid_alive(owner):
        return False, owner
    _write_pid(path, me)
    time.sleep(0.25)
    if _read_pid(path) != me:                           # 被别人抢先写了
        return False, _read_pid(path)
    return True, me


def _autostart_cmd() -> str:
    return '"%s" "%s"' % (_python_exe(), SELF_SCRIPT)


def ensure_autostart() -> tuple:
    """保证 HKCU 的 Run 项存在。这是免管理员的自启方式，被删了会自动补写。"""
    if os.name != "nt":
        return False, "非 Windows 平台"
    import winreg                                       # noqa: PLC0415
    cmd = _autostart_cmd()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                cur, _ = winreg.QueryValueEx(key, _RUN_NAME)
            except FileNotFoundError:
                cur = None
            if cur == cmd:
                return True, "已存在"
            winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, cmd)
            return True, ("已补写" if cur else "已写入")
    except Exception as exc:                            # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def remove_autostart() -> tuple:
    if os.name != "nt":
        return False, "非 Windows 平台"
    import winreg                                       # noqa: PLC0415
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                winreg.DeleteValue(key, _RUN_NAME)
                return True, "已删除"
            except FileNotFoundError:
                return True, "本来就没有"
    except Exception as exc:                            # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# 云端实例保活（可选，默认关闭）
# ---------------------------------------------------------------------------
# 免费层实例闲置 15 分钟就休眠，你下次打开要等约 1 分钟冷启动。
# 主守护会顺手在交易时段里定时戳一下线上地址，让它保持"热"的状态，
# 这样你随手打开就是秒开。
#
# 配置放 data/keepalive.json（data/ 已被 .gitignore 排除，不会上传），
# 格式参照仓库根目录的 keepalive.example.json。
# 文件不存在 / enabled 不是 true = 完全不启用，不影响任何其它功能。
#
# 两个关键设计：
#   1) 探测必须放子线程 —— 冷启动要等 60 秒，同步等会把本机服务的监控晾在一边，
#      而这 60 秒里恰恰是你最需要它看着的时候。
#   2) 只在本机跑 —— 守护进程永远不会部署到云端，所以不会出现"自己戳自己"
#      从而把免费额度 24 小时耗光的蠢事。

KEEPALIVE_FILE = os.path.join(DATA_DIR, "keepalive.json")
KEEPALIVE_STATE = os.path.join(DATA_DIR, "keepalive.state")   # 落盘状态，好让 status 命令读到
KEEPALIVE_MIN_INTERVAL = 60.0        # 免费层 15 分钟才睡，比这更密的间隔没有意义
KEEPALIVE_DEFAULT_TIMEOUT = 90.0     # 冷启动慢，超时给足
KEEPALIVE_DEFAULT_WINDOWS = [("09:00", "11:35"), ("12:45", "15:10")]

_ka_lock = threading.Lock()
_ka_busy = False                     # 上一个请求还没回来
_ka_last = 0.0                       # 上次发起时间
_ka_result = "尚未执行"               # 最近一次结果（仅本进程内有效）
_ka_prev_ok = None                   # None = 还没跑过；这样每次重启后的第一笔一定会记日志
_ka_cache = {"at": 0.0, "cfg": {}}


def _hhmm(text) -> str:
    """把 '9:05' / '09:05' 统一成 'HH:MM'；格式不对返回空串。"""
    raw = str(text or "").strip()
    if ":" not in raw:
        return ""
    hh, _, mm = raw.partition(":")
    try:
        return "%02d:%02d" % (int(hh), int(mm))
    except ValueError:
        return ""


def _keepalive_config() -> dict:
    """读保活配置，带 30 秒缓存（这样改完文件很快生效，又不会每 5 秒开一次文件）。"""
    now = time.time()
    if now - _ka_cache["at"] < 30.0:
        return _ka_cache["cfg"]

    cfg = {}
    try:
        with open(KEEPALIVE_FILE, "r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict) and raw.get("enabled"):
            url = str(raw.get("url") or "").strip()
            if url.startswith("http"):
                windows = []
                for item in (raw.get("windows") or []):
                    head, _, tail = str(item).partition("-")
                    head, tail = _hhmm(head), _hhmm(tail)
                    if head and tail:
                        windows.append((head, tail))
                if not windows:
                    windows = list(KEEPALIVE_DEFAULT_WINDOWS)
                try:
                    interval = float(raw.get("interval_seconds", 600))
                except (TypeError, ValueError):
                    interval = 600.0
                try:
                    timeout = float(raw.get("timeout_seconds", KEEPALIVE_DEFAULT_TIMEOUT))
                except (TypeError, ValueError):
                    timeout = KEEPALIVE_DEFAULT_TIMEOUT
                cfg = {
                    "url": url,
                    "interval": max(KEEPALIVE_MIN_INTERVAL, interval),
                    "timeout": max(5.0, timeout),
                    "windows": windows,
                    "weekdays_only": bool(raw.get("weekdays_only", True)),
                }
    except Exception:                                   # noqa: BLE001
        cfg = {}                                        # 文件不在 / 坏了 = 不启用

    _ka_cache["at"] = now
    _ka_cache["cfg"] = cfg
    return cfg


def _keepalive_ping(cfg: dict, role: str) -> None:
    """子线程里真正去戳远端。纯 urllib，不起子进程，不会闪黑窗。"""
    global _ka_busy, _ka_result, _ka_prev_ok
    url = cfg["url"].rstrip("/") + "/api/ping"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LHT-Keepalive/1.0"})
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            body = resp.read(4096).decode("utf-8", errors="ignore")
            status = getattr(resp, "status", 200)
        ok = (status == 200) and ("longhuitou" in body)
        detail = "HTTP %s" % status
    except Exception as exc:                            # noqa: BLE001
        ok = False
        detail = "%s: %s" % (type(exc).__name__, str(exc)[:60])

    with _ka_lock:
        _ka_busy = False
        _ka_result = ("唤醒成功 " if ok else "失败 ") + detail
        flipped = (ok != _ka_prev_ok)
        _ka_prev_ok = ok

    # 落盘，好让另起进程执行的 `task.ps1 status` 也能看到最近一次的情况
    try:
        with open(KEEPALIVE_STATE, "w", encoding="utf-8") as fh:
            json.dump({"at": time.time(), "ok": ok, "detail": detail, "url": cfg["url"]},
                      fh, ensure_ascii=False)
    except Exception:                                   # noqa: BLE001
        pass

    # 成功且状态没变就不记日志 —— 一个交易日 30 多次成功记录只会把日志淹掉。
    # 只在"首次执行""从失败恢复""开始失败"时记一笔，日志才读得下去。
    if ok:
        if flipped:
            _log("云端实例保活正常（%s）" % detail, role)
    else:
        _log("云端保活失败（%s）" % detail, role)


def keepalive_tick(role: str) -> None:
    """主守护每轮调一次：该戳就起个子线程去戳，绝不阻塞主循环。"""
    global _ka_busy, _ka_last
    cfg = _keepalive_config()
    if not cfg:
        return

    now = _dt.datetime.now()
    if cfg["weekdays_only"] and now.weekday() >= 5:
        return                                          # 周末休市，不用叫醒
    hm = now.strftime("%H:%M")
    if not any(start <= hm <= end for start, end in cfg["windows"]):
        return                                          # 不在交易时段，省着点用免费额度

    with _ka_lock:
        if _ka_busy:
            return                                      # 上一次还没回来，别叠着发
        if (time.time() - _ka_last) < cfg["interval"]:
            return                                      # 还没到下次该戳的时间
        _ka_busy = True
        _ka_last = time.time()

    threading.Thread(target=_keepalive_ping, args=(cfg, role), daemon=True).start()


def _keepalive_last_note() -> str:
    """读落盘状态，给 status 命令用。

    `task.ps1 status` 是另起一个进程跑 `watchdog.py --status`，
    读不到守护进程内存里的 _ka_result，所以必须靠这个文件。
    """
    try:
        with open(KEEPALIVE_STATE, "r", encoding="utf-8-sig") as fh:
            state = json.load(fh)
        when = time.strftime("%m-%d %H:%M", time.localtime(float(state.get("at", 0))))
        return "%s %s（%s）" % ("成功" if state.get("ok") else "失败",
                               state.get("detail", "?"), when)
    except Exception:                                   # noqa: BLE001
        return "还没执行过"


# ---------------------------------------------------------------------------
# 主循环：主守护
# ---------------------------------------------------------------------------

def run_primary(no_guard: bool = False) -> int:
    role = ROLE_PRIMARY
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    got, owner = claim_role(role)
    if not got:
        _log("已有主守护在运行（PID %d），本次退出。" % owner, role)
        return 0

    _log("主守护启动：PID=%d 目标=http://127.0.0.1:%d 间隔=%.0fs 阈值=%d 冷却=%.0fs"
         % (os.getpid(), PORT, INTERVAL, FAIL_THRESHOLD, COOLDOWN), role)
    ok, msg = ensure_autostart()
    _log("开机自启项：%s %s" % ("OK" if ok else "失败", msg), role)

    fails = 0
    paused = False
    last_spawn = 0.0
    last_heal = time.time()

    while True:
        try:
            # ---- 中途接管旧版本残留的 PID 文件 ----
            if _read_pid(LEGACY_PID_FILE) not in (0, os.getpid()):
                _write_pid(LEGACY_PID_FILE, os.getpid())

            # ---- 待机开关 ----
            if _paused():
                if not paused:
                    _log("检测到 %s，进入待机（不再拉起服务）。删掉该文件即恢复。"
                         % os.path.basename(PAUSE_FILE), role)
                    paused = True
                time.sleep(INTERVAL)
                continue
            if paused:
                _log("待机解除，恢复守护。", role)
                paused = False

            # ---- 看住保镖 ----
            if not no_guard:
                guard_pid = _role_pid(ROLE_GUARD)
                if not guard_pid:
                    try:
                        _log("保镖不在，拉起一个（PID=%d）" % _spawn_role(ROLE_GUARD), role)
                    except Exception as exc:            # noqa: BLE001
                        _log("拉起保镖失败：%s" % exc, role)

            # ---- 看住网站服务 ----
            alive, detail = probe()
            if alive:
                if fails:
                    _log("服务已恢复（%s）" % detail, role)
                fails = 0
            else:
                fails += 1
                _log("探活失败 %d/%d：%s" % (fails, FAIL_THRESHOLD, detail), role)
                if fails >= FAIL_THRESHOLD:
                    idle = time.time() - last_spawn
                    if idle < COOLDOWN:
                        _log("重启冷却中（还剩 %.0fs）" % (COOLDOWN - idle), role)
                    else:
                        restart_server(detail, role)
                        last_spawn = time.time()
                    fails = 0

            # ---- 自启项自检 ----
            if time.time() - last_heal >= SELF_HEAL_EVERY:
                last_heal = time.time()
                hok, hmsg = ensure_autostart()
                if not hok:
                    _log("自启项自检失败：%s" % hmsg, role)

            # ---- 顺手把云端实例叫醒（可选，见上面"云端实例保活"一节）----
            keepalive_tick(role)

        except KeyboardInterrupt:
            _log("收到 Ctrl+C，主守护退出。", role)
            return 0
        except Exception as exc:                        # noqa: BLE001
            _log("主循环异常（已忽略，继续运行）：%s: %s"
                 % (type(exc).__name__, exc), role)
        time.sleep(INTERVAL)


# ---------------------------------------------------------------------------
# 主循环：保镖
# ---------------------------------------------------------------------------

def run_guard() -> int:
    role = ROLE_GUARD
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    got, owner = claim_role(role)
    if not got:
        _log("已有保镖在运行（PID %d），本次退出。" % owner, role)
        return 0

    _log("保镖启动：PID=%d 巡检间隔=%.0fs" % (os.getpid(), GUARD_INTERVAL), role)

    while True:
        try:
            if _paused():
                time.sleep(GUARD_INTERVAL)
                continue

            primary_pid = _role_pid(ROLE_PRIMARY)
            if primary_pid:
                # 主守护健在 —— 顺带确认端口上真的有人，没有就叫它动手
                pass
            else:
                _log("主守护不在了，立刻拉起一个新的。", role)
                try:
                    _log("已拉起主守护，PID=%d" % _spawn_role(ROLE_PRIMARY), role)
                except Exception as exc:                # noqa: BLE001
                    _log("拉起主守护失败：%s" % exc, role)
                time.sleep(3.0)

        except KeyboardInterrupt:
            _log("收到 Ctrl+C，保镖退出。", role)
            return 0
        except Exception as exc:                        # noqa: BLE001
            _log("保镖循环异常（已忽略，继续运行）：%s: %s"
                 % (type(exc).__name__, exc), role)
        time.sleep(GUARD_INTERVAL)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _status() -> int:
    primary = _role_pid(ROLE_PRIMARY)
    guard = _role_pid(ROLE_GUARD)
    alive, detail = probe()
    print("主守护 : %s" % ("运行中 PID %d" % primary if primary else "未运行"))
    print("保镖   : %s" % ("运行中 PID %d" % guard if guard else "未运行"))
    print("服务   : %s http://127.0.0.1:%d  %s"
          % ("OK  " if alive else "DOWN", PORT, detail))
    print("待机   : %s" % ("是" if _paused() else "否"))
    ka = _keepalive_config()
    if ka:
        spans = "、".join("%s-%s" % (a, b) for a, b in ka["windows"])
        print("保活   : %s" % ka["url"])
        print("         每 %.0f 分钟一次%s，时段 %s"
              % (ka["interval"] / 60.0,
                 "（仅工作日）" if ka["weekdays_only"] else "",
                 spans))
        print("         最近一次：%s" % _keepalive_last_note())
    else:
        print("保活   : 未启用（没有 data/keepalive.json，或 enabled 不是 true）")
    return 0 if alive else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="龙回头服务守护进程")
    ap.add_argument("--role", choices=[ROLE_PRIMARY, ROLE_GUARD], default=ROLE_PRIMARY,
                    help="运行角色：primary=主守护（看服务），guard=保镖（看主守护）")
    ap.add_argument("--no-guard", action="store_true", help="不启用保镖")
    ap.add_argument("--status", action="store_true", help="只探活一次并打印结果")
    ap.add_argument("--ensure-autostart", action="store_true", help="只写开机自启项")
    ap.add_argument("--remove-autostart", action="store_true", help="只删开机自启项")
    args = ap.parse_args(argv)

    if args.status:
        return _status()
    if args.ensure_autostart:
        ok, msg = ensure_autostart()
        print("%s %s" % ("OK" if ok else "FAIL", msg))
        return 0 if ok else 1
    if args.remove_autostart:
        ok, msg = remove_autostart()
        print("%s %s" % ("OK" if ok else "FAIL", msg))
        return 0 if ok else 1

    try:
        sys.stdout.reconfigure(encoding="utf-8")        # type: ignore[attr-defined]
    except Exception:                                   # noqa: BLE001
        pass
    if args.role == ROLE_GUARD:
        return run_guard()
    return run_primary(no_guard=args.no_guard)


if __name__ == "__main__":
    sys.exit(main())
