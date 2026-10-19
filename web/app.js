/* ==========================================================================
   龙回头 · 五层立体短线交易系统  —  前端逻辑
   纯原生 JS，零第三方依赖；K线/仪表均为手绘（canvas / svg）。
   五层对应方案五大模块：选股逻辑 / 龙回头战法 / 仓位管理 / 铁血纪律 / 每日复盘
   ========================================================================== */
'use strict';

/* ------------------------------------------------------------------ */
/* 常量                                                                 */
/* ------------------------------------------------------------------ */

const REFRESH_MS = 20000;

const LAYERS = [
  { page: 1, no: '01', title: '选股逻辑', color: '#f5a524', hint: '非龙头不炒' },
  { page: 2, no: '02', title: '龙回头战法', color: '#f04438', hint: '缩量低吸 · 右侧确认' },
  { page: 3, no: '03', title: '仓位管理', color: '#22c3e6', hint: '分批建仓 · 不孤注一掷' },
  { page: 4, no: '04', title: '铁血纪律', color: '#a78bfa', hint: '止损止盈 · 无条件执行' },
  { page: 5, no: '05', title: '每日复盘', color: '#34d399', hint: '盘外功夫 · 情绪监控' },
];

const MONTH_CN = ['壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖', '拾', '拾壹', '拾贰'];
const MONTH_EN = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const WEEK_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

const SETTING_FIELDS = [
  ['capital', '短线总资金（元）', 1000],
  ['maxPositionPct', '单股持仓上限（%）', 5],
  ['sleeveCount', '资金平分份数', 1],
  ['starterPct', '首笔观察哨比例（%）', 5],
  ['stopLossPct', '绝对止损线（%）', 0.5],
  ['takeProfitHalfPct', '一档止盈（%）', 0.5],
  ['takeProfitFullPct', '二档止盈（%）', 0.5],
  ['staleDays', '未启动退出日数', 1],
  ['floatCapMin', '流通市值下限（亿）', 1],
  ['floatCapMax', '流通市值上限（亿）', 1],
  ['pullbackDaysMin', '回调周期下限（日）', 1],
  ['pullbackDaysMax', '回调周期上限（日）', 1],
  ['pullbackPctMin', '回调幅度下限（%）', 1],
  ['pullbackPctMax', '回调幅度上限（%）', 1],
  ['panicLimitDowns', '跌停退潮阈值（家）', 1],
  ['archiveMinScore', '档案收录评分下限（分）', 5],
];

/* 微信推送通道（只做「系统 → 你」的单向提醒，不接收消息、不登录微信客户端）
   可以同时勾选多个，同一份内容并行发出——某个通道挂了不影响另一个。 */
const NOTIFY_CHANNELS = [
  ['serverchan', 'Server酱', 'SendKey（SCT… / sctp…）'],
  ['pushplus', 'PushPlus', 'token（或带 token 的完整地址）'],
  ['wecom', '企业微信群机器人', 'Webhook 地址'],
];

const WECOM_FORMATS = [
  ['text', '纯文本（个人微信也能读）'],
  ['markdown', 'Markdown（仅企业微信内好看）'],
];

const NOTIFY_HINT = {
  off: '当前未开启推送。勾选至少一个通道并填入密钥后才会发送；未开启时定时任务也不会发消息。',
  serverchan: '打开 <code>sct.ftqq.com</code> 微信扫码登录，复制 SendKey。Turbo 免费版每天 5 条，只推收盘一条的话用不完。',
  pushplus: '打开 <code>pushplus.plus</code> 微信扫码登录，复制 token；也可以直接粘贴带 token 的完整推送地址。',
  wecom: '企业微信 → 内部群 → 右上角「···」→ <b>消息推送</b>（老版叫「群机器人」）→ 新创建一个 → 复制 Webhook。'
    + '<b>格式务必选「纯文本」</b>：markdown 在企业微信里好看，但同步到<b>个人微信</b>会变成「暂不支持此消息类型」，等于白推。'
    + '想让个人微信收到，还要在管理后台「我的企业 → 微信插件」生成二维码、用个人微信扫码关注。',
};

/* ------------------------------------------------------------------ */
/* 全局状态                                                             */
/* ------------------------------------------------------------------ */

const state = {
  page: 0,
  overview: null,
  hot: null,
  limitup: null,
  scan: null,
  dragons: null,
  store: null,
  settings: {},
  evalResult: null,
  selected: null,
  scanning: false,
  chart: null,
  /* 龙回头档案 */
  archive: null,
  archiveAt: 0,
  archiveQuery: '',
  archiveGrade: 'all',
  archiveTheme: 'noir',
  archiveOpen: { months: {}, days: {} },
  archiveInit: false,
  archiveDetail: null,
};

const _loaded = {};
const stale = (key, ms) => Date.now() - (_loaded[key] || 0) > ms;
const mark = (key) => { _loaded[key] = Date.now(); };
const invalidate = (key) => { delete _loaded[key]; };

/* ------------------------------------------------------------------ */
/* 基础工具                                                             */
/* ------------------------------------------------------------------ */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const num = (v) => (v === null || v === undefined || v === '' || isNaN(Number(v))) ? null : Number(v);

const fmt = (v, d = 2) => { const x = num(v); return x === null ? '—' : x.toFixed(d); };

const sgn = (v, d = 2) => { const x = num(v); return x === null ? '—' : (x > 0 ? '+' : '') + x.toFixed(d); };

const tone = (v) => { const x = num(v); return x === null ? 'flat' : (x > 0 ? 'pos' : (x < 0 ? 'neg' : 'flat')); };

const pctCell = (v, d = 2) => `<span class="${tone(v)}">${sgn(v, d)}%</span>`;

function money(v) {
  const x = num(v);
  if (x === null || x === 0) return '—';
  const a = Math.abs(x);
  if (a >= 1e8) return (x / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (x / 1e4).toFixed(1) + '万';
  return x.toFixed(0);
}

function esc(v) {
  return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function gradeOf(score) {
  const s = num(score) || 0;
  if (s >= 80) return { letter: 'A', cls: 'grade-A' };
  if (s >= 65) return { letter: 'B', cls: 'grade-B' };
  if (s >= 50) return { letter: 'C', cls: 'grade-C' };
  return { letter: 'X', cls: 'grade-X' };
}

const scorePill = (score) => {
  const g = gradeOf(score);
  return `<span class="score-pill ${g.cls}">${fmt(score, 0)}<small>分</small></span>`;
};

function dateStr(d) {
  d = String(d || '');
  if (d.length === 8 && /^\d+$/.test(d)) return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
  return d || '—';
}

function toast(msg, bad) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('bad', !!bad);
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3200);
}

// 后端地址（默认空 = 同源相对路径，本地和整站部署都走这里）：
//   整站部署（本地 / Render）      → 留空即可
//   前端放 GitHub Pages、后端在别处 → 在 index.html 的
//                                    <meta name="lht-api-base" content="https://xxx.onrender.com">
//                                    里填后端地址，这里会自动前缀上。
const API_BASE = (((document.querySelector('meta[name="lht-api-base"]') || {}).content) || '')
  .trim().replace(/\/+$/, '');

async function api(path, opts) {
  const res = await fetch(API_BASE + path, opts);
  return res.json();
}

