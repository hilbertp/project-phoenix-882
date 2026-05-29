#!/usr/bin/env python
"""Build a self-contained HTML dashboard to assess DB1 trade-regime results.

Scores the human-endorsed setup set (data/discovery_bet_1/human_labels.jsonl:
accept -> original, adjust -> corrected, add -> missed; rejects excluded) under
each regime in REGIMES and renders one offline HTML file with KPI cards, an
equity curve, outcome + reach charts, a long/short split, and a per-setup table.

Output: artifacts/discovery_bet_1/dashboard.html  (open it in any browser).
"""
from __future__ import annotations

import sys
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candle_input
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_REJECT,
    latest_by_key,
    load_labels,
)
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.execute_fib_strategy import REGIMES, execute

OUT = REPO_ROOT / "artifacts" / "discovery_bet_1" / "dashboard.html"

# status -> outcome kind. triggered = anything not shrug. The scaled strategy adds
# be_scratch (recovered to break-even, no TP -> 0R) mapped to its own "even" kind.
KIND = {
    "no_trigger": "shrug", "no_entry": "shrug", "degenerate": "shrug",
    "wipeout": "loss",
    "tp1_then_scratch": "scratch",
    "tp2_then_scratch": "partial",
    "tp3_full": "win",
    "open": "open",
    "be_scratch": "even",       # scaled: recovered to break-even, no TP
    "tp_then_scratch": "partial",  # scaled: reached a partial TP then break-even
    "tp_full": "win",            # scaled: full target
}
KIND_LABEL = {
    "win": "WIN — full target", "partial": "partial — TP then BE",
    "scratch": "scratch — TP1 then BE", "loss": "LOSS — stopped",
    "shrug": "shrug — no entry", "open": "open — live",
    "even": "break-even (0R)",
}
COLOR = {
    "win": "#26a69a", "partial": "#66bb6a", "scratch": "#f0b90b",
    "loss": "#ef5350", "shrug": "#6b7785", "open": "#2962ff", "even": "#8893a7",
}
VERDICT_COLOR = {
    "accept": "#26a69a", "adjust": "#f0b90b", "add": "#8957e5",
    "reject": "#ef5350",
}


def _truth_with_verdict() -> list[dict]:
    """Human-endorsed setups carrying their verdict (rejects excluded)."""
    out: list[dict] = []
    for label in latest_by_key(load_labels()).values():
        if label.verdict == VERDICT_REJECT:
            continue
        if label.corrected:
            s = dict(label.corrected)
        else:
            s = {
                "direction": label.direction,
                "parent_ts": label.parent_ts, "parent_price": label.parent_price,
                "term_ts": label.term_ts, "term_price": label.term_price,
            }
        s["verdict"] = label.verdict
        out.append(s)
    out.sort(key=lambda s: s["term_ts"])
    return out


def _fmt_ts(ts: str) -> str:
    return f"{ts[5:7]}-{ts[8:10]} {ts[11:13]}h"


def build_rows(candles, idx, atr, setups, regime) -> list[dict]:
    rows: list[dict] = []
    for n, s in enumerate(setups, start=1):
        if s["term_ts"] not in idx:
            continue
        res = execute(candles, idx, s, **regime)
        kind = KIND.get(res["status"], "open")
        span = abs(s["term_price"] - s["parent_price"])
        a = atr[idx[s["term_ts"]]] or 0.0
        rows.append({
            "n": n,
            "id": f"S{n:02d}",
            "direction": s["direction"],
            "parent_ts": s["parent_ts"], "term_ts": s["term_ts"],
            "span": span,
            "depth": (span / a) if a else 0.0,
            "verdict": s.get("verdict", ""),
            "status": res["status"], "kind": kind, "r": res["r"],
        })
    return rows


