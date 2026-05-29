"""Standalone bot dashboard — read-only HTML over the state store.

A separate process from the live runner so it can't accidentally
interfere with trading. Reads only:
  * state.db (setups, setup_states, orders, runtime_flags, kill_events)
  * tails the JSON log file for recent ERROR lines
  * optionally HL public REST (counterfactual "would-be running" sim)
  * optionally HL signed REST (exchange-state card; gated by env)

NO signed write paths. The dashboard cannot place, cancel, or modify
orders — even with credentials present.

Run:
    PYTHONPATH=. .venv/bin/python -m apps.bot dashboard --port 9101
Then open http://127.0.0.1:9101 in a browser. The page auto-polls
/api/state every 5 seconds.
"""
from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from apps.bot.config import BotConfig, hl_agent_private_key
from apps.bot.logging_setup import get_logger
from apps.bot.risk.engine import (
    FUNDING_SKIP_PREFIX,
    RiskEngine,
)
from apps.bot.risk.funding_watcher import FUNDING_OBS_PREFIX
from apps.bot.state import StateStore
from apps.bot.strategy.levels import compute_levels

log = get_logger(__name__)

# TTL caches for expensive optional cards. Each tuple is (expires_at, value).
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl_s: float, build_fn):
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[0] > now:
            return entry[1]
    value = build_fn()
    with _CACHE_LOCK:
        _CACHE[key] = (now + ttl_s, value)
    return value