function postJSON(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

function busy(btn, on, label) {
  if (!btn) return;
  if (on) {
    btn._label = btn.textContent;
    btn.disabled = true;
    if (label) btn.textContent = label;
  } else {
    btn.disabled = false;
    if (btn._label) btn.textContent = btn._label;
  }
}

/* ------------------------------------------------------------------ */
/* 五层立体塔                                                           */
/* ------------------------------------------------------------------ */

const TOTAL_STEP = 46;

function renderTower() {
  const box = $('#tower');
  if (!box) return;
  box.innerHTML = LAYERS.map((L, i) => {
    const z = (i - (LAYERS.length - 1) / 2) * TOTAL_STEP;
    return `<div class="floor3d" data-layer="${L.page}" title="第 ${L.no} 层 · ${L.title}"
                 style="--z:${z}px;--c:${L.color}">
        <div class="slab"></div>
        <div class="slab-label">
          <span class="n">${L.no}</span>
          <span class="t">${L.title}</span>
          <span class="k" data-k="${L.page}">${L.hint}</span>
        </div>
      </div>`;
  }).join('');

  $$('.floor3d', box).forEach((f) => {
    f.addEventListener('mouseenter', () => focusFloor(Number(f.dataset.layer)));
    f.addEventListener('mouseleave', () => focusFloor(state.page));
  });
}

function focusFloor(page) {
  $$('.floor3d').forEach((f) => {
    const v = Number(f.dataset.layer);
    f.classList.toggle('is-focus', page > 0 && v === page);
    f.classList.toggle('is-dim', page > 0 && v !== page);
  });
}

function towerKpi(page, text) {
  const el = $(`.floor3d .k[data-k="${page}"]`);
  if (el) el.textContent = text;
}

/* ------------------------------------------------------------------ */
/* 页面切换                                                             */
/* ------------------------------------------------------------------ */

function switchPage(page) {
  page = Number(page) || 0;
  state.page = page;
  $$('.page').forEach((el) => el.classList.toggle('is-active', Number(el.dataset.page) === page));
  $$('.lift-btn').forEach((b) => b.classList.toggle('is-active', Number(b.dataset.layer) === page));
  focusFloor(page);
  window.scrollTo({ top: 0, behavior: 'smooth' });
  onEnterPage(page);
}

function onEnterPage(page) {
  if (page === 0) loadOverview();
  else if (page === 1) { loadHot(); loadLimitup(); }
  else if (page === 2) { if (state.scan && !$('#scan-result').querySelector('.tbl')) renderScan(state.scan); loadLimitup(); }
  else if (page === 3) { renderCalc(); loadPositions(); }
  else if (page === 4) { loadDiscipline(); }
  else if (page === 5) { loadDragons(); renderReviews(); syncReviewDefaults(); loadOverview(); }
  else if (page === 6) { loadArchive(); }
}

/* ------------------------------------------------------------------ */
/* 总览                                                                 */
/* ------------------------------------------------------------------ */

async function loadOverview(force) {
  if (!force && !stale('overview', 8000) && state.overview) return renderOverview(state.overview);
  try {
    const d = await api('/api/overview');
    if (!d.ok) throw new Error(d.error || '接口异常');
    state.overview = d;
    mark('overview');
    renderOverview(d);
  } catch (e) {
    toast('总览数据获取失败：' + e.message, true);
  }
}

function renderOverview(d) {
  const s = d.session || {};
  const idx = d.indices || [];
  const main = idx.find((x) => x.code === '000001') || idx[0] || {};

  /* 顶栏状态 */
  const chipSession = $('#chip-session');
  chipSession.querySelector('b').textContent = s.label || '—';
  chipSession.querySelector('small').textContent = dateStr(s.market_date);
  chipSession.querySelector('.dot').className = 'dot ' + (s.is_live ? 'ok live' : (s.state === 'closed' ? '' : 'warn'));

  const chipMarket = $('#chip-market');
  chipMarket.querySelector('b').textContent = main.name || '—';
  chipMarket.querySelector('small').innerHTML = `${fmt(main.price)}　${sgn(main.pct)}%`;
  chipMarket.querySelector('.dot').className = 'dot ' + (num(main.pct) > 0 ? 'bad' : (num(main.pct) < 0 ? 'ok' : 'info'));

  const warnCount = (d.warnings || []).length;
  const chipSource = $('#chip-source');
  chipSource.querySelector('small').textContent = warnCount ? `${warnCount} 项降级` : `正常 · ${d.sources?.requests ?? 0} 次`;
  chipSource.querySelector('.dot').className = 'dot ' + (warnCount ? 'warn' : 'ok');

  /* KPI */
  const tem = d.sentiment || {};
  const up = d.limitup || {};
  const down = d.limitdown || {};
  const kpis = [
    { cls: 'red', lab: '涨停家数', val: up.count ?? '—', sub: `最高 ${up.max_board ?? 0} 连板` },
    { cls: 'amber', lab: '最高连板', val: up.max_board ?? '—', sub: '梯队高度决定持续性' },
    { cls: 'green', lab: '跌停家数', val: down.count ?? '—', sub: `退潮阈值 ${tem.panic_threshold ?? '—'} 家` },
    { cls: 'violet', lab: '情绪温度', val: tem.temperature ?? '—', sub: tem.status || '—' },
    { cls: 'accent', lab: '接口调用', val: d.sources?.requests ?? 0, sub: `错误 ${d.sources?.errors ?? 0} 次` },
  ];
  $('#kpi-row').innerHTML = kpis.map((k) => `
    <div class="kpi ${k.cls}">
      <div class="lab">${esc(k.lab)}</div>
      <div class="val">${esc(k.val)}</div>
      <div class="sub">${esc(k.sub)}</div>
    </div>`).join('');

  /* 指数条 */
  $('#index-strip').innerHTML = idx.length ? idx.map((x) => `
    <div class="idx">
      <span class="nm">${esc(x.name)}</span>
      <span class="pv ${tone(x.pct)}">${fmt(x.price)}</span>
      <span class="ch ${tone(x.pct)}">${sgn(x.pct)}%</span>
    </div>`).join('') : '<div class="empty">指数行情暂不可用</div>';

  /* 数据源 */
  const src = d.sources || {};
  const rows = Object.keys(src).filter((k) => k !== 'requests' && k !== 'errors').map((k) => `
    <div class="src-card"><div class="sc-name">${esc(k)}</div><div class="sc-val">${esc(src[k])}</div></div>`);
  $('#src-grid').innerHTML = rows.join('') || '<div class="empty">无数据源信息</div>';
  const tag = $('#src-tag');
  tag.className = 'tag ' + (warnCount ? 'warn' : '');
  tag.textContent = warnCount ? `${warnCount} 项降级` : '全部正常';

  /* 塔上的关键指标 */
  towerKpi(1, `涨停 ${up.count ?? 0} 家 · 高度 ${up.max_board ?? 0}`);
  towerKpi(3, (state.store?.positions || []).length ? `持仓 ${state.store.positions.length} 只` : '分批建仓 · 不孤注一掷');
  towerKpi(5, `情绪 ${tem.temperature ?? '—'} · ${(d.limitup?.ladder ? Object.keys(d.limitup.ladder).length : 0)} 档梯队`);

  updateGauge(tem.temperature ?? 0, tem.status || '');
  renderSentimentStats(d);
  renderLadder(up.ladder, $('#ladder2'));
}

function updateGauge(temp, status) {
  const el = $('#gauge');
  if (!el) return;
  const W = 220, H = 130, cx = 110, cy = 110, r = 86;
  const A0 = Math.PI, A1 = 2 * Math.PI;
  const t = Math.max(0, Math.min(100, num(temp) || 0));
  const end = A0 + (t / 100) * Math.PI;

  const pt = (a, rad) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
  const arc = (a0, a1, rad) => {
    const [x0, y0] = pt(a0, rad), [x1, y1] = pt(a1, rad);
    const large = (a1 - a0) > Math.PI ? 1 : 0;
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${rad} ${rad} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };

  const ticks = [0, 25, 50, 75, 100].map((v) => {
    const a = A0 + (v / 100) * Math.PI;
    const [x1, y1] = pt(a, r - 13), [x2, y2] = pt(a, r - 22);
    const [tx, ty] = pt(a, r - 33);
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
              stroke="rgba(126,160,214,.4)" stroke-width="1.5"/>
            <text x="${tx.toFixed(1)}" y="${(ty + 4).toFixed(1)}" text-anchor="middle"
              font-size="9" fill="#6f83a3" font-family="monospace">${v}</text>`;
  }).join('');

  const [nx, ny] = pt(end, r - 26);
  const needleColor = t >= 75 ? '#f04438' : (t >= 50 ? '#f5a524' : '#22c3e6');

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="150" role="img" aria-label="情绪温度 ${t}">
      <defs>
        <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#22c3e6"/>
          <stop offset="50%" stop-color="#f5a524"/>
          <stop offset="100%" stop-color="#f04438"/>
        </linearGradient>
      </defs>
      <path d="${arc(A0, A1, r)}" fill="none" stroke="rgba(126,160,214,.16)" stroke-width="13" stroke-linecap="round"/>
      <path d="${arc(A0, end, r)}" fill="none" stroke="url(#gaugeGrad)" stroke-width="13" stroke-linecap="round"/>
      ${ticks}
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}"
            stroke="${needleColor}" stroke-width="3" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="6" fill="#0b1220" stroke="${needleColor}" stroke-width="2.5"/>
    </svg>
    <div class="g-val">
      <b>${Math.round(t)}</b>
      <small>${esc((status || '').split('·')[0].trim() || '情绪温度')}</small>
    </div>`;
}

function renderSentimentStats(d) {
  const el = $('#sentiment-stats');
  if (!el) return;
  const up = d.limitup || {}, down = d.limitdown || {}, tem = d.sentiment || {};
  const ladder = up.ladder || {};
  const tiers = Object.keys(ladder).length;
  const rows = [
    ['涨停家数', up.count ?? '—', '#ff9a91'],
    ['跌停家数', down.count ?? '—', '#6ee7a8'],
    ['最高连板', (up.max_board ?? 0) + ' 板', '#f7c46a'],
    ['连板档数', tiers + ' 档', '#7ed8ef'],
    ['退潮阈值', (tem.panic_threshold ?? '—') + ' 家', '#b6c4d6'],
  ];
  el.innerHTML = `
    <div class="panel-head"><div><h2>市场情绪切片</h2><p>方案第五层：连板高度 · 跌停家数 · 涨跌比</p></div></div>
    ${rows.map(([lab, val, c]) => `
      <div class="stat-row"><span class="sr-lab">${esc(lab)}</span>
        <span class="sr-val" style="color:${c}">${esc(val)}</span></div>`).join('')}
    <div class="stat-note">${esc(tem.status || '—')}</div>`;
}

/* ------------------------------------------------------------------ */
/* 通用：连板梯队                                                       */
/* ------------------------------------------------------------------ */

function renderLadder(ladder, el) {
  if (!el) return;
  const entries = Object.keys(ladder || {})
    .map((k) => [Number(k), ladder[k]])
    .filter((e) => e[0] > 0)
    .sort((a, b) => b[0] - a[0]);
  if (!entries.length) {
    el.innerHTML = '<div class="empty">暂无涨停池数据</div>';
    return;
  }
  const max = Math.max(1, ...entries.map((e) => e[1]));
  el.innerHTML = entries.map(([lv, ct]) => `
    <div class="ladder-row">
      <span class="lv">${lv} 板</span>
      <span class="bar"><span class="fill" style="width:${(ct / max * 100).toFixed(1)}%"></span></span>
      <span class="ct">${ct} 家</span>
    </div>`).join('');
}

/* ------------------------------------------------------------------ */
/* 第一层：热点 / 板块 / 涨停池                                          */
/* ------------------------------------------------------------------ */

async function loadHot(force) {
  if (!force && !stale('hot', 60000) && state.hot) return renderHot(state.hot);
  const grid = $('#hot-grid');
  if (grid && !state.hot) grid.innerHTML = '<div class="skeleton">正在聚合涨停池与板块榜…</div>';
  try {
    const d = await api('/api/hot?days=5');
    if (!d.ok) throw new Error(d.error || '接口异常');
    state.hot = d;
    mark('hot');
    renderHot(d);
  } catch (e) {
    if (grid) grid.innerHTML = `<div class="empty">热点数据获取失败：${esc(e.message)}</div>`;
  }
}

function renderHot(d) {
  const tag = $('#hot-date');
  if (tag) tag.textContent = dateStr(d.date) + '　' + (d.updated || '');

  const grid = $('#hot-grid');
  const hottest = d.hottest || [];
  grid.innerHTML = hottest.length ? hottest.map((h) => {
    const max = Math.max(1, ...hottest.map((x) => x.limitup_count));
    const chips = (h.stocks || []).slice(0, 8).map((s) =>
      `<span class="chip ${s.boards >= 3 ? 'hi' : ''}" data-code="${esc(s.code)}"
        title="${esc(s.name)} ${s.boards} 连板">${esc(s.name)}${s.boards > 1 ? ' ×' + s.boards : ''}</span>`).join('');
    const more = (h.stocks || []).length > 8 ? `<span class="chip">+${h.stocks.length - 8}</span>` : '';
    return `<div class="hot-card">
      <div class="hc-top">
        <span class="hc-name">${esc(h.sector)}</span>
        <span class="hc-count">${h.limitup_count}<small>家涨停</small></span>
      </div>
      <div class="hc-meta">
        <span>最高 ${h.max_boards} 板</span>
        <span>封单 ${fmt(h.seal_fund, 1)} 亿</span>
        <span>近 5 日 ${h.recent_limitups ?? h.limitup_count} 次</span>
      </div>
      <div class="hc-stocks">${chips}${more}</div>
      <div class="bar-intensity" style="width:${(h.limitup_count / max * 100).toFixed(1)}%"></div>
    </div>`;
  }).join('') : '<div class="empty">今日涨停池暂无数据</div>';

  renderBoardTable($('#tbl-concept'), d.concept);
  renderBoardTable($('#tbl-industry'), d.industry);
  renderHotMini(d);
  towerKpi(1, `热点 ${hottest.length} 个 · 龙头 ${hottest[0] ? hottest[0].sector : '—'}`);
}

function renderBoardTable(table, rows) {
  if (!table) return;
  rows = rows || [];
  const head = `<thead><tr>
      <th>板块</th><th class="num">家数</th><th class="num">涨跌幅</th>
      <th class="num">成交额</th><th>领涨股</th><th class="num">领涨涨幅</th>
    </tr></thead>`;
  if (!rows.length) {
    table.innerHTML = head + '<tbody><tr><td colspan="6" class="flat">暂无数据</td></tr></tbody>';
    return;
  }
  table.innerHTML = head + '<tbody>' + rows.map((r) => `
    <tr class="clickable" data-code="${esc(r.leader_code)}">
      <td>${esc(r.name)}</td>
      <td class="num">${r.count}</td>
      <td class="num">${pctCell(r.pct)}</td>
      <td class="num">${money(r.amount)}</td>
      <td>${esc(r.leader)}<span class="mono flat"> ${esc(r.leader_code)}</span></td>
      <td class="num">${pctCell(r.leader_pct)}</td>
    </tr>`).join('') + '</tbody>';
}

function renderHotMini(d) {
  const el = $('#hot-mini');
  if (!el) return;
  const rows = (d.hottest || []).slice(0, 6);
  el.innerHTML = rows.length ? rows.map((h, i) => `
    <div class="hm-row" data-goto="1">
      <span class="hm-rank">${String(i + 1).padStart(2, '0')}</span>
      <span>
        <span class="hm-name">${esc(h.sector)}</span><br>
        <span class="hm-sub">最高 ${h.max_boards} 板 · 封单 ${fmt(h.seal_fund, 1)} 亿</span>
      </span>
      <span class="hm-val pos">${h.limitup_count}<small style="font-size:10px;color:var(--dim)"> 家</small></span>
    </div>`).join('') : '<div class="empty">暂无热点数据</div>';
}

async function loadLimitup(force) {
  if (!force && !stale('limitup', 60000) && state.limitup) return renderLimitup(state.limitup);
  try {
    const d = await api('/api/limitup');
    if (!d.ok) throw new Error(d.error || '接口异常');
    state.limitup = d;
    mark('limitup');
    renderLimitup(d);
  } catch (e) {
    const t = $('#tbl-limitup');
    if (t) t.innerHTML = `<tbody><tr><td class="flat">涨停池获取失败：${esc(e.message)}</td></tr></tbody>`;
  }
}

function renderLimitup(d) {
  renderLadder(d.ladder, $('#ladder'));
  const tag = $('#ladder-tag');
  if (tag) tag.textContent = `${dateStr(d.date)} · ${d.count} 家 · 最高 ${d.max_board} 板`;

  const table = $('#tbl-limitup');
  const items = d.items || [];
  const head = `<thead><tr>
      <th>代码</th><th>名称</th><th class="num">现价</th><th class="num">涨幅</th>
      <th class="num">连板</th><th>首封</th><th class="num">封单</th>
      <th class="num">换手</th><th class="num">流通市值</th><th>板块</th>
    </tr></thead>`;
  table.innerHTML = head + '<tbody>' + (items.length ? items.map((r) => `
    <tr class="clickable" data-code="${esc(r.code)}">
      <td class="mono">${esc(r.code)}</td>
      <td>${esc(r.name)}</td>
      <td class="num">${fmt(r.price)}</td>
      <td class="num">${pctCell(r.pct)}</td>
      <td class="num" style="color:#f7c46a">${r.boards}</td>
      <td class="mono flat">${esc(r.first_seal || '—')}</td>
      <td class="num">${money(r.seal_fund)}</td>
      <td class="num">${fmt(r.turnover, 2)}%</td>
      <td class="num">${fmt(r.float_cap, 1)}</td>
      <td class="flat">${esc(r.sector || '—')}</td>
    </tr>`).join('') : '<tr><td colspan="10" class="flat">暂无涨停数据</td></tr>') + '</tbody>';
}

/* ------------------------------------------------------------------ */
/* 第二层：龙回头扫描                                                   */
/* ------------------------------------------------------------------ */

async function runScan() {
  if (state.scanning) return;
  state.scanning = true;
  const btn = $('#btn-scan');
  busy(btn, true, '⏳ 扫描中…');
  $('#scan-result').innerHTML = '<div class="skeleton">正在并发抓取近 N 日涨停池与 K 线，约需 3~6 秒…</div>';
  $('#scan-tag').textContent = '扫描中…';
  const limit = Math.max(10, Math.min(80, Number($('#scan-limit').value) || 40));
  const days = Math.max(3, Math.min(15, Number($('#scan-days').value) || 10));
  try {
    const d = await api(`/api/scan?limit=${limit}&days=${days}`);
    if (!d.ok) throw new Error(d.error || '接口异常');
    state.scan = d;
    renderScan(d);
    if (d.warnings && d.warnings.length) toast(d.warnings.join('；'), true);
    else {
      const a = d.archive || {};
      const arch = a.ok && !a.skipped
        ? ` · 档案 +${a.added || 0} / 更新 ${a.updated || 0}`
        : (a.skipped ? '' : '');
      toast(`扫描完成：命中 ${d.count} 只（耗时 ${d.elapsed}s）${arch}`);
    }
    if (state.archive) { state.archiveAt = 0; if (state.page === 6) loadArchive(true); }
  } catch (e) {
    $('#scan-result').innerHTML = `<div class="empty">扫描失败：${esc(e.message)}</div>`;
    $('#scan-tag').textContent = '扫描失败';
    toast('扫描失败：' + e.message, true);
  } finally {
    state.scanning = false;
    busy(btn, false);
  }
}

function renderScan(d) {
  const tag = $('#scan-tag');
  tag.className = 'tag ' + (d.count ? 'up' : 'muted');
  tag.textContent = `命中 ${d.count} · 扫描 ${d.scanned} · ${d.elapsed}s`;

  const note = $('#scan-note');
  if (note) note.innerHTML = `扫描对象：近 ${(d.settings && d.settings.pullbackDaysMax) || 10} 日窗口内涨停池中的连板股 + 今日涨停 + 自选池　|　候选 ${d.total_candidates} 只，实际评分 ${d.scanned} 只。` +
    (d.archive && d.archive.ok && !d.archive.skipped
      ? `　|　已自动封存到 <b style="color:#f7c46a">${esc(d.archive.date)}</b> 档案（+${d.archive.added} / 更新 ${d.archive.updated}）。`
      : '');

  const items = d.items || [];
  const others = d.others || [];
  const box = $('#scan-result');

  if (!items.length && !others.length) {
    box.innerHTML = '<div class="empty">未取得有效评分结果，请稍后重试。</div>';
    return;
  }

  const head = `<thead><tr>
      <th>评分</th><th>代码</th><th>名称</th><th class="num">现价</th><th class="num">涨幅</th>
      <th class="num">连板</th><th class="num">回调日</th><th class="num">回调幅</th>
      <th class="num">缩量比</th><th>买点</th><th>板块</th>
    </tr></thead>`;

  const rowOf = (v) => {
    const buy = v.right_side ? '<span class="tag up">激进</span>'
      : (v.stable ? '<span class="tag down">稳健</span>' : '<span class="tag muted">观察</span>');
    return `<tr class="clickable" data-code="${esc(v.code)}">
      <td>${scorePill(v.score)}</td>
      <td class="mono">${esc(v.code)}</td>
      <td>${esc(v.name)}</td>
      <td class="num">${fmt(v.price)}</td>
      <td class="num">${pctCell(v.pct)}</td>
      <td class="num" style="color:#f7c46a">${v.boards}</td>
      <td class="num">${v.pullback_days}</td>
      <td class="num">${fmt(v.pullback_pct, 1)}%</td>
      <td class="num">${v.shrink_ratio === null || v.shrink_ratio === undefined ? '—' : (v.shrink_ratio * 100).toFixed(0) + '%'}</td>
      <td>${buy}</td>
      <td class="flat">${esc(v.sector || '—')}</td>
    </tr>`;
  };

  let html = '<div class="table-wrap"><table class="tbl">' + head + '<tbody>' +
    (items.length ? items.map(rowOf).join('') : '<tr><td colspan="11" class="flat">本次没有满足「有连板基础」的标的</td></tr>') +
    '</tbody></table></div>';

  if (others.length) {
    html += `<div class="divider"></div>
      <div class="panel-head"><div><h2 style="font-size:13.5px">未通过第一层「非龙头不炒」的观察项</h2>
      <p>近期无连板基础，仅列形态评分供参考，按方案一律不介入</p></div></div>
      <div class="table-wrap"><table class="tbl">${head}<tbody>${others.map(rowOf).join('')}</tbody></table></div>`;
  }

  box.innerHTML = html;

  const best = items[0];
  towerKpi(2, best ? `A/B 级 ${items.filter((v) => v.score >= 65).length} 只 · 最高 ${best.score} 分` : '尚无命中');

  renderScanMini(items);

  // 保留用户已选中的标的；只有它已经不在榜上时才自动切到最高分那只。
  const stillListed = items.concat(others).some((v) => v.code === state.selected);
  if (best && !stillListed) selectStock(best.code);
}

function renderScanMini(items) {
  const el = $('#scan-mini');
  if (!el) return;
  items = items || [];
  if (!items.length) {
    el.innerHTML = `<div class="empty">尚未扫描。<br><br>
      <button class="btn tiny ghost" data-goto="2">前往第二层扫描</button></div>`;
    return;
  }
  el.innerHTML = items.slice(0, 6).map((v, i) => `
    <div class="hm-row" data-code="${esc(v.code)}">
      <span class="hm-rank">${String(i + 1).padStart(2, '0')}</span>
      <span>
        <span class="hm-name">${esc(v.name)}</span> <span class="hm-sub">${esc(v.code)}</span><br>
        <span class="hm-sub">${v.boards} 连板 · 回调 ${v.pullback_days} 日 ${fmt(v.pullback_pct, 1)}%
          ${v.right_side ? '· 放量起爆' : (v.stable ? '· 缩量止跌' : '')}</span>
      </span>
      <span class="hm-val">${scorePill(v.score)}</span>
    </div>`).join('');
}

/* ---------- 个股详情 ---------- */

async function selectStock(code) {
  code = String(code || '').trim();
  if (!code) return;
  state.selected = code;
  if (state.page !== 2) switchPage(2);
  const box = $('#stock-detail');
  box.innerHTML = `<div class="skeleton">正在获取 ${esc(code)} 的实时行情与 K 线…</div>`;
  try {
    const v = await api('/api/stock?code=' + encodeURIComponent(code));
    if (!v.ok) {
      box.innerHTML = `<div class="empty">${esc(v.error || '未能获取该股票行情')}</div>`;
      return;
    }
    renderStockDetail(v);
  } catch (e) {
    box.innerHTML = `<div class="empty">获取失败：${esc(e.message)}</div>`;
  }
}

function renderStockDetail(v) {
  const g = gradeOf(v.score);
  const box = $('#stock-detail');

  /* 评分明细 */
  const scoreList = (v.details || []).map((d) => {
    const ratio = d.max ? d.score / d.max : 0;
    const mark = ratio >= 0.999 ? 'full-mark' : (d.score > 0 ? 'part-mark' : 'zero-mark');
    return `<div class="score-item">
      <div class="si-top">
        <b>${esc(d.key)}</b><span>${esc(d.label)}</span>
        <span class="si-val">${d.score} / ${d.max}</span>
      </div>
      <div class="si-bar"><div class="si-fill ${mark}" style="width:${(ratio * 100).toFixed(0)}%"></div></div>
      <div class="si-note">${esc(d.note)}</div>
    </div>`;
  }).join('');

  /* 关键数据 */
  const L = v.levels || {};
  const kv = [
    ['所属板块', esc(v.board || '—')],
    ['连板高度', `${v.boards} 板`],
    ['回调天数', `${v.pullback_days} 日`],
    ['回调幅度', `${fmt(v.pullback_pct, 1)}%`],
    ['缩量比', v.shrink_ratio === null || v.shrink_ratio === undefined ? '—' : (v.shrink_ratio * 100).toFixed(0) + '% (回调均量/拉升天量)'],
    ['MA5 / MA10 / MA20', `${fmt(v.ma5)} / ${fmt(v.ma10)} / ${fmt(v.ma20)}`],
    ['流通市值', `${fmt(v.float_cap, 1)} 亿`],
    ['今日换手 / 量比', `${fmt(v.turnover, 2)}% / ${fmt(v.vol_ratio, 2)}`],
    ['洗盘箱体上沿', `${fmt(v.box_top)}`],
    ['拉升期最高价', `${fmt(v.rally_high)}`],
  ].map(([k, val]) => `<dt>${k}</dt><dd>${val}</dd>`).join('');

  /* 买点与仓位 */
  const plan = v.plan || {};
  const bp = `
    <div class="buypoints">
      <div class="bp"><div class="bp-lab">稳健买点（缩量回踩均线）</div><div class="bp-val">${fmt(L.steady_buy)}</div></div>
      <div class="bp"><div class="bp-lab">激进买点（放量破箱体）</div><div class="bp-val">${fmt(L.box_top)}</div></div>
      <div class="bp sl"><div class="bp-lab">止损价（-${fmt(state.settings.stopLossPct, 0)}%）</div><div class="bp-val">${fmt(L.stop_loss)}</div></div>
      <div class="bp tp"><div class="bp-lab">一档止盈 / 二档止盈</div>
        <div class="bp-val">${fmt(L.take_profit_half)} / ${fmt(L.take_profit_full)}</div></div>
    </div>`;

  const planHtml = plan.ok ? `
    <div class="calc-out" style="margin-top:12px">
      <div class="calc-line"><span>单股仓位上限（${fmt(state.settings.maxPositionPct, 0)}%）</span><b>${fmt(plan.max_cash, 0)} 元</b></div>
      <div class="calc-line hl"><span>首笔观察哨</span><b>${plan.starter_qty} 股 / ${fmt(plan.starter_amount, 0)} 元</b></div>
      <div class="calc-line"><span>右侧确认后补足</span><b>${plan.add_qty} 股</b></div>
      <div class="calc-line"><span>满仓上限</span><b>${plan.full_qty} 股 / ${fmt(plan.full_amount, 0)} 元</b></div>
    </div>` : `<div class="calc-out" style="margin-top:12px"><div class="calc-line warn"><span>仓位测算</span><b>${esc(plan.reason || '资金不足一手')}</b></div></div>`;

  const verdictCls = v.right_side ? 'buy' : (v.stable ? 'stable' : '');
  const verdictTag = v.right_side ? '激进买点已触发' : (v.stable ? '稳健买点已触发' : '右侧尚未确认');

  box.innerHTML = `
    <div class="panel-head">
      <div>
        <h2>${esc(v.name)} <span class="mono flat" style="font-size:13px">${esc(v.code)}</span></h2>
        <p>${esc(v.board || '')}　现价 <b class="${tone(v.pct)}">${fmt(v.price)}</b>
           　${pctCell(v.pct)}　${esc(v.grade)}</p>
      </div>
      <div style="text-align:right">
        ${scorePill(v.score)}
        <div class="muted" style="margin-top:6px">${esc(verdictTag)}</div>
      </div>
    </div>

    <div class="detail-grid">
      <div>
        <canvas class="chart" id="stock-chart"></canvas>
        <div class="verdict ${verdictCls}">${esc(v.advice || '')}</div>
        ${bp}
        ${planHtml}
      </div>
      <div>
        <div class="score-list">${scoreList}</div>
        <div class="divider"></div>
        <dl class="kv">${kv}</dl>
        <div class="row-actions" style="margin-top:14px">
          <button class="btn tiny ghost" data-watch="${esc(v.code)}">☆ 加入自选</button>
          <button class="btn tiny ghost" data-pos="${esc(v.code)}">＋ 按现价建仓</button>
        </div>
      </div>
    </div>`;

  state.chart = { bars: v.bars || [], boxTop: v.box_top, rallyHigh: v.rally_high };
  requestAnimationFrame(() => drawChart($('#stock-chart'), state.chart));
  towerKpi(2, `${v.name} ${v.score} 分`);
}

/* ---------- 手绘 K 线 ---------- */

function drawChart(canvas, data) {
  if (!canvas || !data) return;
  const bars = data.bars || [];
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 560;
  const h = canvas.clientHeight || 210;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (bars.length < 2) {
    ctx.fillStyle = '#6f83a3';
    ctx.font = '12px sans-serif';
    ctx.fillText('无 K 线数据', 12, h / 2);
    return;
  }

  const padL = 8, padR = 46, padT = 10;
  const priceH = 126, volH = 38, gap = 12, axisH = 14;
  const plotW = w - padL - padR;
  const priceTop = padT, priceBot = padT + priceH;
  const volTop = priceBot + gap, volBot = volTop + volH;

  let lo = Infinity, hi = -Infinity;
  bars.forEach((b) => {
    lo = Math.min(lo, b.l, b.ma5 || Infinity, b.ma10 || Infinity, b.ma20 || Infinity);
    hi = Math.max(hi, b.h, b.ma5 || -Infinity, b.ma10 || -Infinity, b.ma20 || -Infinity);
  });
  if (data.boxTop) hi = Math.max(hi, data.boxTop);
  if (data.rallyHigh) hi = Math.max(hi, data.rallyHigh);
  const span = (hi - lo) || 1;
  hi += span * 0.06; lo -= span * 0.06;

  const vmax = Math.max(1, ...bars.map((b) => b.v || 0));
  const step = plotW / bars.length;
  const cw = Math.max(2.5, step * 0.6);

  const X = (i) => padL + step * (i + 0.5);
  const Y = (p) => priceBot - (p - lo) / (hi - lo) * priceH;
  const VY = (v) => volBot - (v / vmax) * volH;

  /* 网格与右侧价格刻度 */
  ctx.strokeStyle = 'rgba(126,160,214,.12)';
  ctx.fillStyle = '#6f83a3';
  ctx.font = '9.5px monospace';
  ctx.lineWidth = 1;
  for (let k = 0; k <= 3; k++) {
    const p = lo + (hi - lo) * (k / 3);
    const y = Math.round(Y(p)) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.fillText(p.toFixed(2), padL + plotW + 6, y + 3);
  }

  /* 洗盘箱体上沿 */
  if (data.boxTop) {
    const y = Y(data.boxTop);
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = 'rgba(245,165,36,.75)';
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.restore();
    ctx.fillStyle = 'rgba(245,165,36,.9)';
    ctx.fillText('箱体上沿', padL + 4, y - 4);
  }
  /* 拉升期最高价 */
  if (data.rallyHigh) {
    const y = Y(data.rallyHigh);
    ctx.save();
    ctx.setLineDash([2, 5]);
    ctx.strokeStyle = 'rgba(240,68,56,.6)';
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.restore();
    ctx.fillStyle = 'rgba(240,68,56,.85)';
    ctx.fillText('前高', padL + 4, y - 4);
  }

  /* K 线 */
  bars.forEach((b, i) => {
    const up = b.c >= b.o;
    const color = up ? '#f04438' : '#22c55e';
    const x = X(i);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, Y(b.h));
    ctx.lineTo(x, Y(b.l));
    ctx.stroke();
    const yO = Y(b.o), yC = Y(b.c);
    const top = Math.min(yO, yC);
    const hgt = Math.max(1, Math.abs(yC - yO));
    ctx.fillRect(x - cw / 2, top, cw, hgt);
  });

  /* 均线 */
  const lines = [['ma5', '#f5a524'], ['ma10', '#22c3e6'], ['ma20', '#a78bfa']];
  lines.forEach(([key, color]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    let started = false;
    bars.forEach((b, i) => {
      const val = b[key];
      if (val === null || val === undefined) return;
      const x = X(i), y = Y(val);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    });
    ctx.stroke();
  });

  /* 成交量 */
  bars.forEach((b, i) => {
    const up = b.c >= b.o;
    ctx.fillStyle = up ? 'rgba(240,68,56,.62)' : 'rgba(34,197,94,.62)';
    const y = VY(b.v || 0);
    ctx.fillRect(X(i) - cw / 2, y, cw, volBot - y);
  });
  ctx.strokeStyle = 'rgba(126,160,214,.2)';
  ctx.beginPath(); ctx.moveTo(padL, volBot + 0.5); ctx.lineTo(padL + plotW, volBot + 0.5); ctx.stroke();

  /* 日期刻度 */
  ctx.fillStyle = '#6f83a3';
  ctx.font = '9px monospace';
  const ticks = Math.min(4, bars.length);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round((bars.length - 1) * k / Math.max(1, ticks - 1));
    const label = String(bars[i].d || '').slice(5);
    const x = X(i);
    ctx.textAlign = k === 0 ? 'left' : (k === ticks - 1 ? 'right' : 'center');
    ctx.fillText(label, Math.max(padL, Math.min(padL + plotW, x)), volBot + axisH);
  }
  ctx.textAlign = 'left';

  /* 图例 */
  ctx.font = '9.5px monospace';
  ctx.fillStyle = '#f5a524'; ctx.fillText('MA5', padL + 4, padT + 9);
  ctx.fillStyle = '#22c3e6'; ctx.fillText('MA10', padL + 38, padT + 9);
  ctx.fillStyle = '#a78bfa'; ctx.fillText('MA20', padL + 76, padT + 9);
}

/* ------------------------------------------------------------------ */
/* 悬停预览：日K + 分时                                                 */
/* ------------------------------------------------------------------ */

const HOVER_DELAY = 180;          // 停留多久才弹出，避免扫过时乱闪

const _hvCache = new Map();       // code -> {preview, minute}
let _hvTimer = null;
let _hvAnchor = null;             // 当前悬停的 [data-code] 元素
let _hvCode = null;
let _hvOn = false;
let _hvX = 0, _hvY = 0;

/** 把 HHMM 映射到分时横轴槽位：09:30=0 … 11:30=120，13:00=121 … 15:00=241。 */
function minuteSlot(t) {
  const hh = Number(String(t).slice(0, 2));
  const mm = Number(String(t).slice(2, 4));
  if (!isFinite(hh) || !isFinite(mm)) return 0;
  const mins = hh * 60 + mm;
  return mins <= 11 * 60 + 30 ? mins - (9 * 60 + 30) : 121 + (mins - 13 * 60);
}

function hideHover() {
  clearTimeout(_hvTimer);
  _hvTimer = null;
  _hvAnchor = null;
  _hvCode = null;
  _hvOn = false;
  const box = $('#hovercard');
  if (!box) return;
  box.classList.remove('show');
  box.hidden = true;
}

function positionHover() {
  const box = $('#hovercard');
  if (!box || box.hidden) return;
  const w = box.offsetWidth || 392;
  const h = box.offsetHeight || 340;
  const pad = 14;
  let left = _hvX + 20;
  let top = _hvY + 18;
  if (left + w > window.innerWidth - pad) left = _hvX - w - 20;
  if (left < pad) left = Math.max(pad, window.innerWidth - w - pad);
  if (top + h > window.innerHeight - pad) top = _hvY - h - 18;
  if (top < pad) top = pad;
  box.style.left = Math.round(left) + 'px';
  box.style.top = Math.round(top) + 'px';
}

function showHover(code) {
  const box = $('#hovercard');
  if (!box || !code) return;
  _hvOn = true;
  _hvCode = code;

  const hit = _hvCache.get(code);
  if (hit) { renderHover(hit, code); return; }

  const rec = { preview: null, minute: null };
  _hvCache.set(code, rec);

  box.hidden = false;
  box.innerHTML = `<div class="hv-head"><span class="hv-name">加载中…</span>
      <span class="hv-code">${esc(code)}</span></div>
    <div class="hv-loading">正在获取日K与分时…</div>`;
  requestAnimationFrame(() => { box.classList.add('show'); positionHover(); });

  const bump = () => { if (_hvOn && _hvCode === code) renderHover(rec, code); };
  // 两个请求分开走：日K通常已被扫描缓存，先出图；分时随后补上。
  api('/api/preview?code=' + encodeURIComponent(code))
    .then((d) => {
      if (d && d.ok) { rec.preview = d; bump(); }
      else if (!rec.minute) { _hvCache.delete(code); if (_hvCode === code) hideHover(); }
    })
    .catch(() => { if (!rec.minute) { _hvCache.delete(code); if (_hvCode === code) hideHover(); } });
  api('/api/minute?code=' + encodeURIComponent(code))
    .then((d) => { if (d && d.ok) { rec.minute = d; bump(); } })
    .catch(() => { });
}

function renderHover(rec, code) {
  const box = $('#hovercard');
  if (!box) return;
  const p = rec.preview;
  const m = rec.minute;
  const cls = p ? tone(p.pct) : 'flat';

  let html = '';
  if (p) {
    html += `<div class="hv-head">
        <span class="hv-name">${esc(p.name)}</span>
        <span class="hv-code">${esc(p.code)}</span>
        <span class="hv-price ${cls}">${fmt(p.price)}</span>
        <span class="hv-pct ${cls}">${sgn(p.pct)}%</span>
      </div>
      <div class="hv-meta">
        <span>换手 ${fmt(p.turnover, 2)}%</span>
        <span>量比 ${fmt(p.vol_ratio, 2)}</span>
        <span>流通 ${fmt(p.float_cap, 0)} 亿</span>
        <span class="hv-hint">点击看完整评分 →</span>
      </div>`;
  } else {
    html += `<div class="hv-head"><span class="hv-name">加载中…</span>
      <span class="hv-code">${esc(code)}</span></div>`;
  }

  if (p && p.bars && p.bars.length) {
    html += `<div class="hv-sec"><div class="hv-sec-t">日K线 <b>近 ${p.bars.length} 个交易日</b></div>
      <canvas class="hv-canvas hv-kline" id="hv-kline"></canvas></div>`;
  }

  const pts = (m && m.points) || [];
  const preClose = (m && m.pre_close) || (p && p.pre_close) || 0;
  const lineColor = (pts.length && preClose > 0 && pts[pts.length - 1].p < preClose) ? '#22c55e' : '#f04438';

  html += `<div class="hv-sec"><div class="hv-sec-t">分时 <b>${m && m.date ? dateStr(m.date) : '加载中…'}</b></div>`;
  if (pts.length) {
    html += `<canvas class="hv-canvas hv-minute" id="hv-minute"></canvas>
      <div class="hv-legend">
        <span><i style="background:${lineColor}"></i>价格</span>
        <span><i style="background:#f5a524"></i>均价</span>
        <span><i style="background:#94a3b8"></i>昨收</span>
      </div>`;
  } else {
    html += '<div class="hv-loading">分时数据加载中…</div>';
  }
  html += '</div>';

  box.hidden = false;
  box.innerHTML = html;
  box.classList.add('show');

  if (p && p.bars && p.bars.length) drawHoverKline($('#hv-kline'), p.bars);
  if (pts.length) drawHoverMinute($('#hv-minute'), pts, preClose);
  positionHover();
}

/** 悬停卡里的迷你日K：蜡烛 + MA5 / MA10 + 右侧价格。 */
function drawHoverKline(canvas, bars) {
  if (!canvas || !bars || bars.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 392;
  const h = canvas.clientHeight || 134;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 7, padR = 42, padT = 17, padB = 13;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  let lo = Infinity, hi = -Infinity;
  bars.forEach((b) => {
    lo = Math.min(lo, b.l, b.ma5 || Infinity, b.ma10 || Infinity);
    hi = Math.max(hi, b.h, b.ma5 || -Infinity, b.ma10 || -Infinity);
  });
  const span = (hi - lo) || 1;
  hi += span * 0.05;
  lo -= span * 0.05;

  const step = plotW / bars.length;
  const cw = Math.max(1.5, step * 0.62);
  const X = (i) => padL + step * (i + 0.5);
  const Y = (v) => padT + plotH - (v - lo) / (hi - lo) * plotH;

  ctx.font = '9px monospace';
  ctx.strokeStyle = 'rgba(126,160,214,.10)';
  ctx.fillStyle = '#6f83a3';
  for (let k = 0; k <= 2; k++) {
    const v = lo + (hi - lo) * (k / 2);
    const y = Math.round(Y(v)) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    ctx.fillText(v.toFixed(2), padL + plotW + 5, y + 3);
  }

  bars.forEach((b, i) => {
    const up = b.c >= b.o;
    const color = up ? '#f04438' : '#22c55e';
    const x = X(i);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, Y(b.h)); ctx.lineTo(x, Y(b.l)); ctx.stroke();
    const yO = Y(b.o), yC = Y(b.c);
    ctx.fillRect(x - cw / 2, Math.min(yO, yC), cw, Math.max(1, Math.abs(yC - yO)));
  });

  [['ma5', '#f5a524'], ['ma10', '#22c3e6']].forEach(([k, color]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    let started = false;
    bars.forEach((b, i) => {
      const v = b[k];
      if (v === null || v === undefined) return;
      const x = X(i), y = Y(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    });
    ctx.stroke();
  });

  ctx.fillStyle = '#6f83a3';
  ctx.textAlign = 'left';
  ctx.fillText(String(bars[0].d || '').slice(5), padL, h - 3);
  ctx.textAlign = 'right';
  ctx.fillText(String(bars[bars.length - 1].d || '').slice(5), padL + plotW, h - 3);
  ctx.textAlign = 'left';
}

/** 悬停卡里的分时图：价格线 + 均价线 + 昨收基准，横轴按交易分钟槽位对齐。 */
function drawHoverMinute(canvas, points, preClose) {
  if (!canvas || !points || points.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 392;
  const h = canvas.clientHeight || 114;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 38, padR = 44, padT = 18, padB = 14;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  if (!preClose || preClose <= 0) preClose = points[0].p;
  let dev = 0;
  points.forEach((p) => {
    dev = Math.max(dev, Math.abs(p.p - preClose), Math.abs((p.avg || p.p) - preClose));
  });
  dev = dev * 1.12 || preClose * 0.01;
  const hi = preClose + dev;
  const lo = preClose - dev;

  const SLOTS = 241;                                  // 09:30 … 15:00
  const X = (t) => padL + plotW * (minuteSlot(t) / SLOTS);
  const Y = (v) => padT + plotH - (v - lo) / (hi - lo) * plotH;
  const yBase = padT + plotH;

  ctx.font = '9px monospace';
  ctx.strokeStyle = 'rgba(126,160,214,.11)';
  [hi, preClose, lo].forEach((v) => {
    const y = Math.round(Y(v)) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
  });
  // 左侧百分比刻度
  ctx.fillStyle = '#6f83a3';
  ctx.textAlign = 'left';
  ctx.fillText(sgn((hi / preClose - 1) * 100), 3, Y(hi) + 3);
  ctx.fillText('0.00%', 3, Y(preClose) + 3);
  ctx.fillText(sgn((lo / preClose - 1) * 100), 3, Y(lo) + 3);
  // 右侧价格刻度
  ctx.fillText(hi.toFixed(2), padL + plotW + 5, Y(hi) + 3);
  ctx.fillText(preClose.toFixed(2), padL + plotW + 5, Y(preClose) + 3);
  ctx.fillText(lo.toFixed(2), padL + plotW + 5, Y(lo) + 3);

  // 午间休市分隔线
  const xMid = padL + plotW * (120.5 / SLOTS);
  ctx.strokeStyle = 'rgba(126,160,214,.18)';
  ctx.beginPath(); ctx.moveTo(xMid, padT); ctx.lineTo(xMid, yBase); ctx.stroke();

  const up = points[points.length - 1].p >= preClose;
  const rgb = up ? '240,68,56' : '34,197,94';
  const lineColor = up ? '#f04438' : '#22c55e';

  // 价格线填充
  const grad = ctx.createLinearGradient(0, padT, 0, yBase);
  grad.addColorStop(0, `rgba(${rgb},.26)`);
  grad.addColorStop(1, `rgba(${rgb},0)`);
  ctx.beginPath();
  ctx.moveTo(X(points[0].t), Y(points[0].p));
  points.forEach((p) => ctx.lineTo(X(p.t), Y(p.p)));
  ctx.lineTo(X(points[points.length - 1].t), yBase);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // 均价线
  ctx.strokeStyle = '#f5a524';
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = X(p.t), y = Y(p.avg || p.p);
    if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.stroke();

  // 价格线
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = X(p.t), y = Y(p.p);
    if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.stroke();

  // 时间轴
  ctx.fillStyle = '#6f83a3';
  ctx.textAlign = 'left';
  ctx.fillText('09:30', padL, h - 3);
  ctx.textAlign = 'center';
  ctx.fillText('11:30/13:00', padL + plotW / 2, h - 3);
  ctx.textAlign = 'right';
  ctx.fillText('15:00', padL + plotW, h - 3);
  ctx.textAlign = 'left';
}

/* ------------------------------------------------------------------ */
/* 第三层：仓位管理                                                     */
/* ------------------------------------------------------------------ */

function readCalcInputs() {
  return {
    capital: Number($('#calc-capital').value) || 100000,
    maxpct: Number($('#calc-maxpct').value) || 50,
    starter: Number($('#calc-starter').value) || 30,
    price: Number($('#calc-price').value) || 0,
  };
}

function renderCalc() {
  const c = readCalcInputs();
  const budget = c.capital * c.maxpct / 100;
  const firstCash = budget * c.starter / 100;
  const price = c.price;
  const firstQty = price > 0 ? Math.floor(firstCash / price / 100) * 100 : 0;
  const fullQty = price > 0 ? Math.floor(budget / price / 100) * 100 : 0;
  const addQty = Math.max(0, fullQty - firstQty);
  const sleeves = Math.max(1, Number(state.settings.sleeveCount) || 3);
  const perSleeve = c.capital / sleeves;

  const out = $('#calc-out');
  out.innerHTML = `
    <div class="calc-line"><span>短线总资金</span><b>${fmt(c.capital, 0)} 元</b></div>
    <div class="calc-line"><span>资金平分 ${sleeves} 份（每份）</span><b>${fmt(perSleeve, 0)} 元</b></div>
    <div class="calc-line"><span>单股持仓上限 ${fmt(c.maxpct, 0)}%</span><b>${fmt(budget, 0)} 元</b></div>
    <div class="calc-line hl"><span>首笔观察哨 ${fmt(c.starter, 0)}%</span><b>${firstQty} 股 / ${fmt(firstQty * price, 0)} 元</b></div>
    <div class="calc-line"><span>右侧确认后补足</span><b>${addQty} 股 / ${fmt(addQty * price, 0)} 元</b></div>
    <div class="calc-line"><span>该股满仓上限</span><b>${fullQty} 股 / ${fmt(fullQty * price, 0)} 元</b></div>
    ${firstQty < 100 ? `<div class="calc-line warn"><span>提示</span><b>资金不足一手观察哨（需 ≥ ${fmt(price * 100, 0)} 元）</b></div>` : ''}`;

  renderChecklist();
}

function renderChecklist() {
  const el = $('#checklist-out');
  if (!el) return;
  const positions = state.store?.positions || [];
  const capital = Number(state.settings.capital) || 100000;
  const maxPct = Number(state.settings.maxPositionPct) || 50;
  const staleDays = Number(state.settings.staleDays) || 3;

  const items = (state.evalResult?.items) || [];
  const values = positions.map((p) => {
    const e = items.find((x) => x.code === String(p.code)) || {};
    return (num(e.price) || 0) * (Number(p.quantity) || 0);
  });
  const total = values.reduce((a, b) => a + b, 0);
  const maxVal = values.length ? Math.max(...values) : 0;
  const maxShare = capital > 0 ? maxVal / capital * 100 : 0;
  const investShare = capital > 0 ? total / capital * 100 : 0;
  const sleeves = Math.max(1, Number(state.settings.sleeveCount) || 3);
  const maxHold = items.reduce((a, b) => Math.max(a, num(b.hold_days) || 0), 0);

  const rows = [
    { label: '持仓只数 vs 资金份数', value: `${positions.length} / ${sleeves} 份`, ok: positions.length <= sleeves },
    { label: '单股最大占比（上限 ' + fmt(maxPct, 0) + '%）', value: fmt(maxShare, 1) + '%', ok: maxShare <= maxPct },
    { label: '已投入资金占比', value: fmt(investShare, 1) + '%', ok: investShare <= 100 },
    { label: '最长持有天数（效率退出 ' + staleDays + ' 日）', value: maxHold ? maxHold + ' 日' : '—', ok: maxHold < staleDays + 2 },
  ];

  el.innerHTML = rows.map((r) => `
    <div class="calc-line ${r.ok ? '' : 'warn'}">
      <span>${esc(r.label)}</span>
      <b class="${r.ok ? 'pos' : 'neg'}">${r.ok ? '✓' : '✕'} ${esc(r.value)}</b>
    </div>`).join('');
}

/* ------------------------------------------------------------------ */
/* 持仓 & 第四层纪律                                                    */
/* ------------------------------------------------------------------ */

async function loadPositions() {
  if (!state.store) await loadStore();
  try {
    const d = await postJSON('/api/evaluate', { positions: state.store.positions || [] });
    state.evalResult = d;
    renderPositionsTable(d.items || []);
    renderChecklist();
  } catch (e) {
    toast('持仓诊断失败：' + e.message, true);
  }
}

function renderPositionsTable(items) {
  const table = $('#tbl-positions');
  const positions = state.store?.positions || [];
  const capital = Number(state.settings.capital) || 100000;
  const tag = $('#pos-tag');

  const head = `<thead><tr>
      <th>代码</th><th>名称</th><th class="num">现价</th><th class="num">成本</th>
      <th class="num">股数</th><th class="num">市值</th><th class="num">浮盈</th>
      <th class="num">占比</th><th class="num">天数</th><th>动作</th><th></th>
    </tr></thead>`;

  if (!positions.length) {
    table.innerHTML = head + '<tbody><tr><td colspan="11" class="flat">尚未录入持仓。到第四层「录入持仓」添加，或从第二层个股详情一键建仓。</td></tr></tbody>';
    if (tag) tag.textContent = '无持仓';
    return;
  }

  const rows = positions.map((p) => {
    const it = items.find((x) => x.code === String(p.code)) || {};
    const value = (num(it.price) || 0) * (Number(p.quantity) || 0);
    const share = capital > 0 ? value / capital * 100 : 0;
    return `<tr>
      <td class="mono">${esc(p.code)}</td>
      <td>${esc(it.name || p.name || '—')}</td>
      <td class="num">${fmt(it.price)}</td>
      <td class="num">${fmt(p.cost_price)}</td>
      <td class="num">${p.quantity}</td>
      <td class="num">${fmt(value, 0)}</td>
      <td class="num">${it.profit_pct === null || it.profit_pct === undefined ? '—' : pctCell(it.profit_pct)}</td>
      <td class="num ${share > (Number(state.settings.maxPositionPct) || 50) ? 'neg' : ''}">${fmt(share, 1)}%</td>
      <td class="num">${it.hold_days ?? '—'}</td>
      <td><span class="tag ${it.severity === 'danger' ? 'up' : (it.severity === 'warn' ? 'warn' : 'muted')}">${esc(it.action || '—')}</span></td>
      <td><button class="btn tiny ghost" data-del-pos="${esc(p.code)}">移除</button></td>
    </tr>`;
  }).join('');

  table.innerHTML = head + '<tbody>' + rows + '</tbody>';
  if (tag) {
    const sum = positions.reduce((a, p) => {
      const it = items.find((x) => x.code === String(p.code)) || {};
      return a + (num(it.price) || 0) * (Number(p.quantity) || 0);
    }, 0);
    tag.textContent = `${positions.length} 只 · 市值 ${fmt(sum, 0)} 元 · 占资金 ${fmt(sum / capital * 100, 1)}%`;
  }
}

async function loadDiscipline(force) {
  const box = $('#discipline');
  if (!state.store) await loadStore();
  const positions = state.store.positions || [];
  if (!positions.length) {
    box.innerHTML = '<div class="empty">先在下方录入持仓，再点击「重新诊断」。</div>';
    return;
  }
  if (!box.querySelector('.disc-card')) {
    box.innerHTML = '<div class="skeleton">正在按第四层规则逐条比对实时行情…</div>';
  }
  try {
    const d = await postJSON('/api/evaluate', { positions });
    state.evalResult = d;
    renderDiscipline(d.items || []);
    renderPositionsTable(d.items || []);
    renderChecklist();
  } catch (e) {
    box.innerHTML = `<div class="empty">诊断失败：${esc(e.message)}</div>`;
  }
}

function renderDiscipline(items) {
  const box = $('#discipline');
  if (!items.length) {
    box.innerHTML = '<div class="empty">暂无持仓可诊断。</div>';
    return;
  }
  const sorted = items.slice().sort((a, b) =>
    ((a.priority || 99) === 0 ? 99 : a.priority) - ((b.priority || 99) === 0 ? 99 : b.priority));

  const danger = sorted.filter((x) => x.severity === 'danger').length;
  towerKpi(4, danger ? `${danger} 只需清仓` : `持仓 ${sorted.length} 只 · 纪律正常`);

  box.innerHTML = '<div class="disc-grid">' + sorted.map((it) => {
    const cls = it.severity === 'danger' ? 'danger' : (it.severity === 'warn' ? 'warn' : (it.priority ? 'info' : ''));
    return `<div class="disc-card ${cls}">
      <div class="dc-top">
        <span class="dc-name">${esc(it.name)}</span>
        <span class="dc-code">${esc(it.code)}</span>
        <span class="dc-action">${esc(it.action)}</span>
      </div>
      ${it.rule ? `<div class="dc-rule">命中规则 · ${esc(it.rule)}</div>` : ''}
      <dl class="dc-kv">
        <dt>现价 / 成本</dt><dd>${fmt(it.price)} / ${fmt(it.cost_price)}</dd>
        <dt>浮动盈亏</dt><dd class="${tone(it.profit_pct)}">${it.profit_pct === null ? '—' : sgn(it.profit_pct) + '%（' + fmt(it.profit_amount, 0) + ' 元）'}</dd>
        <dt>当日涨跌</dt><dd class="${tone(it.pct)}">${sgn(it.pct)}%</dd>
        <dt>持有交易日</dt><dd>${it.hold_days} 日</dd>
      </dl>
      <div class="dc-reason">${esc(it.reason)}</div>
    </div>`;
  }).join('') + '</div>';
}

async function addPosition(input) {
  if (!state.store) await loadStore();
  const code = String(input.code || '').trim();
  if (!/^\d{6}$/.test(code)) { toast('请输入 6 位股票代码', true); return false; }
  if (!(num(input.cost_price) > 0)) { toast('请输入有效成本价', true); return false; }
  if (!(Number(input.quantity) > 0)) { toast('请输入持仓股数', true); return false; }

  const quotes = await api('/api/quote?codes=' + code);
  const name = (quotes.items && quotes.items[0] && quotes.items[0].name) || '';

  const positions = (state.store.positions || []).slice();
  const idx = positions.findIndex((p) => String(p.code) === code);
  const rec = {
    code,
    name,
    cost_price: Number(input.cost_price),
    quantity: Math.round(Number(input.quantity)),
    buy_date: input.buy_date || new Date().toISOString().slice(0, 10),
  };
  if (idx >= 0) positions[idx] = rec; else positions.push(rec);

  state.store = await postJSON('/api/store', { positions });
  invalidate('overview');
  toast(`${idx >= 0 ? '已更新' : '已加入'}持仓：${name || code}`);
  return true;
}

async function removePosition(code) {
  if (!state.store) await loadStore();
  const positions = (state.store.positions || []).filter((p) => String(p.code) !== String(code));
  state.store = await postJSON('/api/store', { positions });
  toast('已移除持仓 ' + code);
  renderPositionsTable([]);
  await loadPositions();
  await loadDiscipline();
}

/* ------------------------------------------------------------------ */
/* 第五层：龙头池 / 复盘                                                */
/* ------------------------------------------------------------------ */

async function loadDragons(force) {
  const days = Math.max(3, Math.min(15, Number($('#dragon-days').value) || 10));
  if (!force && !stale('dragons' + days, 300000) && state.dragons && state.dragons._days === days) {
    return renderDragons(state.dragons);
  }
  const box = $('#dragon-pool');
  if (!state.dragons || state.dragons._days !== days) {
    box.innerHTML = '<div class="skeleton">正在聚合近 ' + days + ' 个交易日涨停池…</div>';
  }
  try {
    const d = await api('/api/dragons?days=' + days);
    if (!d.ok) throw new Error(d.error || '接口异常');
    d._days = days;
    state.dragons = d;
    mark('dragons' + days);
    renderDragons(d);
  } catch (e) {
    box.innerHTML = `<div class="empty">龙头池获取失败：${esc(e.message)}</div>`;
  }
}

function renderDragons(d) {
  const box = $('#dragon-pool');
  const items = d.items || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">窗口内没有可用的龙头标的。</div>';
    towerKpi(5, '龙头池为空');
    return;
  }
  towerKpi(5, `龙头池 ${items.length} 只 · 情绪 ${state.overview?.sentiment?.temperature ?? '—'}`);
  box.innerHTML = '<div class="dragon-grid">' + items.slice(0, 60).map((r) => `
    <div class="dragon-card" data-code="${esc(r.code)}">
      <div class="dg-top">
        <span class="dg-name">${esc(r.name)}</span>
        <span class="dg-code">${esc(r.code)}</span>
        <span class="dg-boards">${r.max_boards} 板</span>
      </div>
      <div class="dg-meta">
        <span>窗口涨停 ${r.limitup_days} 次</span>
        <span>${esc(r.board || '')}</span>
        ${r.sectors && r.sectors.length ? `<span>${esc(r.sectors[0])}</span>` : ''}
        ${r.price ? `<span>现价 ${fmt(r.price)}</span>` : ''}
        ${r.pct !== null && r.pct !== undefined ? `<span class="${tone(r.pct)}">${sgn(r.pct)}%</span>` : ''}
        ${r.float_cap ? `<span>流通 ${fmt(r.float_cap, 0)} 亿</span>` : ''}
      </div>
    </div>`).join('') + '</div>';
}

function syncReviewDefaults() {
  const o = state.overview;
  if (o) {
    const mb = $('#rv-maxboard');
    if (mb && !mb.value) mb.value = o.limitup?.max_board || '';
    const ld = $('#rv-limitdown');
    if (ld && !ld.value) ld.value = o.limitdown?.count || '';
  }
  const h = state.hot;
  if (h && h.hottest && h.hottest.length) {
    const t1 = $('#rv-theme1');
    if (t1 && !t1.value) t1.value = h.hottest[0].sector || '';
    const t2 = $('#rv-theme2');
    if (t2 && !t2.value && h.hottest[1]) t2.value = h.hottest[1].sector || '';
  }
}

async function saveReview() {
  if (!state.store) await loadStore();
  const rec = {
    date: new Date().toISOString().slice(0, 10),
    theme1: $('#rv-theme1').value.trim(),
    theme2: $('#rv-theme2').value.trim(),
    max_board: Number($('#rv-maxboard').value) || 0,
    limit_down: Number($('#rv-limitdown').value) || 0,
    panic: $('#rv-panic').checked,
    plan: $('#rv-plan').value.trim(),
    created: new Date().toISOString(),
  };
  if (!rec.theme1 && !rec.plan) { toast('至少填写最强题材或次日计划', true); return; }
  const reviews = [rec].concat(state.store.reviews || []).slice(0, 60);
  state.store = await postJSON('/api/store', { reviews });
  $('#rv-msg').textContent = '已保存 · ' + rec.date;
  setTimeout(() => { const m = $('#rv-msg'); if (m) m.textContent = ''; }, 3000);
  renderReviews();
  toast('复盘已保存');
}

function renderReviews() {
  const el = $('#review-list');
  if (!el) return;
  const list = (state.store?.reviews) || [];
  if (!list.length) {
    el.innerHTML = '<div class="empty">暂无复盘记录。</div>';
    return;
  }
  el.className = 'review-list';
  el.innerHTML = list.slice(0, 20).map((r) => {
    const themes = [r.theme1, r.theme2].filter(Boolean).join(' · ') || '—';
    return `<div class="review-item">
      <div class="ri-top">
        <span class="ri-date">${esc(r.date)}</span>
        ${r.panic ? '<span class="tag up">退潮预警</span>' : ''}
        <span class="tag muted">最高 ${r.max_board ?? 0} 板</span>
        <span class="tag ${Number(r.limit_down) >= 20 ? 'up' : 'muted'}">跌停 ${r.limit_down ?? 0} 家</span>
      </div>
      <div class="ri-body">
        <b>最强题材：</b>${esc(themes)}<br>
        ${r.plan ? '<b>次日计划：</b>' + esc(r.plan) : ''}
      </div>
    </div>`;
  }).join('');
}

/* ------------------------------------------------------------------ */
/* 龙回头档案                                                           */
/* ------------------------------------------------------------------ */

function archTime(value) {
  const s = String(value || '');
  if (s.length >= 16) return s.slice(11, 16);
  if (s.length >= 10) return s.slice(5, 10);
  return '—';
}

function archDateLabel(date) {
  const s = String(date || '');
  return s.length >= 10 ? `${s.slice(0, 4)}年${Number(s.slice(5, 7))}月${Number(s.slice(8, 10))}日` : (s || '—');
}

function applyArchiveTheme(theme, persist) {
  const next = theme === 'celadon' ? 'celadon' : 'noir';
  state.archiveTheme = next;
  const page = $('#archive-page');
  if (page) page.dataset.theme = next;
  const dlg = $('#dlg-archive');
  if (dlg) dlg.dataset.theme = next;
  $$('[data-arch-theme]').forEach((b) => b.classList.toggle('is-active', b.dataset.archTheme === next));
  if (persist) {
    try { localStorage.setItem('lht.archive.theme', next); } catch (e) { /* 隐私模式下忽略 */ }
  }
}

async function loadArchive(force) {
  const tree = $('#archive-tree');
  const hint = $('#archive-hint');
  if (force && hint) hint.textContent = '正在刷新档案…';
  if (!force && state.archive && Date.now() - state.archiveAt < 15000) return renderArchive();
  if (!state.archive && tree) {
    tree.innerHTML = '<div class="arch-loading"><i></i><span>正在打开档案柜…</span></div>';
  }
  try {
    const d = await api('/api/archive');
    if (!d.ok) throw new Error(d.error || '接口异常');
    state.archive = d;
    state.archiveAt = Date.now();
    if (!state.archiveInit) {
      state.archiveInit = true;
      const m = (d.months || [])[0];
      if (m) {
        state.archiveOpen.months[m.month] = true;
        if (m.days && m.days[0]) state.archiveOpen.days[m.days[0].date] = true;
      }
    }
    renderArchive();
  } catch (e) {
    if (tree) {
      tree.innerHTML = `<div class="arch-empty"><div class="ae-seal">龍</div><h3>档案读取失败</h3>
        <p>${esc(e.message)}</p><button class="btn archive-primary" data-arch-retry>重新读取</button></div>`;
    }
    if (hint) hint.textContent = '读取失败';
  }
}

function archiveMatch(item) {
  const g = gradeOf(item.score).letter;
  if (state.archiveGrade !== 'all' && g !== state.archiveGrade) return false;
  const q = state.archiveQuery.trim().toLowerCase();
  if (!q) return true;
  return [item.code, item.name, item.sector]
    .some((v) => String(v || '').toLowerCase().includes(q));
}

function archiveHeat(month, days) {
  const parts = String(month).split('-').map(Number);
  const y = parts[0];
  const mo = parts[1];
  const total = new Date(y, mo, 0).getDate();
  const counts = {};
  days.forEach((d) => { counts[d.date] = (d.items || []).length; });
  let cells = '';
  for (let i = 1; i <= total; i++) {
    const key = `${month}-${String(i).padStart(2, '0')}`;
    const n = counts[key] || 0;
    const lv = n >= 4 ? 'lv3' : (n >= 2 ? 'lv2' : (n ? 'has' : ''));
    cells += `<i class="${lv}" title="${esc(key)}${n ? ` · ${n} 只` : ''}"></i>`;
  }
  return `<span class="am-heat" aria-hidden="true">${cells}</span>`;
}

function archiveStockCard(item, date) {
  const g = gradeOf(item.score);
  const signal = item.right_side ? '放量起爆' : (item.stable ? '缩量止跌' : '等待确认');
  const shrink = item.shrink_ratio === null || item.shrink_ratio === undefined
    ? '—' : `${Math.round(Number(item.shrink_ratio) * 100)}%`;
  return `<article class="arch-stock grade-${g.letter}"
       data-arch-open="${esc(date)}" data-arch-code="${esc(item.code)}"
       data-code="${esc(item.code)}" role="button" tabindex="0"
       aria-label="${esc(item.name)} ${esc(item.code)} 档案详情">
    <div class="as-head">
      <div class="as-score" style="--p:${Math.max(0, Math.min(100, Number(item.score) || 0))}">
        <span>${fmt(item.score, 0)}<small>分</small></span>
      </div>
      <div class="as-id"><b>${esc(item.name || '—')}</b><small>${esc(item.code || '')}</small></div>
      <span class="as-grade">${g.letter}</span>
    </div>
    <div class="as-price">
      <b>${fmt(item.price)}</b>
      <em class="${tone(item.pct)}">${sgn(item.pct)}%</em>
      <span>首次 ${archTime(item.firstMatchedAt)}</span>
    </div>
    <div class="as-tags">
      <span>${Number(item.boards) || 0} 连板</span>
      <span>回调 ${Number(item.pullback_days) || 0} 日</span>
      <span>幅度 ${fmt(item.pullback_pct, 1)}%</span>
      <span>缩量 ${shrink}</span>
    </div>
    <div class="as-foot">
      <span class="as-sector">${esc(item.sector || '未归类板块')}</span>
      <span class="as-signal">${signal}</span>
    </div>
  </article>`;
}

function archiveDayCard(day) {
  const open = !!state.archiveOpen.days[day.date];
  const dt = new Date(day.date + 'T00:00:00');
  const week = isNaN(dt.getTime()) ? '' : WEEK_CN[dt.getDay()];
  const firsts = day.items.map((x) => x.firstMatchedAt).filter(Boolean).sort();
  const lasts = day.items.map((x) => x.lastMatchedAt || x.firstMatchedAt).filter(Boolean).sort();
  const sectors = (day.sectors || []).slice(0, 3)
    .map((s) => `<span>${esc(s)}</span>`).join('');
  return `<article class="arch-day${open ? ' is-open' : ''}">
    <button class="ad-head" data-arch-day="${esc(day.date)}" aria-expanded="${open}">
      <span class="ad-date"><b>${esc(day.date.slice(8, 10))}</b><small>${week}</small></span>
      <span class="ad-meta">
        <b>${day.items.length} 只命中<em>最高 ${day.bestScore} 分</em></b>
        <small>首次收录 ${archTime(firsts[0])} · 最近确认 ${archTime(lasts[lasts.length - 1])}</small>
      </span>
      <span class="ad-sectors">${sectors}</span>
      <span class="ad-chev">⌄</span>
    </button>
    <div class="ad-body">
      <div class="ad-actions">
        <span>${esc(archDateLabel(day.date))} · 最近更新 ${archTime(day.updatedAt)}</span>
        <button class="ad-del" data-arch-del-day="${esc(day.date)}">删除本日档案</button>
      </div>
      <div class="arch-stocks">${day.items.map((it) => archiveStockCard(it, day.date)).join('')}</div>
    </div>
  </article>`;
}

function archiveMonthCard(month, days) {
  const open = !!state.archiveOpen.months[month.month];
  const parts = String(month.month).split('-');
  const year = parts[0] || '—';
  const mo = Number(parts[1]) || 1;
  const cn = MONTH_CN[mo - 1] || String(mo);
  const en = MONTH_EN[mo - 1] || '';
  const count = days.reduce((sum, d) => sum + d.items.length, 0);
  const best = Math.max(0, ...days.map((d) => Number(d.bestScore) || 0));
  return `<section class="arch-month${open ? ' is-open' : ''}">
    <button class="am-head" data-arch-month="${esc(month.month)}" aria-expanded="${open}">
      <span class="am-seal">${cn}月</span>
      <span class="am-title">
        <small>${esc(year)}</small>
        <b>${cn}月</b>
        <em>${en} / ${parts[1] || ''}</em>
      </span>
      <span class="am-metrics">
        <span><b>${days.length}</b><small>归档交易日</small></span>
        <span><b>${count}</b><small>命中标的</small></span>
        <span><b>${best || '—'}</b><small>最高评分</small></span>
      </span>
      ${archiveHeat(month.month, days)}
      <span class="am-chev">⌄</span>
    </button>
    <div class="am-body">
      <div class="arch-days">${days.map(archiveDayCard).join('')}</div>
    </div>
  </section>`;
}

function renderArchive() {
  const tree = $('#archive-tree');
  if (!tree) return;
  const d = state.archive;
  if (!d) {
    tree.innerHTML = '<div class="arch-loading"><i></i><span>正在打开档案柜…</span></div>';
    return;
  }

  const t = d.totals || {};
  const setText = (sel, value) => { const el = $(sel); if (el) el.textContent = value; };
  setText('#arch-stat-months', t.months || 0);
  setText('#arch-stat-days', t.days || 0);
  setText('#arch-stat-records', t.records || 0);
  setText('#arch-stat-best', t.bestScore ? t.bestScore : '—');
  setText('#arch-last', t.lastDate
    ? `最近收录 ${t.lastDate}${t.lastMatchedAt ? ' · ' + archTime(t.lastMatchedAt) : ''}`
    : '最近收录 —');

  $$('#archive-filters [data-arch-grade]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.archGrade === state.archiveGrade);
  });

  const months = (d.months || []).map((month) => {
    const days = (month.days || []).map((day) => {
      const items = (day.items || []).filter(archiveMatch);
      return items.length ? { ...day, items } : null;
    }).filter(Boolean);
    return days.length ? { ...month, days } : null;
  }).filter(Boolean);

  const filtered = !!state.archiveQuery.trim() || state.archiveGrade !== 'all';
  const shown = months.reduce((sum, m) =>
    sum + m.days.reduce((s, day) => s + day.items.length, 0), 0);

  const hint = $('#archive-hint');
  if (hint) {
    hint.textContent = filtered
      ? `筛选 ${shown} 条 / 共 ${t.records || 0} 条`
      : `收录评分 ≥ ${d.minScore ?? 65} 分 · 共 ${t.records || 0} 条${d.auto ? ' · 扫描后自动存档' : ' · 自动存档已关闭'}`;
  }

  if (!(d.months || []).length) {
    tree.innerHTML = `<div class="arch-empty">
      <div class="ae-seal">龍</div>
      <h3>档案柜还是空的</h3>
      <p>去第二层执行一次「龙回头扫描」。达到档案评分线的标的会自动封存，
         首次命中时间、股价、评分与买点都会一起记录下来。</p>
      <button class="btn archive-primary" data-goto="2">去扫描并开启档案</button>
    </div>`;
    return;
  }

  if (!months.length) {
    tree.innerHTML = `<div class="arch-empty">
      <div class="ae-seal">寻</div>
      <h3>没有匹配的记录</h3>
      <p>换一个代码、名称或板块关键词试试，或把评级筛选切回「全部」。</p>
      <button class="btn archive-primary" data-arch-reset>清除筛选</button>
    </div>`;
    return;
  }

  tree.innerHTML = months.map((m) => archiveMonthCard(m, m.days)).join('');
}

function findArchiveHit(date, code) {
  const months = state.archive ? (state.archive.months || []) : [];
  for (const month of months) {
    const day = (month.days || []).find((d) => d.date === date);
    if (!day) continue;
    const item = (day.items || []).find((x) => String(x.code) === String(code));
    if (item) return { item, day, month };
  }
  return null;
}

function openArchiveDetail(date, code) {
  const hit = findArchiveHit(date, code);
  if (!hit) { toast('这条档案已经不存在了', true); return; }
  const { item, day } = hit;
  const g = gradeOf(item.score);
  const L = item.levels || {};
  const plan = item.plan || {};
  const details = (item.details || []).map((x) => {
    const max = Number(x.max) || 0;
    const sc = Number(x.score) || 0;
    const ratio = max ? Math.max(0, Math.min(100, sc / max * 100)) : 0;
    return `<div>
      <div class="si-top"><b>${esc(x.key)}</b><span>${esc(x.label)}</span><span class="si-val">${sc} / ${max}</span></div>
      <div class="si-bar"><div class="si-fill" style="width:${ratio}%"></div></div>
      <div class="si-note">${esc(x.note)}</div>
    </div>`;
  }).join('');

  const snaps = (item.snapshots || []).slice().reverse().slice(0, 16).map((s) => `
    <div class="adh-snap">
      <span>${esc(s.at || '')}</span>
      <b>${fmt(s.price)}</b>
      <em class="${tone(s.pct)}">${sgn(s.pct)}%</em>
      <b>${Number(s.score) || 0} 分</b>
    </div>`).join('');

  const kv = [
    ['所属板块', esc(item.sector || '—')],
    ['连板高度', `${Number(item.boards) || 0} 板`],
    ['回调天数', `${Number(item.pullback_days) || 0} 日`],
    ['回调幅度', `${fmt(item.pullback_pct, 1)}%`],
    ['缩量比', item.shrink_ratio === null || item.shrink_ratio === undefined
      ? '—' : `${(Number(item.shrink_ratio) * 100).toFixed(0)}%（回调均量 / 拉升天量）`],
    ['MA5 / MA10 / MA20', `${fmt(item.ma5)} / ${fmt(item.ma10)} / ${fmt(item.ma20)}`],
    ['流通市值', `${fmt(item.float_cap, 1)} 亿`],
    ['换手 / 量比', `${fmt(item.turnover, 2)}% / ${fmt(item.vol_ratio, 2)}`],
    ['洗盘箱体上沿', fmt(item.box_top)],
    ['拉升期最高价', fmt(item.rally_high)],
  ].map(([k, val]) => `<dt>${k}</dt><dd>${val}</dd>`).join('');

  const buys = `
    <div class="adh-bps">
      <div class="bp"><div class="bp-lab">稳健买点</div><div class="bp-val">${fmt(L.steady_buy)}</div></div>
      <div class="bp"><div class="bp-lab">放量突破位</div><div class="bp-val">${fmt(L.box_top)}</div></div>
      <div class="bp sl"><div class="bp-lab">止损价</div><div class="bp-val">${fmt(L.stop_loss)}</div></div>
      <div class="bp tp"><div class="bp-lab">止盈 1 / 2</div><div class="bp-val">${fmt(L.take_profit_half)} / ${fmt(L.take_profit_full)}</div></div>
    </div>`;

  const planHtml = plan.ok ? `
    <div class="adh-kv" style="margin-top:11px">
      <dt>首笔观察哨</dt><dd>${plan.starter_qty || 0} 股 / ${fmt(plan.starter_amount, 0)} 元</dd>
      <dt>确认后补足</dt><dd>${plan.add_qty || 0} 股</dd>
      <dt>单股上限</dt><dd>${plan.full_qty || 0} 股 / ${fmt(plan.full_amount, 0)} 元</dd>
    </div>` : '';

  const body = `<div class="arch-detail">
    <div class="adh-top">
      <div class="adh-score grade-${g.letter}" style="--p:${Math.max(0, Math.min(100, Number(item.score) || 0))}">
        <span>${fmt(item.score, 0)}<small>分</small></span>
      </div>
      <div class="adh-id">
        <h2>${esc(item.name || '—')}<span>${esc(item.code || '')}</span></h2>
        <p>${esc(archDateLabel(day.date))} · 首次命中 <b>${esc(item.firstMatchedAt || '—')}</b>
           · 最近确认 <b>${esc(item.lastMatchedAt || '—')}</b> · 累计命中 <b>${Number(item.hitCount) || 1}</b> 次</p>
      </div>
      <button class="adh-close" data-arch-close aria-label="关闭">×</button>
    </div>

    <div class="adh-price">
      <b>${fmt(item.price)}</b>
      <em class="${tone(item.pct)}">${sgn(item.pct)}%</em>
      <span>首次命中价 ${fmt(item.firstPrice)}<br>${esc(item.grade || g.letter + ' 级')}</span>
    </div>

    <div class="adh-grid">
      <div>
        <div class="adh-sec">
          <h3>命中时的日 K 与关键位</h3>
          <canvas class="chart" id="arch-detail-chart"></canvas>
          ${buys}
          <div class="adh-verdict">${esc(item.advice || '档案未记录操作建议。')}</div>
          ${planHtml}
        </div>
      </div>
      <div>
        <div class="adh-sec">
          <h3>评分明细 · ${fmt(item.score, 0)} / 100</h3>
          <div class="adh-score-list">${details || '<div class="empty">未记录评分明细</div>'}</div>
        </div>
        <div class="adh-sec" style="margin-top:12px">
          <h3>关键要素</h3>
          <dl class="adh-kv">${kv}</dl>
        </div>
        <div class="adh-sec" style="margin-top:12px">
          <h3>命中快照 · 时间 / 股价 / 评分</h3>
          <div class="adh-snaps">${snaps || '<div class="empty">未记录快照</div>'}</div>
        </div>
      </div>
    </div>

    <div class="adh-actions">
      <button class="btn ghost" data-watch="${esc(item.code)}">☆ 加入自选</button>
      <button class="btn ghost" data-arch-live="${esc(item.code)}">↗ 查看实时分析</button>
      <button class="btn danger" data-arch-del-record="${esc(day.date)}|${esc(item.code)}">删除该条记录</button>
      <span class="muted" style="margin-left:auto">档案只记录历史，不构成当前买卖建议</span>
    </div>
  </div>`;

  const box = $('#archive-detail');
  if (!box) return;
  box.innerHTML = body;
  const dlg = $('#dlg-archive');
  dlg.dataset.theme = state.archiveTheme;
  state.archiveDetail = {
    bars: item.bars || [],
    boxTop: item.box_top,
    rallyHigh: item.rally_high,
  };
  if (dlg.showModal) dlg.showModal();
  const paint = () => {
    const canvas = $('#arch-detail-chart');
    if (canvas) drawChart(canvas, state.archiveDetail);
  };
  // showModal 之后布局已完成；再补一帧，兼顾刷新率较低或被节流的标签页。
  paint();
  setTimeout(paint, 80);
}

async function deleteArchive(date, code) {
  const what = code ? `${code} 在 ${date} 的档案记录` : `${date} 整天的档案`;
  if (!window.confirm(`确定删除${what}？此操作不可撤销。`)) return;
  try {
    const d = await postJSON('/api/archive', { action: 'delete', date, code: code || '' });
    if (!d.ok) throw new Error(d.error || '删除失败');
    state.archive = d;
    state.archiveAt = Date.now();
    const dlg = $('#dlg-archive');
    if (dlg && dlg.open) dlg.close();
    renderArchive();
    toast('档案已更新');
  } catch (e) {
    toast('删除失败：' + e.message, true);
  }
}

function exportArchive() {
  if (!state.archive) { toast('档案尚未加载', true); return; }
  const blob = new Blob([JSON.stringify(state.archive, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `longhuitou-archive-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('档案已导出为 JSON');
}

/* ------------------------------------------------------------------ */
/* 设置                                                                 */
/* ------------------------------------------------------------------ */

async function loadStore() {
  try {
    const d = await api('/api/store');
    state.store = d;
    state.settings = { ...(d.settings || {}) };
  } catch (e) {
    toast('本地配置读取失败：' + e.message, true);
    state.store = state.store || { settings: {}, watchlist: [], positions: [], reviews: [] };
  }
  return state.store;
}

function renderSettingsForm() {
  const el = $('#settings-form');
  if (!el) return;
  el.innerHTML = SETTING_FIELDS.map(([key, label, step]) => `
    <label>${esc(label)}
      <input type="number" data-set="${esc(key)}" step="${step}"
             value="${num(state.settings[key]) ?? ''}">
    </label>`).join('');
}

function renderNotifyForm() {
  const el = $('#notify-form');
  if (!el) return;
  const s = state.settings || {};
  const on = Array.isArray(s.notifyChannels) ? s.notifyChannels : [];
  const keys = (s.notifyKeys && typeof s.notifyKeys === 'object') ? s.notifyKeys : {};

  el.innerHTML = `
    <div class="nch-list">${NOTIFY_CHANNELS.map(([v, name, ph]) => `
      <div class="nch-row${on.indexOf(v) >= 0 ? '' : ' off'}" data-ch="${v}">
        <label class="nch-on">
          <input type="checkbox" data-ch="${v}"${on.indexOf(v) >= 0 ? ' checked' : ''}>
          <span>${esc(name)}</span>
        </label>
        <input type="text" data-chkey="${v}" autocomplete="off" spellcheck="false"
               placeholder="${esc(ph)}" value="${esc(keys[v] || '')}">${v === 'wecom' ? `
        <select data-chfmt="wecom" title="正文格式">${WECOM_FORMATS.map(([fv, ft]) =>
          `<option value="${fv}"${fv === (s.notifyWecomFormat || 'text') ? ' selected' : ''}>${esc(ft)}</option>`).join('')}</select>` : ''}
      </div>`).join('')}
    </div>
    <p class="form-hint" id="notify-hint"></p>
    <div class="form-grid">
      <label>只推该评分以上
        <input type="number" data-notify="notifyMinScore" step="5" min="0" max="100"
               value="${num(s.notifyMinScore) ?? 65}">
      </label>
      <label>单条最多几只
        <input type="number" data-notify="notifyTopN" step="1" min="1" max="30"
               value="${num(s.notifyTopN) ?? 8}">
      </label>
      <label>交易日自动推送时刻
        <input type="text" data-notify="notifyTimes" placeholder="15:05，多个用逗号分隔"
               value="${esc(s.notifyTimes || '')}">
      </label>
      <label>扫描窗口（交易日）
        <input type="number" data-notify="notifyDays" step="1" min="3" max="15"
               value="${num(s.notifyDays) ?? 10}">
      </label>
    </div>`;

  $$('#notify-form input[data-ch]').forEach((cb) => {
    cb.addEventListener('change', () => {
      const row = cb.closest('.nch-row');
      if (row) row.classList.toggle('off', !cb.checked);
      refreshNotifyHint();
    });
  });
  refreshNotifyHint();
}

/** 读当前勾选的通道。 */
function checkedChannels() {
  return $$('#notify-form input[data-ch]').filter((cb) => cb.checked).map((cb) => cb.dataset.ch);
}

/** 按勾选情况刷新下方说明。 */
function refreshNotifyHint() {
  const hint = $('#notify-hint');
  if (!hint) return;
  const on = checkedChannels();
  if (!on.length) { hint.innerHTML = NOTIFY_HINT.off; return; }
  const head = on.length > 1
    ? `已开启 <b>${on.length}</b> 个通道，同一份内容会并行发出（互为冗余）：`
    : '';
  hint.innerHTML = head + on.map((c) => NOTIFY_HINT[c] || '').filter(Boolean).join('<br>');
}

/** 读设置对话框里的推送字段，返回存储结构（notifyXxx）。 */
function collectNotifyPatch() {
  const channels = [];
  const keys = {};
  $$('#notify-form input[data-ch]').forEach((cb) => {
    const ch = cb.dataset.ch;
    const keyEl = document.querySelector(`#notify-form input[data-chkey="${ch}"]`);
    const key = keyEl ? keyEl.value.trim() : '';
    if (cb.checked) channels.push(ch);
    if (key) keys[ch] = key;      // 没勾选也保留密钥，方便随时切回
  });
  const patch = { notifyChannels: channels, notifyKeys: keys };
  const fmt = document.querySelector('#notify-form select[data-chfmt="wecom"]');
  if (fmt) patch.notifyWecomFormat = fmt.value;
  $$('#notify-form [data-notify]').forEach((inp) => {
    const k = inp.dataset.notify;
    if (k === 'notifyTimes') { patch[k] = String(inp.value || '').trim(); return; }
    const v = Number(inp.value);
    if (inp.value !== '' && !isNaN(v)) patch[k] = v;
  });
  return patch;
}

/** 勾了通道却没填密钥的，返回提示文案（这些通道实际不会生效）。 */
function notifyWarnings(patch) {
  const keys = patch.notifyKeys || {};
  return (patch.notifyChannels || [])
    .filter((ch) => !keys[ch])
    .map((ch) => `${(NOTIFY_CHANNELS.find((c) => c[0] === ch) || [, ch])[1]} 没填密钥，本次不会生效`);
}

/** 把存储结构转成 /api/notify 的临时覆盖参数（只对本次生效）。 */
function notifyOverride(patch) {
  const p = patch || collectNotifyPatch();
  const out = { channels: p.notifyChannels || [], keys: p.notifyKeys || {} };
  if (p.notifyWecomFormat) out.wecomFormat = p.notifyWecomFormat;
  if (p.notifyMinScore != null) out.minScore = p.notifyMinScore;
  if (p.notifyTopN != null) out.top = p.notifyTopN;
  if (p.notifyDays != null) out.days = p.notifyDays;
  return out;
}

function openSettings() {
  renderSettingsForm();
  renderNotifyForm();
  const dlg = $('#dlg-settings');
  if (dlg.showModal) dlg.showModal();
}

async function saveSettings() {
  const patch = {};
  $$('#settings-form input[data-set]').forEach((inp) => {
    const v = Number(inp.value);
    if (inp.value !== '' && !isNaN(v)) patch[inp.dataset.set] = v;
  });
  const notify = collectNotifyPatch();
  Object.assign(patch, notify);
  const warn = notifyWarnings(notify);
  try {
    // 服务端对 settings 是按字段合并，所以只提交表单里出现过的键是安全的
    state.store = await postJSON('/api/store', { settings: patch });
    state.settings = { ...(state.store.settings || {}) };
    invalidate('overview'); invalidate('hot'); invalidate('limitup');
    if (warn.length) toast('已保存，但 ' + warn.join('；'), true);
    else if (state.store.persisted === false) {
      toast('已生效，但云端磁盘是临时的：服务重启后会恢复默认值', true);
    } else toast('策略参数已保存');
    renderCalc();
    if (state.scan) toast('参数已更新，可重新扫描以应用新阈值');
  } catch (e) {
    toast('保存失败：' + e.message, true);
  }
}

/* ------------------------------------------------------------------ */
/* 刷新                                                                 */
/* ------------------------------------------------------------------ */

function refreshLive() {
  loadOverview(true);
  if (state.page === 1) { loadHot(true); loadLimitup(true); }
  if (state.page === 3) loadPositions();
  if (state.page === 4) loadDiscipline();
  if (state.page === 5 && state.overview) renderSentimentStats(state.overview);
}

/* ------------------------------------------------------------------ */
/* 事件绑定                                                             */
/* ------------------------------------------------------------------ */

function bindEvents() {
  /* --- 悬停预览：日K + 分时（事件委托，覆盖所有 [data-code]） --- */
  document.addEventListener('mouseover', (ev) => {
    const el = ev.target.closest ? ev.target.closest('[data-code]') : null;
    if (!el || el === _hvAnchor) return;
    const code = el.dataset.code;
    if (!code) return;
    _hvAnchor = el;
    clearTimeout(_hvTimer);
    _hvTimer = setTimeout(() => { if (_hvAnchor === el) showHover(code); }, HOVER_DELAY);
  });

  document.addEventListener('mouseout', (ev) => {
    const el = ev.target.closest ? ev.target.closest('[data-code]') : null;
    if (!el) return;
    const to = ev.relatedTarget && ev.relatedTarget.closest
      ? ev.relatedTarget.closest('[data-code]') : null;
    if (to === el) return;
    if (to) return;                       // 移到另一只股票，交给 mouseover 处理
    hideHover();
  });

  document.addEventListener('mousemove', (ev) => {
    _hvX = ev.clientX;
    _hvY = ev.clientY;
    if (!_hvOn) return;
    // 列表被自动刷新后旧锚点会脱离文档，此时必须收起，否则预览会卡住。
    if (_hvAnchor && !_hvAnchor.isConnected) { hideHover(); return; }
    positionHover();
  });

  document.addEventListener('mouseleave', hideHover);
  window.addEventListener('wheel', hideHover, { passive: true });
  window.addEventListener('scroll', hideHover, { passive: true });
  window.addEventListener('blur', hideHover);

  document.addEventListener('click', (ev) => {
    hideHover();
    const t = ev.target;

    const goto = t.closest('[data-goto]');
    if (goto) { switchPage(Number(goto.dataset.goto)); return; }

    const floor = t.closest('.lift-btn, .flow-step, .floor3d');
    if (floor) {
      const p = floor.dataset.layer !== undefined ? floor.dataset.layer : floor.dataset.page;
      switchPage(Number(p));
      return;
    }

    const del = t.closest('[data-del-pos]');
    if (del) { removePosition(del.dataset.delPos); return; }

    const watch = t.closest('[data-watch]');
    if (watch) { addWatch(watch.dataset.watch); return; }

    const posBtn = t.closest('[data-pos]');
    if (posBtn) { quickPosition(posBtn.dataset.pos); return; }

    const reload = t.closest('[data-reload]');
    if (reload) { loadHot(true); return; }

    /* --- 龙回头档案 --- */
    const themeBtn = t.closest('[data-arch-theme]');
    if (themeBtn) { applyArchiveTheme(themeBtn.dataset.archTheme, true); return; }

    const gradeBtn = t.closest('[data-arch-grade]');
    if (gradeBtn) { state.archiveGrade = gradeBtn.dataset.archGrade || 'all'; renderArchive(); return; }

    const resetBtn = t.closest('[data-arch-reset]');
    if (resetBtn) {
      state.archiveQuery = '';
      state.archiveGrade = 'all';
      const input = $('#archive-search');
      if (input) input.value = '';
      renderArchive();
      return;
    }

    const retryBtn = t.closest('[data-arch-retry]');
    if (retryBtn) { loadArchive(true); return; }

    const delDay = t.closest('[data-arch-del-day]');
    if (delDay) { deleteArchive(delDay.dataset.archDelDay || '', ''); return; }

    const delRec = t.closest('[data-arch-del-record]');
    if (delRec) {
      const [date, code] = String(delRec.dataset.archDelRecord || '').split('|');
      deleteArchive(date, code);
      return;
    }

    const archClose = t.closest('[data-arch-close]');
    if (archClose) {
      const dlg = $('#dlg-archive');
      if (dlg && dlg.open) dlg.close();
      return;
    }

    const archLive = t.closest('[data-arch-live]');
    if (archLive) {
      const dlg = $('#dlg-archive');
      if (dlg && dlg.open) dlg.close();
      selectStock(archLive.dataset.archLive);
      return;
    }

    const monthToggle = t.closest('[data-arch-month]');
    if (monthToggle) {
      const key = monthToggle.dataset.archMonth;
      const opening = !state.archiveOpen.months[key];
      state.archiveOpen.months[key] = opening;
      if (opening && state.archive) {
        const month = (state.archive.months || []).find((m) => m.month === key);
        const hasOpen = month && (month.days || []).some((d) => state.archiveOpen.days[d.date]);
        if (month && !hasOpen) {
          const first = (month.days || []).find((d) =>
            (d.items || []).some(archiveMatch));
          if (first) state.archiveOpen.days[first.date] = true;
        }
      }
      renderArchive();
      return;
    }

    const dayToggle = t.closest('[data-arch-day]');
    if (dayToggle) {
      const key = dayToggle.dataset.archDay;
      state.archiveOpen.days[key] = !state.archiveOpen.days[key];
      renderArchive();
      return;
    }

    const archOpen = t.closest('[data-arch-open]');
    if (archOpen) {
      openArchiveDetail(archOpen.dataset.archOpen, archOpen.dataset.archCode);
      return;
    }

    const stock = t.closest('[data-code]');
    if (stock && stock.dataset.code) { selectStock(stock.dataset.code); return; }
  });

  $('#btn-refresh').addEventListener('click', () => {
    invalidate('overview'); invalidate('hot'); invalidate('limitup');
    refreshLive();
    toast('已刷新实时行情');
  });

  $('#auto-refresh').addEventListener('change', (e) => {
    toast(e.target.checked ? '已开启自动刷新（20 秒）' : '已关闭自动刷新');
  });

  $('#btn-settings').addEventListener('click', openSettings);
  $('#btn-save-settings').addEventListener('click', (ev) => {
    ev.preventDefault();
    saveSettings().then(() => { const d = $('#dlg-settings'); if (d.open) d.close(); });
  });

  $('#btn-scan').addEventListener('click', runScan);
  $('#btn-eval').addEventListener('click', () => loadDiscipline(true));

  /* --- 龙回头档案 --- */
  $('#btn-open-archive').addEventListener('click', () => switchPage(6));
  $('#btn-archive-refresh').addEventListener('click', () => loadArchive(true));
  $('#btn-archive-export').addEventListener('click', exportArchive);
  $('#btn-archive-goto-scan').addEventListener('click', () => switchPage(2));
  $('#archive-search').addEventListener('input', (ev) => {
    state.archiveQuery = String(ev.target.value || '');
    renderArchive();
  });
  $('#dlg-archive').addEventListener('click', (ev) => {
    if (ev.target && ev.target.id === 'dlg-archive') ev.currentTarget.close();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const card = ev.target.closest ? ev.target.closest('[data-arch-open]') : null;
    if (!card) return;
    ev.preventDefault();
    openArchiveDetail(card.dataset.archOpen, card.dataset.archCode);
  });

  /* --- 微信推送 --- */
  $('#btn-test-push').addEventListener('click', async (ev) => {
    ev.preventDefault();
    const btn = ev.currentTarget;
    busy(btn, true, '发送中…');
    try {
      const d = await postJSON('/api/notify', { test: true, ...notifyOverride() });
      toast(d.ok ? `测试消息已提交（${d.channel}）：${d.detail}` : `推送失败：${d.detail}`, !d.ok);
    } catch (e) {
      toast('推送失败：' + e.message, true);
    } finally {
      busy(btn, false);
    }
  });

  $('#btn-push-scan').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const s = state.settings || {};
    const chans = Array.isArray(s.notifyChannels) ? s.notifyChannels : [];
    const keys = (s.notifyKeys && typeof s.notifyKeys === 'object') ? s.notifyKeys : {};
    if (!chans.some((c) => keys[c])) {
      toast('还没配置推送通道，先在「策略参数 → 微信推送」里勾选通道并填好密钥', true);
      openSettings();
      return;
    }
    busy(btn, true, '推送中…');
    try {
      // 用服务端已保存的设置（不读对话框里可能未保存的临时值）
      const d = await postJSON('/api/notify', { scan: true });
      toast(d.ok
        ? `已推送：命中 ${d.hit} 只，其中 ≥${d.minScore} 分的 ${d.picked} 只（耗时 ${d.elapsed}s）`
        : `推送失败：${d.detail}`, !d.ok);
    } catch (e) {
      toast('推送失败：' + e.message, true);
    } finally {
      busy(btn, false);
    }
  });

  ['#calc-capital', '#calc-maxpct', '#calc-starter', '#calc-price'].forEach((sel) => {
    $(sel).addEventListener('input', renderCalc);
  });

  $('#btn-add-pos').addEventListener('click', async () => {
    const btn = $('#btn-add-pos');
    busy(btn, true, '校验中…');
    const ok = await addPosition({
      code: $('#pos-code').value,
      cost_price: $('#pos-cost').value,
      quantity: $('#pos-qty').value,
      buy_date: $('#pos-date').value,
    });
    busy(btn, false);
    if (ok) {
      $('#pos-code').value = '';
      $('#pos-cost').value = '';
      $('#pos-qty').value = '';
      $('#pos-msg').textContent = '已保存';
      setTimeout(() => { $('#pos-msg').textContent = ''; }, 2500);
      await loadPositions();
      await loadDiscipline();
    }
  });

  $('#btn-dragons').addEventListener('click', () => loadDragons(true));
  $('#dragon-days').addEventListener('change', () => loadDragons(true));
  $('#btn-save-review').addEventListener('click', saveReview);

  let rt;
  window.addEventListener('resize', () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      if (state.chart) drawChart($('#stock-chart'), state.chart);
      const adlg = $('#dlg-archive');
      if (adlg && adlg.open && state.archiveDetail) {
        drawChart($('#arch-detail-chart'), state.archiveDetail);
      }
    }, 160);
  });
}