def aggregate(rows) -> dict:
    triggered = [r for r in rows if r["kind"] != "shrug"]
    n = len(triggered)
    win_rows = [r for r in triggered if r["kind"] in ("scratch", "partial", "win")
                or (r["kind"] == "open" and r["r"] > 0)]
    loss_rows = [r for r in triggered if r["kind"] == "loss"]
    wins = len(win_rows)
    losses = len(loss_rows)
    opens = sum(1 for r in triggered if r["kind"] == "open" and r["r"] <= 0)
    reach_tp1 = wins
    reach_tp2 = sum(1 for r in triggered if r["kind"] in ("partial", "win"))
    reach_tp3 = sum(1 for r in triggered if r["kind"] == "win")
    total_r = sum(r["r"] for r in triggered)

    # Realized payoff: avg R captured by a winner vs avg R given up by a loser.
    # breakeven win rate = 1 / (1 + payoff): the hit rate this R:R needs to net 0.
    avg_win = (sum(r["r"] for r in win_rows) / wins) if wins else 0.0
    avg_loss = (sum(r["r"] for r in loss_rows) / losses) if losses else -1.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss else avg_win
    breakeven_wr = (1.0 / (1.0 + payoff)) if payoff > 0 else None

    def dir_split(d):
        sub = [r for r in triggered if r["direction"] == d]
        w = sum(1 for r in sub if r["kind"] in ("scratch", "partial", "win"))
        return {"n": len(sub), "wins": w, "r": sum(r["r"] for r in sub)}

    return {
        "n": n, "wins": wins, "losses": losses, "opens": opens,
        "shrug": sum(1 for r in rows if r["kind"] == "shrug"),
        "reach_tp1": reach_tp1, "reach_tp2": reach_tp2, "reach_tp3": reach_tp3,
        "total_r": total_r, "avg_r": (total_r / n) if n else 0.0,
        "win_rate": (wins / n) if n else 0.0,
        "loss_rate": (losses / n) if n else 0.0,
        "avg_win": avg_win, "avg_loss": avg_loss, "payoff": payoff,
        "breakeven_wr": breakeven_wr,
        "long": dir_split("up"), "short": dir_split("down"),
        "counts": Counter(r["kind"] for r in rows),
    }


def rr_targets(regime) -> dict:
    """Geometric reward:risk to each target (constant per regime, per 1R risked)."""
    risk = abs(regime["entry_c"] - regime["init_sl_c"])
    return {
        "tp1": abs(regime["entry_c"] - regime["be_trig_c"]) / risk,
        "tp2": abs(regime["entry_c"] - regime["tp2_c"]) / risk,
        "tp3": abs(regime["entry_c"] - regime["tp3_c"]) / risk,
    }


# --------------------------------------------------------------------------- #
# SVG charts (hand-rolled, no external deps)
# --------------------------------------------------------------------------- #
def _svg_equity(triggered, w=820, h=240) -> str:
    cum, run = [], 0.0
    for r in triggered:
        run += r["r"]
        cum.append(run)
    pts = [0.0] + cum
    n = len(pts)
    lo, hi = min(pts + [0.0]), max(pts + [0.0])
    if hi == lo:
        hi = lo + 1.0
    pl, pr, pt, pb = 46, 16, 16, 24
    iw, ih = w - pl - pr, h - pt - pb

    def X(i):
        return pl + iw * (i / ((n - 1) or 1))

    def Y(v):
        return pt + ih * (1 - (v - lo) / (hi - lo))

    zy = Y(0.0)
    poly = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(pts))
    area = f"{X(0):.1f},{zy:.1f} {poly} {X(n - 1):.1f},{zy:.1f}"
    final = pts[-1]
    col = COLOR["win"] if final >= 0 else COLOR["loss"]
    grid = "".join(
        f'<line x1="{pl}" y1="{Y(v):.1f}" x2="{w - pr}" y2="{Y(v):.1f}" '
        f'stroke="#2a3142" stroke-width="1"/>'
        f'<text x="{pl - 6}" y="{Y(v) + 3:.1f}" fill="#6b7785" font-size="10" '
        f'text-anchor="end">{v:+.1f}R</text>'
        for v in (hi, 0.0, lo)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none">'
        f'{grid}'
        f'<line x1="{pl}" y1="{zy:.1f}" x2="{w - pr}" y2="{zy:.1f}" '
        f'stroke="#3a4256" stroke-width="1.2"/>'
        f'<polygon points="{area}" fill="{col}" fill-opacity="0.10"/>'
        f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="2"/>'
        f'<circle cx="{X(n - 1):.1f}" cy="{Y(final):.1f}" r="3.5" fill="{col}"/>'
        f'<text x="{X(n - 1) - 4:.1f}" y="{Y(final) - 8:.1f}" fill="{col}" '
        f'font-size="12" font-weight="700" text-anchor="end">{final:+.2f}R</text>'
        f'</svg>'
    )