# Single-page HTML. Kept inline so the dashboard is a single import.
_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DB1-Sniper · live</title>
<style>
  :root {
    --bg: #0d1117; --fg: #c9d1d9; --mute: #8b949e;
    --good: #56d364; --bad: #f85149; --warn: #d29922; --accent: #58a6ff;
    --card: #161b22; --border: #30363d;
  }
  body {
    margin: 0; padding: 24px; font-family: -apple-system, system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
  }
  h1 { margin: 0 0 12px; font-weight: 600; }
  .grid {
    display: grid; gap: 16px;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }
  .card h2 {
    margin: 0 0 12px; font-size: 13px; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--mute);
  }
  .stat { display: flex; justify-content: space-between; padding: 4px 0; }
  .stat .v { font-variant-numeric: tabular-nums; }
  .good { color: var(--good); } .bad { color: var(--bad); }
  .warn { color: var(--warn); } .mute { color: var(--mute); }
  table {
    width: 100%; border-collapse: collapse;
    font-variant-numeric: tabular-nums;
    font-size: 13px;
  }
  th, td {
    text-align: left; padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }
  th { color: var(--mute); font-weight: 600; }
  tr:last-child td { border-bottom: 0; }
  .pill {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .pill.armed { background: #0d4a6e; color: #79c0ff; }
  .pill.entered { background: #054f31; color: #56d364; }
  .pill.tp1_hit, .pill.tp2_hit { background: #5a3500; color: #d29922; }
  .pill.tp3_full { background: #054f31; color: #56d364; }
  .pill.wipeout { background: #5a0d12; color: #f85149; }
  .pill.tp1_then_scratch, .pill.tp2_then_scratch {
    background: #3e3220; color: #d29922;
  }
  .pill.risk_blocked, .pill.missed { background: #21262d; color: var(--mute); }
  .pill.detected { background: #21262d; color: var(--mute); }
  .pill.no_trigger, .pill.no_entry { background: #21262d; color: var(--mute); }
  .halt-banner {
    background: var(--bad); color: white; padding: 12px 16px;
    border-radius: 8px; margin-bottom: 16px; font-weight: 600;
  }
  .live-banner {
    background: #054f31; color: var(--good); padding: 8px 16px;
    border-radius: 6px; margin-bottom: 16px; font-size: 12px;
  }
  footer { margin-top: 24px; color: var(--mute); font-size: 11px; }

  /* Setup row + chart panel */
  tr.setup-row { cursor: pointer; }
  tr.setup-row:hover { background: #1c2128; }
  tr.setup-row.active { background: #1f4060 !important; }
  tr.setup-row.active td { color: #c9d1d9; }
  #chart-panel {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #161b22; border-top: 1px solid #30363d;
    padding: 12px 24px; box-shadow: 0 -8px 24px rgba(0,0,0,0.5);
    transform: translateY(100%);
    transition: transform 0.2s ease-out;
    z-index: 50;
  }
  #chart-panel.open { transform: translateY(0); }
  #chart-panel .row {
    display: flex; gap: 16px; align-items: stretch;
  }
  #chart-iframe-wrap {
    flex: 1 1 auto; height: 360px; min-width: 0;
    background: #0d1117; border-radius: 6px; overflow: hidden;
    position: relative;
  }
  #chart-iframe-wrap iframe {
    width: 100%; height: 100%; border: 0;
  }
  #chart-iframe-wrap .placeholder {
    display: flex; align-items: center; justify-content: center;
    height: 100%; color: var(--mute); font-size: 13px;
  }
  #chart-meta {
    flex: 0 0 280px; font-size: 12px;
  }
  #chart-meta h3 {
    margin: 0 0 8px; font-size: 13px; color: var(--accent);
    font-weight: 600;
  }
  #chart-meta .lvl { display: flex; justify-content: space-between; padding: 2px 0; }
  #chart-meta .lvl b { font-weight: 600; font-variant-numeric: tabular-nums; }
  #chart-panel .controls {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 8px;
  }
  #chart-panel .controls label {
    font-size: 12px; color: var(--mute); cursor: pointer;
    display: inline-flex; gap: 6px; align-items: center;
  }
  #chart-panel button.close-btn {
    background: transparent; color: var(--mute); border: 1px solid var(--border);
    padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  #chart-panel button.close-btn:hover { color: var(--fg); border-color: var(--fg); }
  body.has-chart-panel { padding-bottom: 440px; }
</style>
</head>
<body>
<h1>DB1-Sniper <span id="env" class="mute" style="font-size:14px"></span></h1>
<div id="banner"></div>
<div class="grid">
  <div class="card" id="card-risk">
    <h2>Risk</h2>
    <div id="risk"></div>
  </div>
  <div class="card" id="card-positions">
    <h2>In flight</h2>
    <div id="positions"></div>
  </div>
  <div class="card" id="card-funding">
    <h2>Funding (APY %)</h2>
    <div id="funding"></div>
  </div>
  <div class="card" id="card-kills">
    <h2>Recent kill events</h2>
    <div id="kills"></div>
  </div>
  <div class="card" id="card-counterfactual">
    <h2>Would-be running (sim)</h2>
    <div id="counterfactual"></div>
  </div>
  <div class="card" id="card-exchange">
    <h2>Exchange state</h2>
    <div id="exchange"></div>
  </div>
  <div class="card" id="card-errors">
    <h2>Recent errors</h2>
    <div id="errors"></div>
  </div>
</div>
<div class="card" style="margin-top:16px">
  <h2>Net R by entry level × asset (counterfactual)</h2>
  <div id="regimes"></div>
</div>

<div class="card" style="margin-top:16px">
  <h2>Last 50 setups</h2>
  <div id="setups"></div>
</div>
<footer>
  Auto-refreshes every 5s. Read-only — no exchange writes from this page.
  · Last update: <span id="ts">—</span>
</footer>

<div id="chart-panel">
  <div class="controls">
    <div>
      <label>
        <input type="checkbox" id="follow-scroll">
        follow scroll
      </label>
      <span class="mute" style="margin-left:16px" id="chart-current">—</span>
    </div>
    <button class="close-btn" onclick="closeChart()">close</button>
  </div>
  <div class="row">
    <div id="chart-iframe-wrap">
      <div class="placeholder">click a setup row to render its chart</div>
    </div>
    <div id="chart-meta">
      <h3 id="chart-title">no setup selected</h3>
      <div id="chart-levels"></div>
    </div>
  </div>
</div>
<script>
const fmt = (n, d=2) => Number(n).toLocaleString(undefined, {
  minimumFractionDigits: d, maximumFractionDigits: d,
});
const stat = (label, val, cls='') => `
  <div class="stat"><span class="mute">${label}</span>
  <span class="v ${cls}">${val}</span></div>`;

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    render(s);
    document.getElementById('ts').textContent = new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('banner').innerHTML =
      `<div class="halt-banner">dashboard fetch failed: ${e}</div>`;
  }
}

function render(s) {
  const r = s.risk;
  // Banner: halted > paused-asset > all clear.
  let banner = '';
  if (r.halted) {
    banner = `<div class="halt-banner">⛔ HALTED — ${r.halt_reason || ''}</div>`;
  } else if ((r.paused_assets || []).length) {
    banner = `<div class="live-banner">paused: ${r.paused_assets.join(', ')}</div>`;
  } else {
    banner = `<div class="live-banner">● running · accepting new entries</div>`;
  }
  document.getElementById('banner').innerHTML = banner;

  // Risk card
  const rLines = [
    stat('halted', r.halted ? 'YES' : 'no', r.halted ? 'bad' : 'good'),
    stat('open positions',
      `${r.concurrent_positions} / ${r.max_concurrent_positions}`),
    stat('today R',
      fmt(r.daily_realized_r),
      r.daily_realized_r < 0 ? 'bad' : 'good'),
    stat('today R limit', fmt(r.daily_loss_r_limit), 'mute'),
    stat('week R',
      fmt(r.weekly_realized_r),
      r.weekly_realized_r < 0 ? 'bad' : 'good'),
    stat('week R limit', fmt(r.weekly_loss_r_limit), 'mute'),
    stat('consec losses',
      `${r.consecutive_losses} / ${r.consecutive_loss_limit}`,
      r.consecutive_losses >= r.consecutive_loss_limit ? 'bad' :
      r.consecutive_losses > 0 ? 'warn' : ''),
  ];
  document.getElementById('risk').innerHTML = rLines.join('');

  // In flight
  const pos = s.in_flight_setups || [];
  if (!pos.length) {
    document.getElementById('positions').innerHTML =
      `<div class="mute">no in-flight setups</div>`;
  } else {
    document.getElementById('positions').innerHTML = `
      <table><thead><tr>
        <th>asset</th><th>dir</th><th>state</th><th>R</th>
      </tr></thead><tbody>
      ${pos.map(p => `
        <tr><td>${p.asset}</td>
        <td>${p.direction}</td>
        <td><span class="pill ${p.state}">${p.state}</span></td>
        <td class="v">${p.realized_r != null ? fmt(p.realized_r) : ''}</td>
        </tr>`).join('')}
      </tbody></table>`;
  }

  // Funding
  const f = s.funding_apy || {};
  const fEntries = Object.entries(f).sort();
  if (!fEntries.length) {
    document.getElementById('funding').innerHTML =
      `<div class="mute">no observations yet</div>`;
  } else {
    document.getElementById('funding').innerHTML = `
      <table><thead><tr><th>asset</th><th>APY</th><th></th></tr></thead>
      <tbody>${fEntries.map(([k, v]) => {
        const apy = parseFloat(v);
        const paused = (r.paused_assets || []).includes(k);
        const cls = Math.abs(apy) > 100 ? 'bad' :
                    Math.abs(apy) > 50 ? 'warn' : '';
        return `<tr><td>${k}</td>
          <td class="v ${cls}">${fmt(apy, 2)}%</td>
          <td>${paused ? '<span class="pill wipeout">paused</span>' : ''}</td>
        </tr>`;
      }).join('')}</tbody></table>`;
  }

  // Kill events
  const k = s.kill_events || [];
  if (!k.length) {
    document.getElementById('kills').innerHTML =
      `<div class="mute">no kill events recorded</div>`;
  } else {
    document.getElementById('kills').innerHTML = `
      <table><thead><tr>
        <th>when</th><th>reason</th><th>ok</th>
      </tr></thead><tbody>
      ${k.slice(0, 8).map(e => `
        <tr><td class="mute">${e.halted_at}</td>
        <td>${e.reason}</td>
        <td class="${(e.summary && e.summary.cancel_failures &&
          e.summary.cancel_failures.length) ||
          (e.summary && e.summary.close_failures &&
          e.summary.close_failures.length) ? 'bad' : 'good'}">
          ${(e.summary && e.summary.cancel_failures &&
            !e.summary.cancel_failures.length &&
            e.summary.close_failures &&
            !e.summary.close_failures.length) ? '✓' : '⚠'}
        </td></tr>`).join('')}
      </tbody></table>`;
  }

  // Counterfactual
  const cf = s.counterfactual || {};
  const cfAssets = cf.per_asset || [];
  if (!cfAssets.length) {
    document.getElementById('counterfactual').innerHTML =
      `<div class="mute">sim pending…</div>`;
  } else {
    const open_rows = [];
    let total_open = 0;
    for (const a of cfAssets) {
      if (a.error) continue;
      for (const o of (a.open || [])) {
        open_rows.push(`<tr><td>${a.asset}</td>
          <td>${o.direction}</td>
          <td><span class="pill ${o.fsm_state}">${o.fsm_state}</span></td>
          <td class="v">${o.realized_r ? fmt(o.realized_r) : ''}</td>
          <td class="mute">${o.term_ts}</td></tr>`);
        total_open++;
      }
    }
    const head = stat('open right now', String(total_open),
                       total_open ? 'good' : 'mute');
    const tail = total_open
      ? `<table style="margin-top:8px"><thead><tr>
          <th>asset</th><th>dir</th><th>state</th><th>R</th>
          <th>since</th></tr></thead>
          <tbody>${open_rows.join('')}</tbody></table>`
      : `<div class="mute" style="margin-top:8px">
          no setups currently in flight in the counterfactual sim</div>`;
    document.getElementById('counterfactual').innerHTML = head + tail;
  }

  // Exchange state
  const ex = s.exchange_state;
  if (ex === null || ex === undefined) {
    document.getElementById('exchange').innerHTML =
      `<div class="mute">credentials not set — card hidden</div>`;
  } else if (ex.error) {
    document.getElementById('exchange').innerHTML =
      `<div class="bad">error: ${ex.error}</div>`;
  } else {
    const aprv = ex.agent_approved
      ? '<span class="good">approved</span>'
      : '<span class="bad">NOT approved</span>';
    const lines = [
      stat('agent', aprv),
      stat('positions', String((ex.positions || []).length)),
      stat('open orders', String((ex.open_orders || []).length)),
    ];
    document.getElementById('exchange').innerHTML = lines.join('');
  }

  // Recent errors
  const errs = s.recent_errors || [];
  if (!errs.length) {
    document.getElementById('errors').innerHTML =
      `<div class="mute">no recent errors</div>`;
  } else {
    document.getElementById('errors').innerHTML = `
      <table><thead><tr>
        <th>when</th><th>logger</th><th>event</th>
      </tr></thead><tbody>
      ${errs.slice(0, 10).map(e => `
        <tr><td class="mute">${(e.ts || '').slice(0, 19)}</td>
        <td class="mute">${(e.logger || '').replace('apps.bot.', '')}</td>
        <td class="bad">${e.event || ''}</td>
        </tr>`).join('')}
      </tbody></table>`;
  }

  // Regime comparison (net R by entry coefficient × asset)
  const reg = s.regimes || {};
  const regAssets = reg.per_asset || [];
  if (!regAssets.length) {
    document.getElementById('regimes').innerHTML =
      `<div class="mute">sim pending…</div>`;
  } else {
    const coefs = reg.coefficients || ['0.941', '0.882', '0.786'];
    const head = `<tr><th>asset</th>` + coefs.map(c => `
      <th colspan="3" style="text-align:center">entry ${c}</th>`).join('') + `</tr>
      <tr><th></th>` + coefs.map(() => `
      <th>trades</th><th>net R</th><th>win%</th>`).join('') + `</tr>`;
    const totalsByCoef = {};
    coefs.forEach(c => totalsByCoef[c] = {triggered: 0, total_r: 0, wins: 0});
    const rows = regAssets.map(a => {
      const cells = coefs.map(c => {
        const r = (a.regimes && a.regimes[c]) || {triggered: 0, total_r: 0, win_rate: 0};
        totalsByCoef[c].triggered += r.triggered || 0;
        totalsByCoef[c].total_r += r.total_r || 0;
        totalsByCoef[c].wins += r.wins || 0;
        const rCls = (r.total_r || 0) > 0 ? 'good'
                   : (r.total_r || 0) < 0 ? 'bad' : 'mute';
        return `<td class="v">${r.triggered || 0}</td>
          <td class="v ${rCls}">${(r.total_r || 0) >= 0 ? '+' : ''}${fmt(r.total_r || 0)}</td>
          <td class="v">${r.triggered ? Math.round((r.wins || 0) / r.triggered * 100) : 0}%</td>`;
      }).join('');
      return `<tr><td><b>${a.asset}</b></td>${cells}</tr>`;
    }).join('');
    const totalsRow = `<tr style="border-top:2px solid #444">
      <td><b class="accent">TOTAL</b></td>` + coefs.map(c => {
      const t = totalsByCoef[c];
      const cls = t.total_r > 0 ? 'good' : t.total_r < 0 ? 'bad' : 'mute';
      const wr = t.triggered ? Math.round(t.wins / t.triggered * 100) : 0;
      return `<td class="v"><b>${t.triggered}</b></td>
        <td class="v ${cls}"><b>${t.total_r >= 0 ? '+' : ''}${fmt(t.total_r)}</b></td>
        <td class="v"><b>${wr}%</b></td>`;
    }).join('') + `</tr>`;
    document.getElementById('regimes').innerHTML = `
      <div class="mute" style="margin-bottom:8px">
        ${reg.window_bars || '?'}-bar window across ${regAssets.length} assets
      </div>
      <table>
        <thead>${head}</thead>
        <tbody>${rows}${totalsRow}</tbody>
      </table>`;
  }

  // All setups
  const setups = s.recent_setups || [];
  document.getElementById('setups').innerHTML = `
    <table><thead><tr>
      <th>asset</th><th>dir</th><th>parent_ts</th><th>term_ts</th>
      <th>parent</th><th>term</th><th>state</th><th>R</th>
    </tr></thead><tbody id="setups-tbody">
    ${setups.map(s => `
      <tr data-key="${s.setup_key}"><td>${s.asset}</td>
      <td>${s.direction}</td>
      <td class="mute">${s.parent_ts}</td>
      <td class="mute">${s.term_ts}</td>
      <td class="v">${fmt(s.parent_price)}</td>
      <td class="v">${fmt(s.term_price)}</td>
      <td><span class="pill ${s.state || 'detected'}">
        ${s.state || 'detected'}</span></td>
      <td class="v">${s.realized_r != null ? fmt(s.realized_r) : ''}</td>
      </tr>`).join('')}
    </tbody></table>`;
  // Wire row clicks for the chart panel.
  document.querySelectorAll('#setups-tbody tr').forEach(tr => {
    const key = tr.dataset.key;
    const setup = setups.find(x => x.setup_key === key);
    if (setup) wireSetupRow(tr, setup);
  });
  // Re-highlight active row after refresh (DOM was rebuilt).
  if (_activeSetupKey) {
    const active = document.querySelector(
      `tr.setup-row[data-key="${_activeSetupKey}"]`);
    if (active) active.classList.add('active');
  }
}

