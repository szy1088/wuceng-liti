# 龙回头 · 五层立体短线交易系统

> **🌐 在线访问**：<https://wuceng-liti.onrender.com>
>
> 部署在 Render 免费层（新加坡节点）。闲置 15 分钟会休眠，**首次打开约需 1 分钟唤醒**，之后就快了。
> 本地跑（`python server.py`）则没有冷启动，行情也更新更实时。

一套本地运行的短线策略系统，把「五层立体」的交易纪律做成能直接看的界面与能自动送达的提醒。

整个界面用「五层立体塔」表达方案的五层结构，页面上的五个图层与方案的五大模块一一对应：

| 图层 | 方案章节 | 主题 | 实现内容 |
| --- | --- | --- | --- |
| 第一层 | 核心选股逻辑 | 非龙头不炒 | 今日热点题材（涨停池按行业板块聚合）、概念/行业板块榜、连板梯队与涨停池明细 |
| 第二层 | 核心战法 | 右侧「龙回头」 | 100 分制形态评分、评分明细、缩量/回调/均线证据链、激进与稳健买点、K 线图 |
| 第三层 | 日内交易与仓位管理 | 永远不要孤注一掷 | 仓位计算器、资金平分与观察哨测算、持仓体检清单 |
| 第四层 | 铁血纪律 | 会止损的是祖师爷 | 八级规则优先级诊断（止损 / 跌破 5 日线 / 两档止盈 / 效率退出 / 走弱预警） |
| 第五层 | 实施准备 | 短线功夫在盘外 | 情绪温度仪表、市场情绪切片、龙头池、每日复盘记录 |

**接入的是真实 A 股行情**，全部来自公开接口，无需任何密钥。

## 获取代码

```bash
git clone https://github.com/szy1088/wuceng-liti.git
cd wuceng-liti
```

克隆下来就能直接跑。想一开始就带着一份配置，把模板复制过去：

```powershell
Copy-Item store.example.json data\store.json
```

> `data/store.json` 存的是**你自己的**东西（资金、参数、自选、持仓、复盘、推送密钥），
> 已经在 `.gitignore` 里，**不会进版本库** —— 公开仓库要是带上了推送密钥，
> 等于把微信推送入口送给所有人。仓库里只有一份不含任何密钥的模板 `store.example.json`。
>
> 不复制也能跑：首次启动用内置默认值，你在页面上点保存时才会生成这个文件。

## 启动

只用 Python 标准库，**不需要安装任何第三方依赖**（不需要 pip install）。

```
python server.py
```

然后浏览器打开 <http://127.0.0.1:8766>。

Windows 上也可以直接双击 `start.ps1`，它会自动选一个可用的 Python 并打开浏览器。

- 端口占用时可用环境变量改端口：`set LHT_PORT=9000 && python server.py`
- 只允许本机访问时用 `LHT_HOST=127.0.0.1`（默认值）；改为 `0.0.0.0` 可让同一局域网内的手机/平板访问。
- 按 `Ctrl+C` 停止，或运行 `stop.ps1`。