def _svg_hbars(items, w=380, rowh=26, gap=10, pl=92, pr=46) -> str:
    maxv = max([v for _, v, _ in items] + [1])
    h = len(items) * (rowh + gap) + gap
    body = []
    for k, (label, v, col) in enumerate(items):
        y = gap + k * (rowh + gap)
        bw = (w - pl - pr) * (v / maxv) if maxv else 0
        body.append(
            f'<text x="{pl - 8}" y="{y + rowh * 0.68:.0f}" fill="#9aa4b2" '
            f'font-size="11" text-anchor="end">{label}</text>'
            f'<rect x="{pl}" y="{y}" width="{max(bw, 1):.1f}" height="{rowh}" '
            f'rx="4" fill="{col}"/>'
            f'<text x="{pl + max(bw, 1) + 6:.1f}" y="{y + rowh * 0.68:.0f}" '
            f'fill="#d1d4dc" font-size="11" font-weight="600">{v}</text>'
        )
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{"".join(body)}</svg>'


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _kpi(label, value, sub, color="#d1d4dc") -> str:
    return (
        f'<div class="kpi"><div class="kpi-v" style="color:{color}">{value}</div>'
        f'<div class="kpi-l">{label}</div><div class="kpi-s">{sub}</div></div>'
    )


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _panel(slug, label, regime, rows, agg, active) -> str:
    triggered = [r for r in rows if r["kind"] != "shrug"]
    rr = rr_targets(regime)
    reg_txt = " &nbsp;|&nbsp; ".join(
        f"{k.replace('_c', '').replace('_', ' ')} {v}" for k, v in regime.items()
    )
    be = agg["breakeven_wr"]
    beats_be = be is not None and agg["win_rate"] > be
    kpis = "".join([
        _kpi("Win rate", _pct(agg["win_rate"]),
             f"{agg['wins']}/{agg['n']} triggered", COLOR["win"]),
        _kpi("Loss rate", _pct(agg["loss_rate"]),
             f"{agg['losses']}/{agg['n']}", COLOR["loss"]),
        _kpi("Avg R / trade", f"{agg['avg_r']:+.3f}",
             "blended expectancy",
             COLOR["win"] if agg["avg_r"] >= 0 else COLOR["loss"]),
        _kpi("R:R &rarr; TP3", f"{rr['tp3']:.1f}R",
             "max reward per 1R", COLOR["win"]),
        _kpi("Avg winner", f"{agg['avg_win']:+.2f}R",
             f"of {rr['tp3']:.1f}R available",
             COLOR["win"] if agg["avg_win"] > 0 else "#6b7785"),
        _kpi("Break-even WR", _pct(be) if be is not None else "n/a",
             "actual " + _pct(agg["win_rate"]),
             COLOR["win"] if beats_be else COLOR["loss"]),
        _kpi("Total R", f"{agg['total_r']:+.1f}",
             f"over {agg['n']} trades",
             COLOR["win"] if agg["total_r"] >= 0 else COLOR["loss"]),
        _kpi("Triggered", str(agg["n"]), f"{agg['shrug']} shrug excluded", "#2962ff"),
    ])

    rr_card = (
        '<div class="card"><h3>Reward : risk to targets '
        '<span class="muted">(per 1R risked)</span></h3>'
        f'<div class="rr"><span>&rarr; TP1 ({regime["be_trig_c"]})</span>'
        f'<b>{rr["tp1"]:.2f}R</b></div>'
        f'<div class="rr"><span>&rarr; TP2 ({regime["tp2_c"]})</span>'
        f'<b>{rr["tp2"]:.2f}R</b></div>'
        f'<div class="rr"><span>&rarr; TP3 ({regime["tp3_c"]})</span>'
        f'<b style="color:{COLOR["win"]}">{rr["tp3"]:.2f}R</b></div>'
        f'<div class="rr cap"><span>avg winner captured</span>'
        f'<b>{agg["avg_win"]:+.2f}R</b></div></div>'
    )
    exp_card = (
        '<div class="card"><h3>Expectancy math</h3>'
        f'<div class="rr"><span>payoff (avg win : avg loss)</span>'
        f'<b>{agg["payoff"]:.2f} : 1</b></div>'
        f'<div class="rr"><span>break-even win rate needed</span>'
        f'<b>{_pct(be) if be is not None else "n/a"}</b></div>'
        f'<div class="rr"><span>actual win rate</span>'
        f'<b style="color:{COLOR["win"] if beats_be else COLOR["loss"]}">'
        f'{_pct(agg["win_rate"])}</b></div>'
        f'<div class="rr cap"><span>'
        f'{"above break-even" if beats_be else "below break-even"}</span>'
        f'<b style="color:{COLOR["win"] if agg["avg_r"] >= 0 else COLOR["loss"]}">'
        f'{agg["avg_r"]:+.3f}R</b></div></div>'
    )

    outcome_bars = _svg_hbars([
        ("WIN", agg["counts"].get("win", 0), COLOR["win"]),
        ("partial", agg["counts"].get("partial", 0), COLOR["partial"]),
        ("scratch", agg["counts"].get("scratch", 0), COLOR["scratch"]),
        ("LOSS", agg["counts"].get("loss", 0), COLOR["loss"]),
        ("shrug", agg["counts"].get("shrug", 0), COLOR["shrug"]),
    ])
    reach_bars = _svg_hbars([
        ("≥ TP1", agg["reach_tp1"], COLOR["win"]),
        ("≥ TP2", agg["reach_tp2"], COLOR["partial"]),
        ("TP3", agg["reach_tp3"], COLOR["scratch"]),
    ])

    def dir_block(name, d):
        wr = (d["wins"] / d["n"]) if d["n"] else 0.0
        return (
            f'<div class="dir"><div class="dir-h">{name}</div>'
            f'<div class="dir-r"><b>{_pct(wr)}</b> win</div>'
            f'<div class="dir-s">{d["wins"]}/{d["n"]} &middot; '
            f'{d["r"]:+.1f}R</div></div>'
        )

    trs = []
    for r in rows:
        dcol = COLOR["win"] if r["direction"] == "up" else COLOR["loss"]
        vcol = VERDICT_COLOR.get(r["verdict"], "#6b7785")
        ocol = COLOR.get(r["kind"], "#9aa4b2")
        rcol = COLOR["win"] if r["r"] > 0 else (COLOR["loss"] if r["r"] < 0 else "#6b7785")
        trs.append(
            f'<tr><td class="muted">{r["n"]}</td><td>{r["id"]}</td>'
            f'<td style="color:{dcol}">{"long" if r["direction"] == "up" else "short"}</td>'
            f'<td class="muted">{_fmt_ts(r["parent_ts"])} &rarr; {_fmt_ts(r["term_ts"])}</td>'
            f'<td>{r["span"]:.0f}</td><td>{r["depth"]:.1f}&times;</td>'
            f'<td style="color:{vcol}">{r["verdict"] or "&mdash;"}</td>'
            f'<td style="color:{ocol}">{KIND_LABEL.get(r["kind"], r["status"])}</td>'
            f'<td style="color:{rcol};text-align:right">{r["r"]:+.2f}</td></tr>'
        )

    return (
        f'<section class="panel" id="panel-{slug}" '
        f'style="{"" if active else "display:none"}">'
        f'<div class="reg">{reg_txt}</div>'
        f'<div class="kpis">{kpis}</div>'
        f'<div class="grid2">'
        f'<div class="card"><h3>Equity curve <span class="muted">'
        f'(cumulative R over {agg["n"]} triggered trades)</span></h3>'
        f'{_svg_equity(triggered)}</div>'
        f'{rr_card}'
        f'</div>'
        f'<div class="grid2">'
        f'{exp_card}'
        f'<div class="card dirs"><h3>By direction</h3>'
        f'{dir_block("Long", agg["long"])}{dir_block("Short", agg["short"])}</div>'
        f'</div>'
        f'<div class="grid2">'
        f'<div class="card"><h3>Outcome distribution</h3>{outcome_bars}</div>'
        f'<div class="card"><h3>Level reach <span class="muted">'
        f'(of {agg["n"]} triggered)</span></h3>{reach_bars}</div>'
        f'</div>'
        f'<div class="card"><h3>Every setup</h3>'
        f'<table><thead><tr><th>#</th><th>id</th><th>dir</th>'
        f'<th>parent &rarr; terminal</th><th>span</th><th>ATR</th>'
        f'<th>verdict</th><th>outcome</th><th>R</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table></div>'
        f'</section>'
    )


CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #0e1117; color: #d1d4dc;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 22px 60px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h3 { font-size: 13px; margin: 0 0 12px; font-weight: 600; color: #c7ccd6; }
.sub { color: #787b86; margin: 0 0 22px; font-size: 13px; }
.muted { color: #6b7785; font-weight: 400; }
.tabs { display: flex; gap: 8px; margin: 0 0 18px; }
.tab { background: #1c2230; color: #9aa4b2; border: 1px solid #2a3142;
  padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px;
  font-weight: 600; }
.tab.active { background: #2962ff; color: #fff; border-color: #2962ff; }
.compare { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px; margin: 0 0 22px; }
.cmp { background: #161b26; border: 1px solid #232a39; border-radius: 12px; padding: 16px 18px; }
.cmp h4 { margin: 0 0 10px; font-size: 13px; color: #c7ccd6; }
.cmp-row { display: flex; justify-content: space-between; padding: 3px 0;
  font-size: 13px; }
.cmp-row span:first-child { color: #787b86; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 12px; margin: 0 0 18px; }
.kpi { background: #161b26; border: 1px solid #232a39; border-radius: 12px;
  padding: 14px 14px 12px; }
.kpi-v { font-size: 23px; font-weight: 700; letter-spacing: -0.5px; }
.kpi-l { font-size: 12px; color: #c7ccd6; margin-top: 2px; font-weight: 600; }
.kpi-s { font-size: 11px; color: #6b7785; }
.rr { display: flex; justify-content: space-between; align-items: baseline;
  padding: 6px 0; font-size: 13px; border-bottom: 1px solid #1a2030; }
.rr span { color: #9aa4b2; }
.rr b { font-weight: 700; font-variant-numeric: tabular-nums; }
.rr.cap { border-bottom: none; margin-top: 8px; padding-top: 10px;
  border-top: 1px solid #2a3142; }
.rr.cap span { color: #c7ccd6; }
.grid2 { display: grid; grid-template-columns: 1.6fr 1fr; gap: 14px; margin: 0 0 14px; }
.card { background: #131722; border: 1px solid #232a39; border-radius: 12px; padding: 16px 18px; }
.reg { color: #787b86; font-size: 12px; margin: 0 0 14px; font-family: ui-monospace, monospace; }
.dirs { display: block; }
.dir { display: inline-block; width: 48%; vertical-align: top; }
.dir-h { color: #9aa4b2; font-size: 12px; }
.dir-r { font-size: 22px; font-weight: 700; }
.dir-s { font-size: 11px; color: #6b7785; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th { text-align: left; color: #6b7785; font-weight: 600; padding: 6px 8px;
  border-bottom: 1px solid #232a39; }
td { padding: 6px 8px; border-bottom: 1px solid #1a2030; }
tr:hover td { background: #161b26; }
"""

JS = """
function showRegime(slug, btn){
  document.querySelectorAll('.panel').forEach(p => p.style.display='none');
  document.getElementById('panel-'+slug).style.display='';
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
}
"""


def build_html(results) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n_setups = len(results[0][3])

    tabs = "".join(
        f'<button class="tab{" active" if i == 0 else ""}" '
        f'onclick="showRegime(\'{slug}\', this)">{label}</button>'
        for i, (slug, label, _, _, _) in enumerate(results)
    )

    cmps = []
    for slug, label, regime, rows, agg in results:
        cmps.append(
            f'<div class="cmp"><h4>{label}</h4>'
            f'<div class="cmp-row"><span>Win rate</span>'
            f'<span style="color:{COLOR["win"]};font-weight:700">'
            f'{_pct(agg["win_rate"])}</span></div>'
            f'<div class="cmp-row"><span>Loss rate</span>'
            f'<span style="color:{COLOR["loss"]};font-weight:700">'
            f'{_pct(agg["loss_rate"])}</span></div>'
            f'<div class="cmp-row"><span>Avg R / trade</span>'
            f'<span style="font-weight:700;color:'
            f'{COLOR["win"] if agg["avg_r"] >= 0 else COLOR["loss"]}">'
            f'{agg["avg_r"]:+.3f}R</span></div>'
            f'<div class="cmp-row"><span>Triggered (N)</span>'
            f'<span>{agg["n"]} <span class="muted">/ {agg["shrug"]} shrug</span>'
            f'</span></div></div>'
        )

    panels = "".join(
        _panel(slug, label, regime, rows, agg, active=(i == 0))
        for i, (slug, label, regime, rows, agg) in enumerate(results)
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>DB1 Results Dashboard</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>"
        "<h1>DB1 — Trade Regime Results</h1>"
        f"<p class='sub'>BITGET:BTCUSDT.P 1H &middot; {n_setups} human-endorsed "
        f"setups (accept + adjust-corrected + add) &middot; generated {now}</p>"
        f"<div class='compare'>{''.join(cmps)}</div>"
        f"<div class='tabs'>{tabs}</div>"
        f"{panels}"
        f"<script>{JS}</script>"
        "</div></body></html>"
    )


def main() -> None:
    candles = load_candle_input(DEFAULT_INPUT_PATH).candles
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    setups = _truth_with_verdict()

    results = []
    for reg in REGIMES:
        rows = build_rows(candles, idx, atr, setups, reg["params"])
        results.append((reg["slug"], reg["label"], reg["params"], rows, aggregate(rows)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_html(results), encoding="utf-8")
    print(f"WROTE {OUT}")
    for slug, label, regime, rows, agg in results:
        print(f"  {label}: win {agg['win_rate']:.0%} / loss {agg['loss_rate']:.0%} "
              f"/ {agg['avg_r']:+.3f}R over N={agg['n']}")
    if "--open" in sys.argv:
        webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