// --- Chart panel (TradingView embed) -----------------------------------

let _activeSetupKey = null;
let _followScroll = false;
let _scrollDebounce = null;

function openChart(setup) {
  if (!setup) return;
  if (_activeSetupKey === setup.setup_key) return;
  _activeSetupKey = setup.setup_key;
  const panel = document.getElementById('chart-panel');
  panel.classList.add('open');
  document.body.classList.add('has-chart-panel');
  // Re-build the iframe so TV reloads with the new symbol cleanly.
  const wrap = document.getElementById('chart-iframe-wrap');
  const sym = encodeURIComponent(setup.tv_symbol || setup.asset);
  const url = `https://www.tradingview.com/widgetembed/?symbol=${sym}`
    + '&interval=60&hidesidetoolbar=0&theme=dark&style=1'
    + '&timezone=Etc/UTC&withdateranges=1&allow_symbol_change=0';
  wrap.innerHTML = `<iframe src="${url}" allowfullscreen></iframe>`;

  // Numeric levels overlay.
  const meta = document.getElementById('chart-meta');
  const title = document.getElementById('chart-title');
  title.textContent = `${setup.asset} · ${setup.direction.toUpperCase()}`
    + ` · ${setup.state || 'detected'}`;
  document.getElementById('chart-current').textContent =
    `${setup.asset} ${setup.parent_ts} → ${setup.term_ts}`;
  const lvl = setup.levels;
  const lines = [
    `<div class="lvl"><span>parent</span><b>${fmt(setup.parent_price)}</b></div>`,
    `<div class="lvl"><span>terminal</span><b>${fmt(setup.term_price)}</b></div>`,
  ];
  if (lvl) {
    lines.push(
      `<div class="lvl"><span>entry (0.941)</span><b class="good">${fmt(lvl.entry)}</b></div>`,
      `<div class="lvl"><span>init SL (1.05)</span><b class="bad">${fmt(lvl.init_sl)}</b></div>`,
      `<div class="lvl"><span>TP1 (0.882)</span><b>${fmt(lvl.tp1)} · ${fmt(lvl.r_tp1)}R</b></div>`,
      `<div class="lvl"><span>TP2 (0.5)</span><b>${fmt(lvl.tp2)} · ${fmt(lvl.r_tp2)}R</b></div>`,
      `<div class="lvl"><span>TP3 (0.0)</span><b>${fmt(lvl.tp3)} · ${fmt(lvl.r_tp3)}R</b></div>`,
      `<div class="lvl mute" style="margin-top:8px"><span>risk_per_unit</span><b>${fmt(lvl.risk_per_unit)}</b></div>`,
    );
  } else {
    lines.push('<div class="mute" style="margin-top:8px">degenerate leg — no levels</div>');
  }
  document.getElementById('chart-levels').innerHTML = lines.join('');

  // Active-row highlight in the setups table.
  document.querySelectorAll('tr.setup-row.active')
    .forEach(el => el.classList.remove('active'));
  const row = document.querySelector(
    `tr.setup-row[data-key="${setup.setup_key}"]`);
  if (row) row.classList.add('active');
}