async function addWatch(code) {
  if (!state.store) await loadStore();
  const list = (state.store.watchlist || []).slice();
  if (list.some((w) => String(w.code) === String(code))) { toast('已在自选池中'); return; }
  const q = await api('/api/quote?codes=' + code);
  const name = (q.items && q.items[0] && q.items[0].name) || '';
  list.push({ code: String(code), name, added: new Date().toISOString().slice(0, 10) });
  state.store = await postJSON('/api/store', { watchlist: list });
  toast(`已加入自选：${name || code}`);
}

async function quickPosition(code) {
  if (!state.store) await loadStore();
  const q = await api('/api/quote?codes=' + code);
  const item = (q.items || [])[0];
  if (!item) { toast('未取到行情，无法建仓', true); return; }
  const settings = state.settings || {};
  const budget = (Number(settings.capital) || 100000) * (Number(settings.maxPositionPct) || 50) / 100;
  const firstQty = Math.max(100, Math.floor(budget * (Number(settings.starterPct) || 30) / 100 / item.price / 100) * 100);
  const ok = await addPosition({
    code, cost_price: item.price, quantity: firstQty,
    buy_date: new Date().toISOString().slice(0, 10),
  });
  if (ok) { switchPage(4); await loadDiscipline(); toast(`已按观察哨仓位 ${firstQty} 股建仓`); }
}

/* ------------------------------------------------------------------ */
/* 启动                                                                 */
/* ------------------------------------------------------------------ */

async function boot() {
  renderTower();
  bindEvents();

  let archiveTheme = 'noir';
  try { archiveTheme = localStorage.getItem('lht.archive.theme') || 'noir'; } catch (e) { /* 忽略 */ }
  applyArchiveTheme(archiveTheme, false);

  const today = new Date().toISOString().slice(0, 10);
  const pd = $('#pos-date');
  if (pd && !pd.value) pd.value = today;

  await loadStore();
  renderSettingsForm();
  renderNotifyForm();
  renderReviews();

  await loadOverview();
  switchPage(0);

  loadHot();
  renderScanMini(state.scan ? state.scan.items : null);
  loadPositions();

  setInterval(() => {
    if ($('#auto-refresh').checked) refreshLive();
  }, REFRESH_MS);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