> **想让网站一直开着、被杀掉也能自动复活？** 一条命令搞定，见下面的
> [常驻运行（守护进程）](#常驻运行守护进程)。

## 部署到云端（免费）

> **先澄清一个常见误解**：GitHub Pages **只能托管静态文件**，它跑不了 Python。
> 而本项目的行情抓取、100 分制评分、缓存全在 `server.py` 里，
> 所以**不能只靠 GitHub Pages 把站跑起来**。
> 正确做法是把整个项目部署到一个免费的 Python 托管平台，由它同时提供页面和 API。

### 一键部署到 Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/szy1088/wuceng-liti)

1. 点上面的按钮，或用 GitHub 账号打开 <https://render.com/deploy?repo=https://github.com/szy1088/wuceng-liti>
2. 用 GitHub 登录并授权（**不需要信用卡**）
3. 点 **Apply** —— 配置全在 `render.yaml` 里，一个字段都不用填
4. 等 2~3 分钟，拿到形如 `https://wuceng-liti.onrender.com` 的地址

`render.yaml` 里已经定好这些：

| 配置 | 值 | 为什么这么定 |
| --- | --- | --- |
| `plan` | `free` | 2026 年唯一还不需要信用卡的免费长驻服务 |
| `region` | `singapore` | 行情接口都在国内，新加坡最近。境外 IP 实测这 7 个接口全部 200，延迟 370~420ms |
| `startCommand` | `python server.py` | 零依赖，不需要 `pip install` |
| `healthCheckPath` | `/api/ping` | 极轻量探针，不碰任何外部接口，不会被行情接口抖动误杀 |

> **本仓库已经这样部署过一次**，线上实测：
> `/api/scan` 候选 309 / 评分 40 / 命中 24，与本地**逐条一致**，耗时还更快（3.2s vs 12.2s）。
> 所以「境外服务器抓不到中国行情接口」这个顾虑可以排除 —— 7 个数据源全部实测 200。

**免费层的代价**（2026 年现状，得认）：

- 闲置 **15 分钟休眠**，下次访问约 **1 分钟冷启动**（这是所有免费方案的共同代价）；
- 磁盘是**临时的**，服务重启后 `data/store.json` 恢复默认值（页面上会明确提示）；
  要真正持久化，见下面的 [Upstash Redis 方案](#让数据真正存下来upstash-redis可选)；
- 每月 750 实例小时，个人用绰绰有余。

> 其他平台的免费层现状：Fly.io 已改为需要信用卡、Koyeb 缩水成 scale-to-zero、
> Railway 只剩每月 $1 额度、Heroku 早在 2022 年就取消了免费层。
> **不需要信用卡、还能跑长驻进程的，基本只剩 Render。**

### 让数据真正存下来（Upstash Redis，可选）

Render / Vercel 免费实例的磁盘都是**临时**的：冷启动、重启、重新部署会把
`data/store.json` 清空。Vercel 更麻烦 —— 同一时刻会跑多个互相隔离的实例，
每个实例各有一份磁盘，请求打到哪个实例就看到哪份数据，所以档案会「时有时无」。

要让档案、自选、持仓、复盘跨重启保留，配一个免费的
[Upstash Redis](https://console.upstash.com/) 即可（不需要信用卡）：

1. 在 Upstash 控制台建一个免费 Redis 数据库；
2. 复制 **REST URL** 和 **REST TOKEN**；
3. 在部署平台（Vercel / Render）加两个环境变量：

| 变量 | 值 |
| --- | --- |
| `UPSTASH_REDIS_REST_URL` | `https://xxx.upstash.io` |
| `UPSTASH_REDIS_REST_TOKEN` | 控制台里的 REST Token |

也兼容 Vercel 市场集成自动注入的 `KV_REST_API_URL` / `KV_REST_API_TOKEN`。

配好后 `server.py` 会自动切换存储：元数据存 `<前缀>meta`，档案按月存
`<前缀>archive:YYYY-MM`（gzip + base64 压缩，单月通常只有十几 KB），
本地 `data/store.json` 继续作为离线备份。**没配这两个变量时行为完全不变**，
本地开发仍然是纯文件存储。

> 多套环境（本地 / Vercel / Render）共用一个库时，给其中一套设
> `LHT_KV_PREFIX=lht:dev:` 就能隔离数据。
> 公网实例的 `/api/store` 是**公开可读**的，不要在云端填推送密钥、持仓等个人数据。

档案页顶部会显示当前存储状态：`☁ 云端持久化` / `💾 本地文件` /
`⚠ 临时存储，重启会丢`，一眼就能确认有没有生效。

### 部署之后：消灭那 1 分钟冷启动

免费层闲置 15 分钟休眠，你下次打开就要等约 1 分钟。项目自带**两层保活**：

| 机制 | 在哪 | 什么时候起作用 |
| --- | --- | --- |
| **本机保活**（主力） | `watchdog.py`，交易时段每 10 分钟戳一次 | 你电脑开着的时候。时间精准，不依赖第三方 |
| **GitHub 定时任务**（兜底） | `.github/workflows/keepalive.yml` | 你电脑关着的时候。GitHub 免费跑，但可能延迟几分钟 |

**本机保活**默认关闭，开启只要一步：

```powershell
Copy-Item keepalive.example.json data\keepalive.json
```

然后按需改 `data\keepalive.json` 里的 `url` 和 `windows`（生效时段，按本机时间）。
改完最多 30 秒自动生效，**不用重启守护**。随时可以用这个命令看状态：

```powershell
powershell -ExecutionPolicy Bypass -File task.ps1 watchdog-status
```

```
=== 云端保活 ===
  目标：https://wuceng-liti.onrender.com
  频率：每 10 分钟一次（仅工作日）
  时段：09:00-11:35、12:45-15:10
  最近：成功 HTTP 200（10-18 09:05）
```

**GitHub 兜底**默认就是开的（工作流已在仓库里），但有两个限制要知道：

- GitHub 的定时任务是「尽力而为」的，高峰时段可能延迟几分钟到几十分钟，只适合兜底；
- 仓库连续 **60 天**没有任何提交活动，GitHub 会自动停掉定时任务 —— 随便推一次提交就恢复。

> **为什么不干脆 24 小时一直戳醒它？**
> 免费层每月给 750 实例小时，而一个月约 730 小时 —— 24 小时保活会把额度吃到见底、毫无余地。
> 只在交易时段保活，一个月才用掉约 100 小时，既够用又安全。
> 这也是「按需唤醒」比「永不休眠」更合理的地方。

### 部署到其他平台

仓库里备好了三种入口，按平台任选：

| 文件 | 适用平台 |
| --- | --- |
| `render.yaml` | Render（一键蓝图） |
| `Dockerfile` | Koyeb / Back4App / Northflank / 自己的 VPS |
| `Procfile` | Heroku 系 |

两个通用要点：

- 平台如果注入 `PORT`，`server.py` 会**自动**改绑 `0.0.0.0:$PORT`；
  也可以显式设 `LHT_HOST=0.0.0.0`、`LHT_PORT=...`
- 想被外部访问，必须绑 `0.0.0.0`。本地默认只绑 `127.0.0.1`，这是有意的安全默认值。

### 可选：只把前端放 GitHub Pages

想用 `https://szy1088.github.io/wuceng-liti/` 这个地址的话，可以前端走 Pages、后端仍在 Render：

1. 在 Render 加环境变量 `LHT_CORS_ORIGIN` = `https://szy1088.github.io`
2. 仓库 Settings → Secrets and variables → Actions → **Variables** 新增
   `LHT_API_BASE` = 你的 Render 地址（如 `https://wuceng-liti.onrender.com`）
3. 仓库 Settings → **Pages** → Source 选 **GitHub Actions**
4. Actions → 「把 web/ 发布到 GitHub Pages」→ **Run workflow**

前端读的是 `web/index.html` 里的 `<meta name="lht-api-base">`，留空即同源。
发布工作流会自动把仓库变量里的后端地址填进去。

> **为什么 CORS 默认是关的**：`/api/store` 会返回你填的推送密钥（Server酱 SendKey、
> 企业微信 webhook）。本地跑着 `127.0.0.1:8766` 时如果允许任意来源跨域读取，
> 你随手打开一个恶意网页就能把密钥偷走。所以只有确实需要跨域时才用
> `LHT_CORS_ORIGIN` 打开，并且建议填具体来源而不是 `*`。

### 部署到公网后的安全提醒

- **不要把推送密钥配在公网实例上** —— 任何人都能访问 `/api/store`。
  而且免费层重启就丢，配了也没有意义。
- 推送、持仓、复盘这类**带个人数据**的功能，留在本机跑就够。
- 本服务不下单、不读账户、不连券商，即使公开也不存在资金风险。

## 常驻运行（守护进程）

**目标：任何时候 http://127.0.0.1:8766 都能正常打开。**

装一次就行：

```powershell
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-install
```

它会做四件事：

1. 把一个快捷方式放进「启动」文件夹 —— 登录后自动拉起守护；
2. 写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 注册表自启项（第二条独立保险）；
3. 立刻在后台启动**主守护**进程；
4. 主守护再拉起一个**保镖**进程，两者互保。

### 两层自愈

| 谁死了 | 谁来救 | 多久 |
| --- | --- | --- |
| `server.py`（网站服务） | 主守护 | 约 10 秒 |
| 主守护 | 保镖 | 约 2 秒 |
| 保镖 | 主守护 | 约 5 秒 |
| 开机自启项被删 | 主守护（每 5 分钟自检） | 最多 5 分钟 |

主守护每 5 秒向 `/api/ping` 探活一次；**连续 2 次失败**才动手（避免一次网络抖动
就误杀健康服务）。动手时先清理占着端口的僵死进程，再重新拉起 `server.py`；
两次重启之间有 10 秒冷却，防止配置写错时疯狂重启。

保镖只做一件事：每 2 秒确认主守护还活着，不在就拉一个新的。两个进程互相盯着，
所以「只杀掉其中一个」是没用的。

> 用的是 `pythonw.exe`，全程不弹黑窗口；日志写在 `logs\` 下面。

**关于「黑窗一直闪」**：这是个很隐蔽的坑。守护由 `pythonw.exe` 启动，**它自己没有控制台**；
于是每当它调用 `tasklist` / `netstat` / `taskkill` 这类「控制台子系统」程序时，
Windows 都会给子进程**新建一个控制台窗口** —— 屏幕上一闪一闪的黑窗就是这么来的
（保镖每 2 秒一次，主守护每 5 秒一次，实测 12 秒能抓到 7 次）。

现已两处根治：

1. 「进程是否存活」改用 Win32 API（`OpenProcess` + `WaitForSingleObject`），
   连子进程都不起 —— 既没有窗口，也比解析 `tasklist` 文本可靠得多
   （之前就因为文本解析偶发失败，把活得好好的保镖误判成已死，白拉起好几个进程）；
2. 剩下确实要起子进程的地方（`netstat` / `taskkill`，只在重启时用）统统加 `CREATE_NO_WINDOW`。

实测：现在守护正常运行期间**子进程数为 0**，一个黑窗都不会再出现。
如果你还看到闪动，那来自别的程序 —— 本项目已与本机其他进程隔离。

### 常用命令

```powershell
# 看状态（守护角色 / 服务健康 / 自启项 / 最近日志）
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-status

# 临时停护（做维护、改代码时用；期间服务不会被自动拉起）
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-pause
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-resume

# 彻底拆掉守护（不会停掉网站服务本身）
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-uninstall
```

也可以直接看守护自己的状态：

```bash
python watchdog.py --status     # 退出码 0=健康 / 1=不健康，便于脚本调用
python watchdog.py              # 前台跑主守护（调试用，Ctrl+C 退出）
```

### 日志

| 文件 | 内容 |
| --- | --- |
| `logs\watchdog.log` | 探活失败、重启、角色互保，超过 1MB 自动轮转成 `.1` |
| `logs\server.log` | 网站服务的全部输出（含每次请求） |

客户端刷新页面/关标签导致的连接中断属于正常现象，**不会**再往日志里刷 traceback。

### 手动停服务时请注意

装了守护之后，直接 `Stop-Process` 杀服务是没用的 —— 10 秒内就会被拉回来。
`stop.ps1` 已经处理了这一点：它会先把守护切到待机，再停服务；
用 `start.ps1` 启动时会自动解除待机。

### 管理员权限下可以更强

上面这套**完全不需要管理员权限**（本项目的会话就是受限令牌，验证过
`schtasks /Create` 会被拒绝）。如果你有管理员权限，还能再加一层
Windows 任务计划程序：`-Action install` 注册的计划任务可以配置
「失败时重启」，那是比守护进程更底层的兜底。

## 数据来源

| 用途 | 接口 | 说明 |
| --- | --- | --- |
| 实时快照 / 指数 | 腾讯 `qt.gtimg.cn/q=` | GBK，批量；含量比、换手、流通市值、涨停价 |
| 日 K 线 / 交易日历 | 新浪 `CN_MarketData.getKLineData` | 需带 Referer；服务端并发抓取 |
| 涨停池 / 跌停池 / 连板梯队 | 东方财富 `push2ex` | `getTopicZTPool` / `getTopicDTPool`，支持历史日期 |
| 概念 / 行业板块榜 | 新浪 `newFLJK.php` / `newSinaHy.php` | GBK，涨幅榜 |

> 东财 push2 的 clist/ulist 系列对高频请求会限流（502 / 连接重置），本项目**刻意不使用**它。
> 第一层的「选热点」改为由涨停池按行业板块聚合 —— 这恰好是方案第五层复盘原文
> 「把今天所有的涨停股拉出来，归纳出当前最强的 2-3 个概念板块」的自动化。

服务端对每个数据源做带 TTL 的内存缓存（快照 3s / K 线 600s / 板块 30s / 涨停池 300s），
避免频繁请求被限流；接口失败时回退到上一次的缓存值，不会把页面打空。

### 上游接口变慢时不会被拖垮

一次扫描最坏情况曾经要 **178 秒**（一只股票 10 秒超时 × 3 次重试 × 40 只 ÷ 10 线程，
再叠加涨停池的 10 个日期 ÷ 6 线程）。这会直接毁掉 15:05 的定时推送。现在有四道保护：

| 保护 | 作用 |
| --- | --- |
| **慢失败不重试** | 一次尝试把超时耗光，说明对面是「慢」不是「偶发错」，重试必然还是慢 → 立即放弃。40 只股票从 120 次请求降到 40 次 |
| **阶段时间预算** | 涨停池 20s、个股K线 25s 的硬上限；到点就跳过没抓到的，绝不干等 |
| **单飞缓存** | 同一个 key 过期时只放一个线程去抓，其余等结果。避免前端 3 秒轮询在缓存失效瞬间打出一堆重复请求 |
| **慢接口日志** | 单个外部请求超过 4 秒会在 `logs\server.log` 记一条 `[慢接口]`，方便事后定位 |

实测（40 只候选 / 10 日涨停池）：

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 网络正常 | 13.4s | **7.4s** |
| 个股 K 线全部挂起 | 129.9s | **27.5s** |
| 整个外网全断 | 约 180s | **24.0s**（并给出「涨停池来源不可用」降级提示） |

扫描结果与修复前逐条一致（命中 24 只，襄阳轴承 88 分居首），只是快了很多。

## 评分口径（第二层，100 分制）

由「五层立体」方案的五个模块逐条推导，分值分配如下：

| 项 | 分值 | 依据 |
| --- | --- | --- |
| A 龙头辨识度 | 25 | 前期 2~3 个强悍连板 |
| B 回调时间 | 15 | 缩量回踩 3~8 个交易日 |
| C 回调幅度 | 20 | 回调 20%~30% |
| D 缩量程度 | 20 | 无量回踩（回调期均量 ÷ 拉升期**天量**） |
| E 均线支撑 | 10 | 回踩 10/20 日均线止跌 |
| F 流通市值 | 5 | 30 亿 ~ 120 亿 |
| G 拉升期换手 | 5 | 拉升期换手 10% ~ 20% |

分级：**A ≥ 80 / B ≥ 65 / C ≥ 50**。

两个关键算法决策：

1. 缩量比的参照系是**拉升期天量**而不是拉升期均量。一字板期间筹码锁死、成交量极小，
   用均量作分母会得出「回调放量 16 倍」的荒谬结论。
2. 拉升期最高价允许出现在连板段**之后**（炸板/天量阴线当天往往才是最高点），
   否则回调幅度会被系统性低估。

买点：
- **稳健买点** = 缩量回踩均线出现止跌小实体；
- **激进买点** = 放量突破洗盘箱体上沿（`right_side`）。

## 微信推送

把「龙回头扫描结果」推到你自己的微信。**只做「系统 → 你」的单向提醒**：
不登录微信客户端、不接收消息、不读账户、不下单。没有使用 itchat / wechaty
那类模拟客户端方案——那类做法违反微信使用协议，有封号风险。

### 怎么配

页面右上角 **⚙ 策略参数 → 微信推送**：

| 字段 | 说明 |
| --- | --- |
| 推送通道 | Server酱 / PushPlus / 企业微信群机器人 / 关闭 |
| 密钥 | 对应通道的 SendKey / token / webhook 地址 |
| 只推该评分以上 | 默认 65（B 级），低于此分不上榜 |
| 单条最多几只 | 默认 8，防止消息过长 |
| 交易日自动推送时刻 | 默认 `15:05`，逗号分隔可填多个，如 `09:20,15:05` |
| 扫描窗口（交易日） | 默认 10 |

填好先点 **📶 测试推送** 验证通道，成功后 **保存参数**。
第二层扫描面板上还有 **📤 推送到微信**，可以随时手动推一次当前结果。

拿密钥：

- **Server酱**：<https://sct.ftqq.com> 微信扫码登录 → 复制 SendKey（`SCT…` 或 `sctp…`）。
  Turbo 免费版每天 5 条，这个用途足够。
- **PushPlus**：<https://www.pushplus.plus> 微信扫码登录 → 复制 token。
- **企业微信群机器人**：企业微信建一个只有自己的群 → 添加群机器人 → 复制完整
  Webhook 地址。官方接口，最稳。

### 谁来触发

**方式一（默认，无需管理员）**：网站服务自带的常驻线程。只要 `server.py` 在跑，
到点就会自动扫描并推送；会先校验「今天确实是交易日」，节假日不打扰。

**方式二（需要管理员）**：不依赖网站是否开着。用 Windows 任务计划程序：

```powershell
# 每个交易日（周一至周五）15:05 自动扫描并推送
powershell -ExecutionPolicy Bypass -File task.ps1 -Action install -At 15:05

powershell -ExecutionPolicy Bypass -File task.ps1 -Action run       # 立刻跑一次
powershell -ExecutionPolicy Bypass -File task.ps1 -Action status    # 查看状态
powershell -ExecutionPolicy Bypass -File task.ps1 -Action uninstall # 取消
```

`scan_push.py` 也可以单独用（不启动网站）：

```bash
python scan_push.py                    # 扫描并推送（非交易日自动跳过）
python scan_push.py --test             # 只发测试消息
python scan_push.py --force            # 非交易日也发
python scan_push.py --top 5 --min-score 70
```

**方式三（荐，无需管理员）**：让网站在登录后自动在后台启动，并挂上守护进程，
于是「方式一」的定时推送始终生效：

```powershell
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-install
powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-uninstall
```

（旧名字 `-Action autostart-install` 仍然可用，现在等价于 `watchdog-install`；
只想要「开机自启、不带守护」的老行为，用 `-Action server-autostart-install`。）

推送内容长这样：

```
龙回头扫描 · 2026-10-16 · 命中 24 只

市场情绪  涨停 61 家 · 最高 11 板 · 跌停 10 家 · 情绪温度 90（主线亢奋）
扫描概况  候选 309 只 · 实际评分 40 只 · B 级以上 24 只 · 耗时 20.35s

1. 襄阳轴承 000678  88 分 · A 级
> 4 连板 · 回调 6 日 · 回调 21.4% · 缩量比 54% · 汽车零部
- 现价 10.93　+9.96%　换手 13.16%　量比 0.84　流通 50 亿
- 买点：买点未触发，仅观察（MA5 10.76）
- 仓位：首笔 1300 股 ≈ 14,209 元，上限补至 4500 股
```

> 推送失败不会中断任何流程：通道未开、密钥为空、接口报错都会收敛成一条
> 可读的提示（例如 `HTTP 400 [AUTH]错误的Key`），只在页面上弹一下 toast。

## 龙回头档案（按月 / 按日收藏）

第二层每次扫描成功后，评分达到档案线（默认 **65 分，即 B 级及以上**）的标的会自动封存。
左侧电梯的 **06 龙回头档案** 就是档案室：

- **月份卡**：点一下展开当月所有交易日；月份卡上带交易日热力格、命中数量与最高评分。
- **日期卡**：点一下展开当天的全部命中标的；再点收起。
- **标的卡**：显示首次命中的时间、当时股价、涨幅、连板高度、回调天数 / 幅度、缩量比、板块与买点状态。
- **详情**：点标的卡打开详情，包含命中时的日 K、七项评分明细、关键价位、仓位测算，以及
  「时间 / 股价 / 评分」的历次命中快照。
- **两套主题**：右上角可切换 **鎏金夜**（暗金档案室）与 **青瓷昼**（浅色青瓷），选择会记在浏览器里。
- **检索与导出**：支持按代码 / 名称 / 板块搜索、按 A/B 级筛选，并可一键导出完整档案 JSON。

档案存在 `data/store.json` 的 `dragonArchive` 字段里，结构是：

```
dragonArchive
└─ 2026-10                        月份
   └─ 2026-10-19                  交易日
      ├─ createdAt / updatedAt
      └─ items
         └─ 600519                单只标的
            ├─ firstMatchedAt    首次命中的时间（永不覆盖）
            ├─ firstPrice        首次命中时的股价
            ├─ lastMatchedAt     最近一次确认的时间
            ├─ hitCount / snapshots  命中次数与逐次快照
            ├─ score / details   评分与七项证据链
            ├─ levels / plan     当时的关键价位与仓位测算
            └─ bars              命中时的日 K（用于详情缩略图）
```

同一天同一只股票只保留一条：后续扫描会更新「最近确认」并追加快照，不会重复占卡。
档案线可在 **⚙ 策略参数 → 档案收录评分下限** 调整；把 `archiveAuto` 设为 `false`
可关闭自动存档（仍可通过 `POST /api/archive` 手动保存）。

## 重要边界

- 本系统**只做纪律提示，不构成投资建议**；
- **不连接券商、不读取交易账户、不发送任何委托**，没有「一键下单」或无人值守开关；
- 所有买卖点、止损止盈价位均为按方案参数计算出的**提示值**，最终决策与风险由使用者承担；
- 公开行情接口可能临时限流或调整，页面会显示「数据源」状态与降级警告，请以券商行情为准；
- 参数取自方案的区间表达，可在「⚙ 策略参数」中调整；
- 微信推送是**单向**的：只能系统发给你，你不能通过微信下指令或查询；
  它同样不下单、不读账户，与上面的边界完全一致。

## 目录

```
server.py                    后端：数据源、评分算法、API 路由（纯标准库）
push.py                      微信推送通道（Server酱 / PushPlus / 企业微信，纯标准库）
scan_push.py                 命令行：扫描一次并推送（可挂任务计划程序）
watchdog.py                  守护进程：主守护（看服务）+ 保镖（看主守护），双进程互保
task.ps1                     守护安装 / 定时任务 / 开机自启管理
web/index.html               页面结构（五个图层 + 总览 + 龙回头档案 + 设置对话框）
web/styles.css               五层立体主题样式（CSS 3D 等距塔 + 深空驾驶舱 + 档案双主题）
web/app.js                   前端逻辑（电梯切换、3D 塔、canvas K 线、悬停预览、档案卡片、表单持久化）
data/store.json              本地持久化（参数 / 自选 / 持仓 / 复盘 / 交易 / 推送配置 / 龙回头档案）
data/watchdog.pid            主守护 PID（进程互保用，自动维护）
data/watchdog.guard.pid      保镖 PID（自动维护）
data/watchdog.off            存在即让守护待机（维护开关，删除即恢复）
logs/watchdog.log            守护日志（1MB 自动轮转）
logs/server.log              网站服务日志
start.ps1 / stop.ps1         启动与停止脚本（会自动协同守护的待机开关）
store.example.json           配置模板（不含任何密钥，进版本库）
.gitignore                   排除 data/ 与 logs/ —— 防止推送密钥被误传
.gitattributes               锁定换行符（.ps1 必须保留 UTF-8 BOM，否则 PowerShell 5.1 会解析失败）
requirements.txt             声明这是 Python 项目（零依赖，内容只是说明）
render.yaml                  Render 免费部署蓝图（一键部署）
Dockerfile                   给 Koyeb / Back4App / VPS 等平台用
Procfile                     Heroku 系平台用
.github/workflows/pages.yml  可选：把 web/ 发布到 GitHub Pages
.github/workflows/keepalive.yml  兜底：GitHub 定时唤醒线上实例（你的电脑关机时用）
keepalive.example.json       云端保活配置模板（复制到 data/keepalive.json 即开启）
```

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/ping` | 极轻量存活探针（守护进程每秒都在打它，不碰任何外部接口） |
| GET | `/api/overview` | 指数、涨停/跌停池、连板梯队、情绪温度、数据源状态 |
| GET | `/api/hot?days=5` | 热点聚合 + 概念/行业板块榜（第一层） |
| GET | `/api/limitup?date=` | 涨停池与连板梯队（第一层） |
| GET | `/api/dragons?days=10` | 龙头池（第五层） |
| GET | `/api/scan?limit=40&days=10` | 龙回头评分扫描（第二层） |
| GET | `/api/quote?codes=a,b` | 批量实时快照 |
| GET | `/api/preview?code=` | 悬停预览用：快照 + 末 40 根日K（日K 600s 缓存） |
| GET | `/api/minute?code=` | 悬停预览用：当日分时（242 个分钟点 + 均价线，60s 缓存） |
| GET | `/api/stock?code=` | 单只股票的完整评分视图 + K 线 |
| GET | `/api/archive` | 龙回头档案树（月份 → 日期 → 标的） |
| POST | `/api/archive` | 档案维护：`{"action":"save","scan":{...}}` / `{"action":"delete","date":"YYYY-MM-DD","code":"600000"}` / `{"action":"clear"}` |
| POST | `/api/evaluate` | 持仓纪律诊断（第四层） |
| POST | `/api/notify` | 微信推送：`{"test":true}` 测试通道，`{"scan":true}` 扫描并推送 |
| GET/POST | `/api/store` | 读取 / 保存本地配置（`settings` 按字段合并，其余按 key 整体替换） |