function closeChart() {
  _activeSetupKey = null;
  document.getElementById('chart-panel').classList.remove('open');
  document.body.classList.remove('has-chart-panel');
  document.querySelectorAll('tr.setup-row.active')
    .forEach(el => el.classList.remove('active'));
}

function wireSetupRow(tr, setup) {
  tr.classList.add('setup-row');
  tr.dataset.key = setup.setup_key;
  tr._setup = setup;
  tr.addEventListener('click', () => openChart(setup));
}

function _maybeFollowScroll() {
  if (!_followScroll) return;
  clearTimeout(_scrollDebounce);
  _scrollDebounce = setTimeout(() => {
    // Pick the setup row whose center is closest to the viewport center
    // ABOVE the chart panel (panel sits at the bottom).
    const rows = document.querySelectorAll('tr.setup-row');
    if (!rows.length) return;
    const panel = document.getElementById('chart-panel');
    const panelTop = panel.classList.contains('open')
      ? panel.getBoundingClientRect().top
      : window.innerHeight;
    const focus = panelTop * 0.5;  // halfway up the visible area
    let best = null, bestDist = Infinity;
    rows.forEach(r => {
      const b = r.getBoundingClientRect();
      const c = (b.top + b.bottom) / 2;
      const d = Math.abs(c - focus);
      if (d < bestDist) { bestDist = d; best = r; }
    });
    if (best && best._setup) openChart(best._setup);
  }, 600);
}

document.getElementById('follow-scroll').addEventListener('change', e => {
  _followScroll = e.target.checked;
  if (_followScroll) _maybeFollowScroll();
});
window.addEventListener('scroll', _maybeFollowScroll, {passive: true});

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def _build_counterfactual(
    universe: tuple[str, ...],
    rest_url: str,
    ws_url: str,
    strategy_cfg,
) -> dict[str, Any]:
    """Run the would-be-running sim with the operator's config.

    Heavy (fetches REST + runs detector for each asset). Cached 60s in the
    caller so dashboard auto-refresh doesn't hammer HL. Respects:
      * universe (config.universe — may be a subset of DEFAULT_UNIVERSE)
      * rest_url (mainnet vs testnet)
      * strategy_cfg (entry / TP / SL coefficients tuned by the operator)
    """
    from apps.bot.exchange.hyperliquid import HyperliquidPublicClient
    from apps.bot.marketdata import hl_to_worker_candle
    from apps.bot.strategy.fsm import FibFSM, FsmState, Setup
    from apps.worker.discovery_bet_1.atr import calculate_atr14
    from apps.worker.discovery_bet_1.swing_detector import clean_legs

    client = HyperliquidPublicClient(rest_url=rest_url, ws_url=ws_url)
    interval_ms = 3_600_000
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 200 * interval_ms
    cfg = strategy_cfg
    per_asset: list[dict] = []
    grand_open = 0
    for asset in universe:
        try:
            raw = client.candle_snapshot(asset, "1h", start_ms, end_ms)
        except Exception as exc:
            per_asset.append({"asset": asset, "error": str(exc)})
            continue
        candles = [hl_to_worker_candle(c) for c in raw]
        atr = calculate_atr14(candles)
        legs = clean_legs(candles, atr, None, min_bars=6, mult=2.0)
        armed_n = missed_n = 0
        open_now: list[dict] = []
        for i, leg in enumerate(legs):
            if i + 1 >= len(legs):
                continue
            term_idx = leg["term_idx"]
            arm_idx = legs[i + 1]["parent_idx"]
            setup = Setup(
                asset=asset, direction=leg["direction"],
                parent_ts=leg["parent_ts"],
                parent_price=float(leg["parent_price"]),
                term_ts=leg["term_ts"],
                term_price=float(leg["term_price"]),
            )
            fsm = FibFSM(setup, cfg)
            if fsm.state == FsmState.DEGENERATE:
                continue
            for c in candles[term_idx + 1: arm_idx + 1]:
                fsm.on_bar(c)
                if fsm.finished or fsm.state != FsmState.ARMED:
                    break
            if fsm.finished or fsm.state != FsmState.ARMED:
                missed_n += 1
                continue
            armed_n += 1
            for c in candles[arm_idx + 1:]:
                if fsm.finished:
                    break
                fsm.on_bar(c)
            if not fsm.finished:
                open_now.append({
                    "fsm_state": fsm.state.value,
                    "direction": setup.direction,
                    "parent_ts": setup.parent_ts,
                    "term_ts": setup.term_ts,
                    "realized_r": fsm.realized_r,
                })
        per_asset.append({
            "asset": asset, "legs": len(legs),
            "armed": armed_n, "missed": missed_n,
            "open": open_now,
        })
        grand_open += len(open_now)
    return {
        "per_asset": per_asset,
        "total_open": grand_open,
        "window_bars": 200,
        "as_of_ms": int(time.time() * 1000),
    }


def _build_regimes(
    universe: tuple[str, ...],
    rest_url: str,
    ws_url: str,
    base_strategy_cfg,
) -> dict[str, Any]:
    """Per-asset net R for each entry-coefficient regime.

    PRD §3 / scripts/execute_fib_strategy.REGIMES — three sniper regimes
    (0.941, 0.882, 0.786). For each detected leg over the window, runs
    the simulator under each regime and tallies trades / net R / win rate
    per (asset, regime). Cached 120s.

    Notes: "win" = any non-wipeout terminal that triggered (TP1+ scratch
    or full TP3 counts; matches the review-label semantics from
    feedback/db1_review_label_semantics.md).
    """
    from dataclasses import replace as _replace

    from apps.bot.exchange.hyperliquid import HyperliquidPublicClient
    from apps.bot.marketdata import hl_to_worker_candle
    from apps.bot.simulation.paper_executor import simulate_setup
    from apps.worker.discovery_bet_1.atr import calculate_atr14
    from apps.worker.discovery_bet_1.swing_detector import clean_legs

    # The three regimes baked into the executor. We mirror them locally
    # so the dashboard doesn't depend on scripts/.
    regime_specs = [
        {
            "label": "0.941",
            "cfg": _replace(
                base_strategy_cfg,
                entry_coeff=0.941, init_sl_coeff=1.05,
                tp1_coeff=0.882, tp2_coeff=0.5, tp3_coeff=0.0,
            ),
        },
        {
            "label": "0.882",
            "cfg": _replace(
                base_strategy_cfg,
                entry_coeff=0.882, init_sl_coeff=1.05,
                tp1_coeff=0.786, tp2_coeff=0.5, tp3_coeff=0.0,
            ),
        },
        {
            "label": "0.786",
            "cfg": _replace(
                base_strategy_cfg,
                entry_coeff=0.786, init_sl_coeff=1.05,
                tp1_coeff=0.618, tp2_coeff=0.382, tp3_coeff=0.0,
            ),
        },
    ]
    TRADED_STATUSES = {
        "wipeout", "tp1_then_scratch", "tp2_then_scratch", "tp3_full",
    }
    WIN_STATUSES = {
        "tp1_then_scratch", "tp2_then_scratch", "tp3_full",
    }

    client = HyperliquidPublicClient(rest_url=rest_url, ws_url=ws_url)
    interval_ms = 3_600_000
    window_bars = 500
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - window_bars * interval_ms

    per_asset: list[dict] = []
    for asset in universe:
        try:
            raw = client.candle_snapshot(asset, "1h", start_ms, end_ms)
        except Exception as exc:
            per_asset.append({"asset": asset, "error": str(exc)})
            continue
        candles = [hl_to_worker_candle(c) for c in raw]
        if len(candles) < 50:
            per_asset.append({"asset": asset, "regimes": {}})
            continue
        atr = calculate_atr14(candles)
        legs = clean_legs(candles, atr, None, min_bars=6, mult=2.0)
        idx = {c.source_timestamp: i for i, c in enumerate(candles)}

        regime_results: dict[str, dict] = {}
        for spec in regime_specs:
            triggered = wins = 0
            total_r = 0.0
            for leg in legs:
                leg_with_asset = {**leg, "asset": asset}
                out = simulate_setup(leg_with_asset, candles, idx, spec["cfg"])
                status = out["status"]
                if status in TRADED_STATUSES:
                    triggered += 1
                    total_r += float(out.get("r") or 0.0)
                    if status in WIN_STATUSES:
                        wins += 1
            regime_results[spec["label"]] = {
                "triggered": triggered,
                "wins": wins,
                "total_r": total_r,
                "win_rate": (wins / triggered) if triggered else 0.0,
                "avg_r": (total_r / triggered) if triggered else 0.0,
            }
        per_asset.append({"asset": asset, "regimes": regime_results})

    return {
        "per_asset": per_asset,
        "coefficients": [s["label"] for s in regime_specs],
        "window_bars": window_bars,
        "as_of_ms": int(time.time() * 1000),
    }


def _build_exchange_state(rest_url: str) -> dict[str, Any] | None:
    """If HL agent + master env are present, return open orders + positions.

    Read-only — only the Info endpoints; never constructs Exchange writes.
    Cached 30s. Returns None when credentials aren't set (card hidden).
    Uses the operator's configured rest_url so testnet works.
    """
    if (hl_agent_private_key() is None
            or os.environ.get("PHOENIX_HL_ACCOUNT_ADDRESS") is None):
        return None
    from apps.bot.exchange.signed_client import SignedHyperliquidClient

    try:
        client = SignedHyperliquidClient(
            agent_private_key=hl_agent_private_key(),
            master_account_address=os.environ["PHOENIX_HL_ACCOUNT_ADDRESS"],
            rest_url=rest_url,
        )
        orders = client.open_orders()
        positions = client.positions()
        return {
            "open_orders": [
                {"coin": o.coin, "side": o.side, "qty": o.qty,
                 "price": o.price, "reduce_only": o.reduce_only,
                 "cloid": o.cloid, "oid": o.oid}
                for o in orders
            ],
            "positions": [
                {"coin": p.coin, "size": p.size, "entry_px": p.entry_px,
                 "unrealized_pnl": p.unrealized_pnl}
                for p in positions
            ],
            "agent_approved": client.agent_is_approved(),
            "agent_address": client.agent_address,
            "master_address": client.master_address,
        }
    except Exception as exc:
        log.exception("exchange-state fetch failed")
        return {"error": str(exc)}


def _tail_errors(log_dir: Path, lines: int = 20) -> list[dict]:
    """Tail the bot's JSON log and return the last `lines` ERROR records."""
    path = log_dir / "bot.log"
    if not path.exists():
        return []
    out: list[dict] = []
    # Tail by scanning the last ~256KB; cheap enough at our log volume.
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - 256 * 1024))
            tail = fh.read().decode("utf-8", errors="replace")
    except Exception:
        log.exception("could not tail log file")
        return []
    for line in tail.splitlines()[-500:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("level") in ("ERROR", "CRITICAL"):
            out.append({
                "ts": rec.get("ts"), "event": rec.get("event"),
                "logger": rec.get("logger"),
                "extras": {k: v for k, v in rec.items()
                           if k not in ("ts", "level", "logger", "event")},
            })
    return out[-lines:]


# HL coin -> TradingView symbol. Matches the convention in
# scripts/place_fibs_tradingview.py (BITGET perp series).
# Override per-coin here if a different feed reads better on TV.
_TV_SYMBOL_FOR_COIN = {
    "BTC": "BITGET:BTCUSDT.P",
    "ETH": "BITGET:ETHUSDT.P",
    "BNB": "BITGET:BNBUSDT.P",
    "ADA": "BITGET:ADAUSDT.P",
    "XRP": "BITGET:XRPUSDT.P",
    "SOL": "BITGET:SOLUSDT.P",
    "HYPE": "BITGET:HYPEUSDT.P",
    "TRX": "BITGET:TRXUSDT.P",
}


def _tv_symbol_for(coin: str) -> str:
    return _TV_SYMBOL_FOR_COIN.get(coin, f"BITGET:{coin}USDT.P")


def _setup_levels(parent_price: float, term_price: float,
                   direction: str, strategy_cfg) -> dict | None:
    """Compute Fib levels for a setup so the dashboard can show them
    alongside the TV chart. Returns None if the setup is degenerate."""
    levels = compute_levels(
        parent_price=float(parent_price),
        term_price=float(term_price),
        direction=direction,
        cfg=strategy_cfg,
    )
    if levels.degenerate:
        return None
    return {
        "entry": levels.entry,
        "init_sl": levels.init_sl,
        "tp1": levels.tp1,
        "tp2": levels.tp2,
        "tp3": levels.tp3,
        "risk_per_unit": levels.risk_per_unit,
        "r_tp1": levels.risk_to_tp1,
        "r_tp2": levels.risk_to_tp2,
        "r_tp3": levels.risk_to_tp3,
    }


def _build_state_payload(store: StateStore, cfg: BotConfig,
                          log_dir: Path | None = None) -> dict[str, Any]:
    risk_cfg = cfg.risk
    engine = RiskEngine(store=store, risk_cfg=risk_cfg)
    snap = engine.status_snapshot()
    setups = store.list_setups(limit=50)
    out_setups: list[dict] = []
    for rec in setups:
        state = store.get_state(rec.setup_key)
        realized_r = None
        state_name = state.state if state else None
        if state and state.payload and "realized_r" in state.payload:
            realized_r = state.payload.get("realized_r")
        out_setups.append({
            "setup_key": rec.setup_key,
            "asset": rec.asset,
            "direction": rec.direction,
            "parent_ts": rec.parent_ts,
            "parent_price": rec.parent_price,
            "term_ts": rec.term_ts,
            "term_price": rec.term_price,
            "state": state_name,
            "realized_r": realized_r,
            "tv_symbol": _tv_symbol_for(rec.asset),
            "levels": _setup_levels(
                rec.parent_price, rec.term_price, rec.direction,
                cfg.strategy,
            ),
        })

    in_flight = [
        s for s in out_setups
        if s["state"] in ("armed", "entered", "tp1_hit", "tp2_hit")
    ]
    funding_flags = store.list_flags_prefix(FUNDING_OBS_PREFIX)
    funding_apy = {
        k[len(FUNDING_OBS_PREFIX):]: v
        for k, v in funding_flags.items()
    }
    paused_flags = store.list_flags_prefix(FUNDING_SKIP_PREFIX)
    snap["paused_assets"] = sorted(
        k[len(FUNDING_SKIP_PREFIX):] for k in paused_flags
    )

    payload = {
        "risk": snap,
        "in_flight_setups": in_flight,
        "recent_setups": out_setups,
        "funding_apy": funding_apy,
        "kill_events": store.list_kill_events(limit=8),
    }

    # Optional cards — each wrapped so one card's failure does not break
    # the whole dashboard response.
    def _safe(key: str, ttl: float, build_fn):
        try:
            return _cached(key, ttl, build_fn)
        except Exception as exc:
            log.exception("dashboard card %s build failed", key)
            return {"error": str(exc)}

    payload["counterfactual"] = _safe(
        "counterfactual", 60.0,
        lambda: _build_counterfactual(
            universe=cfg.universe,
            rest_url=cfg.hyperliquid.rest_url,
            ws_url=cfg.hyperliquid.ws_url,
            strategy_cfg=cfg.strategy,
        ),
    )
    payload["regimes"] = _safe(
        "regimes", 120.0,
        lambda: _build_regimes(
            universe=cfg.universe,
            rest_url=cfg.hyperliquid.rest_url,
            ws_url=cfg.hyperliquid.ws_url,
            base_strategy_cfg=cfg.strategy,
        ),
    )
    payload["exchange_state"] = _safe(
        "exchange_state", 30.0,
        lambda: _build_exchange_state(rest_url=cfg.hyperliquid.rest_url),
    )
    try:
        payload["recent_errors"] = (
            _tail_errors(log_dir) if log_dir else []
        )
    except Exception as exc:
        log.exception("recent_errors tail failed")
        payload["recent_errors"] = []
        payload["recent_errors_error"] = str(exc)

    return payload


def make_handler(store: StateStore, cfg: BotConfig,
                 log_dir: Path | None = None):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quieter console
            return

        def _send(self, code: int, body: bytes,
                  content_type: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(
                    200, _INDEX_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                return
            if self.path == "/api/state":
                try:
                    payload = _build_state_payload(
                        store, cfg, log_dir=log_dir,
                    )
                except Exception as exc:
                    log.exception("dashboard /api/state failed")
                    self._send(
                        500,
                        json.dumps({"error": str(exc)}).encode("utf-8"),
                    )
                    return
                self._send(
                    200,
                    json.dumps(payload, default=str).encode("utf-8"),
                )
                return
            self._send(404, b'{"error":"not found"}')

    return _Handler


def serve(
    store: StateStore,
    cfg: BotConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 9101,
    open_browser: bool = False,
    log_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Start the dashboard on its own thread. Returns the server object so
    callers can call `shutdown()` to stop it."""
    handler_cls = make_handler(store, cfg, log_dir=log_dir)
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever, name="bot-dashboard", daemon=True,
    )
    thread.start()
    log.info("dashboard serving",
             extra={"host": host, "port": port,
                    "url": f"http://{host}:{port}"})
    if open_browser:
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass
    return server
