#!/usr/bin/env python
"""Interactive DB1 review dashboard -- local server with a feedback API.

Serves a single-page app (scripts/dashboard_app.html) plus a small JSON API:

  GET  /api/state      regimes, every reviewed setup with its per-regime outcome
                       (status, R, fib levels, bar-by-bar events), the candle
                       window, and the scored aggregates.
  POST /api/feedback   append a human verdict to data/discovery_bet_1/human_labels.jsonl
                       (accept / reject(wtf) / adjust / add) and re-score on the
                       next /api/state poll.

No third-party deps (stdlib http.server). Run:

  .venv/bin/python scripts/dashboard_server.py [--port 8800] [--open]
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.candle_input import load_candles
from apps.worker.discovery_bet_1.human_labels import (
    VERDICT_REJECT,
    append_label,
    latest_by_key,
    load_labels,
    make_label,
    setup_key,
)
from apps.worker.discovery_bet_1.pivots import detect_local_pivots
from apps.worker.discovery_bet_1.run_generator import DEFAULT_INPUT_PATH
from scripts.build_dashboard import COLOR, KIND, KIND_LABEL, aggregate, rr_targets
from scripts.execute_fib_strategy import (
    REGIMES,
    SCALED_SL_C,
    SCALED_TRANCHES,
    run_regime,
)
from scripts.place_fibs_tradingview import _clean_legs

APP_HTML = Path(__file__).resolve().parent / "dashboard_app.html"
PAD_BARS = 48  # candles of context shown on each side of a setup

# The scaled multi-tranche strategy as a 4th regime alongside the single-entry ones.
SCALED_REGIME = {
    "slug": "scaled", "label": "Scaled 786/882/941", "scaled": True,
    "params": {"entries": "786:50% 882:25% 941:25%", "init sl": 1.05,
               "be": "blended", "TP1": "25% @0.618", "then": "trail SL, runner -> 0.0"},
}
REGIMES_ALL = REGIMES + [SCALED_REGIME]

# Asset catalog. BTC uses the human-reviewed setups (feedback-enabled); the others
# use raw detector output (no labels exist for them) at an adjustable granularity.
DATA_DIR = REPO_ROOT / "data" / "discovery_bet_1"


def _asset_csv(sym: str) -> Path:
    return DATA_DIR / f"bitget_{sym}_1h_last_12_months.csv"


ASSETS = {
    "btc": {"label": "BTC", "symbol": "BITGET:BTCUSDT.P", "csv": DEFAULT_INPUT_PATH,
            "source": "reviewed"},
    "ada": {"label": "ADA", "symbol": "BITGET:ADAUSDT.P", "csv": _asset_csv("adausdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
    "eth": {"label": "ETH", "symbol": "BITGET:ETHUSDT.P", "csv": _asset_csv("ethusdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
    "bnb": {"label": "BNB", "symbol": "BITGET:BNBUSDT.P", "csv": _asset_csv("bnbusdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
    "xrp": {"label": "XRP", "symbol": "BITGET:XRPUSDT.P", "csv": _asset_csv("xrpusdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
    "sol": {"label": "SOL", "symbol": "BITGET:SOLUSDT.P", "csv": _asset_csv("solusdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
    "hype": {"label": "HYPE", "symbol": "BITGET:HYPEUSDT.P", "csv": _asset_csv("hypeusdt_p"),
             "source": "detector", "min_bars": 6, "mult": 2.0},
    "trx": {"label": "TRX", "symbol": "BITGET:TRXUSDT.P", "csv": _asset_csv("trxusdt_p"),
            "source": "detector", "min_bars": 6, "mult": 2.0},
}


def detector_setups(candles, idx, atr, min_bars, mult) -> list[dict]:
    """Raw ATR-zigzag detector legs as setups (for assets with no human labels)."""
    piv = detect_local_pivots(candles)
    legs = [leg for leg in _clean_legs(candles, atr, piv, min_bars=min_bars, mult=mult)
            if leg["term_ts"] in idx]
    out = []
    for n, leg in enumerate(legs, start=1):
        out.append({
            "key": setup_key(leg["parent_ts"], leg["term_ts"]),
            "id": f"S{n:02d}",
            "direction": leg["direction"],
            "parent_ts": leg["parent_ts"], "parent_price": float(leg["parent_price"]),
            "term_ts": leg["term_ts"], "term_price": float(leg["term_price"]),
            "verdict": "detector", "scored": True,
        })
    return out


def _pct(x) -> str:
    return f"{x * 100:.0f}%" if x is not None else "n/a"


def _rr_display(reg: dict):
    """(reward:risk rows, max achievable R) for a regime, for the RR card + KPI."""
    if reg.get("scaled"):
        e = sum(w * c for c, w in SCALED_TRANCHES)          # blended entry coeff
        r1 = sum(w * abs(c - SCALED_SL_C) for c, w in SCALED_TRANCHES)
        rows = [{"label": f"full position &rarr; {lv}", "value": f"{(e - lv) / r1:.2f}R"}
                for lv in (0.618, 0.5, 0.0)]
        max_r = e / r1   # full ride to 0.0 (capital-weighted ceiling)
        rows.append({"label": "max if full ride to 0.0", "value": f"{max_r:.2f}R"})
        return rows, max_r
    rr = rr_targets(reg["params"])
    p = reg["params"]
    rows = [
        {"label": f"&rarr; TP1 ({p['be_trig_c']})", "value": f"{rr['tp1']:.2f}R"},
        {"label": f"&rarr; TP2 ({p['tp2_c']})", "value": f"{rr['tp2']:.2f}R"},
        {"label": f"&rarr; TP3 ({p['tp3_c']})", "value": f"{rr['tp3']:.2f}R"},
    ]
    return rows, rr["tp3"]


def dashboard_setups() -> list[dict]:
    """Every reviewed setup with its latest verdict, displayed at its current
    anchors (corrected when the human adjusted it). Reject 'artifacts' that merely
    duplicate an adjust's corrected anchors are dropped; standalone rejects (a
    disputed outcome) are kept and flagged unscored, so nothing silently vanishes.
    """
    latest = latest_by_key(load_labels())
    corrected_keys = {
        setup_key(lbl.corrected["parent_ts"], lbl.corrected["term_ts"])
        for lbl in latest.values()
        if lbl.corrected
    }
    by_disp: dict[str, dict] = {}
    for lbl in latest.values():
        anchors = lbl.corrected or {
            "direction": lbl.direction,
            "parent_ts": lbl.parent_ts, "parent_price": lbl.parent_price,
            "term_ts": lbl.term_ts, "term_price": lbl.term_price,
        }
        key = setup_key(anchors["parent_ts"], anchors["term_ts"])
        if lbl.verdict == VERDICT_REJECT and key in corrected_keys:
            continue  # the stray left by an adjust -> drop the duplicate
        row = {
            "key": key,
            "direction": anchors["direction"],
            "parent_ts": anchors["parent_ts"], "parent_price": float(anchors["parent_price"]),
            "term_ts": anchors["term_ts"], "term_price": float(anchors["term_price"]),
            "verdict": lbl.verdict,
            "scored": lbl.verdict != VERDICT_REJECT,
            "created_at": lbl.created_at,
        }
        prev = by_disp.get(key)
        if prev is None or row["created_at"] >= prev["created_at"]:
            by_disp[key] = row
    out = list(by_disp.values())
    out.sort(key=lambda s: s["term_ts"])
    for n, s in enumerate(out, start=1):
        s["id"] = f"S{n:02d}"
    return out


def _detail(candles, idx, atr, setup, reg) -> dict:
    res = run_regime(candles, idx, setup, reg)
    lv = res.get("levels", {})
    kind = KIND.get(res["status"], "open")
    events = [
        {"label": lab, "ts": ts, "price": price, "i": idx.get(ts)}
        for lab, ts, price in res["events"]
    ]
    # Uniform chart levels: scaled provides level_lines; build them for single-entry.
    lines = res.get("level_lines")
    if not lines and lv:
        lines = [
            {"label": "entry", "price": lv["entry"], "role": "entry"},
            {"label": "SL 1.05", "price": lv["init_sl"], "role": "sl"},
            {"label": "TP1", "price": lv["be_trig"], "role": "tp"},
            {"label": "TP2", "price": lv["tp2"], "role": "tp"},
            {"label": "TP3", "price": lv["tp3"], "role": "tp"},
        ]
    span = abs(setup["term_price"] - setup["parent_price"])
    a = atr[idx[setup["term_ts"]]] or 0.0
    return {
        "status": res["status"],
        "kind": kind,
        "kind_label": KIND_LABEL.get(kind, res["status"]),
        "r": res["r"],
        "levels": lv,
        "level_lines": lines or [],
        "events": events,
        "entry_i": events[0]["i"] if events else None,
        "exit_i": events[-1]["i"] if events else None,
        "span": span,
        "depth": (span / a) if a else 0.0,
    }


def compute_state(asset_key: str = "btc", min_bars=None, mult=None) -> dict:
    cfg = ASSETS.get(asset_key, ASSETS["btc"])
    candles = load_candles(cfg["csv"])
    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    atr = calculate_atr14(candles)
    detector = cfg["source"] == "detector"
    if detector:
        mb = int(min_bars) if min_bars else cfg["min_bars"]
        mu = float(mult) if mult else cfg["mult"]
        setups = detector_setups(candles, idx, atr, mb, mu)
        det_info = {"min_bars": mb, "mult": mu}
    else:
        setups = dashboard_setups()
        det_info = None

    parents = [idx[s["parent_ts"]] for s in setups if s["parent_ts"] in idx]
    win_start = max(0, (min(parents) - PAD_BARS)) if parents else 0
    window = candles[win_start:]
    candle_payload = [
        {"t": c.source_timestamp, "o": c.open, "h": c.high, "l": c.low, "c": c.close}
        for c in window
    ]

    # Compute each setup's per-regime detail once, then derive the aggregates.
    for s in setups:
        s["parent_i"] = idx.get(s["parent_ts"])
        s["term_i"] = idx.get(s["term_ts"])
        s["by_regime"] = {}
        if s["term_ts"] in idx:
            for reg in REGIMES_ALL:
                s["by_regime"][reg["slug"]] = _detail(candles, idx, atr, s, reg)

    agg_by_regime: dict[str, dict] = {}
    for reg in REGIMES_ALL:
        rows = [
            {"kind": s["by_regime"][reg["slug"]]["kind"],
             "r": s["by_regime"][reg["slug"]]["r"], "direction": s["direction"]}
            for s in setups if s["scored"] and s["term_ts"] in idx
        ]
        agg = aggregate(rows)
        rr_rows, max_r = _rr_display(reg)
        be = agg["breakeven_wr"]
        rr_rows.append({"label": "break-even win rate", "value": _pct(be)})
        rr_rows.append({
            "label": "above break-even" if (be is not None and agg["win_rate"] > be) else "below break-even",
            "value": f"{agg['avg_r']:+.3f}R", "cap": True, "pos": agg["avg_r"] >= 0,
        })
        agg["rr_rows"] = rr_rows
        agg["max_r"] = max_r
        agg["even"] = sum(1 for r in rows if r["kind"] == "even")
        agg_by_regime[reg["slug"]] = agg

    return {
        "symbol": cfg["symbol"] + " 1H",
        "asset": asset_key,
        "source": cfg["source"],
        "detector": det_info,
        "assets": [{"key": k, "label": v["label"], "source": v["source"]}
                   for k, v in ASSETS.items() if Path(v["csv"]).exists()],
        "regimes": [{"slug": r["slug"], "label": r["label"], "params": r["params"]} for r in REGIMES_ALL],
        "colors": COLOR,
        "kind_label": KIND_LABEL,
        "base_i": win_start,
        "candles": candle_payload,
        "setups": setups,
        "agg": agg_by_regime,
        "n_setups": len(setups),
        "n_scored": sum(1 for s in setups if s["scored"]),
    }


def save_feedback(body: dict) -> dict:
    verdict = body["verdict"]
    leg = {
        "parent_ts": body["parent_ts"], "term_ts": body["term_ts"],
        "direction": body["direction"],
        "parent_price": float(body["parent_price"]),
        "term_price": float(body["term_price"]),
    }
    params = {"source": "dashboard"}
    if body.get("note"):
        params["note"] = str(body["note"])[:500]
    rec = make_label(leg, verdict, corrected=body.get("corrected"), detector_params=params)
    append_label(rec)
    return {"ok": True, "setup_key": rec.setup_key, "verdict": verdict}


def _tv_chrome_alive(port: int = 9222) -> bool:
    """Quick TCP probe: is debug Chrome listening on the TradingView port?"""
    import socket as _sock
    s = _sock.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _run_tv_script(args: list[str], timeout: int = 60) -> dict:
    """Subprocess-spawn place_fibs_tradingview.py with given args, captured
    and synchronous. Used by /api/tv_place_setups (we want the placement
    output back). NOT suitable for `login` mode -- selenium's chromedriver
    keeps the captured-pipe alive long after Chrome is spawned, blocking us
    for the full timeout. Use _spawn_tv_script_detached() for that."""
    import subprocess as _sp
    script = REPO_ROOT / "scripts" / "place_fibs_tradingview.py"
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    cmd = [py, str(script), *args]
    try:
        proc = _sp.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                       text=True, timeout=timeout,
                       env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
        return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr, "cmd": cmd}
    except _sp.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "",
                "stderr": f"timeout after {timeout}s", "cmd": cmd}
    except Exception as exc:
        return {"ok": False, "returncode": -1, "stdout": "",
                "stderr": f"spawn failed: {exc!r}", "cmd": cmd}


def _spawn_tv_script_detached(args: list[str]) -> dict:
    """Fire-and-forget spawn. Pipes go to DEVNULL so chromedriver can't keep
    them open. Returns immediately once Popen launches the child. Caller
    polls /api/tv_status to detect when Chrome's debug port comes up."""
    import subprocess as _sp
    script = REPO_ROOT / "scripts" / "place_fibs_tradingview.py"
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    cmd = [py, str(script), *args]
    try:
        proc = _sp.Popen(cmd, cwd=str(REPO_ROOT),
                         stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                         env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
                         start_new_session=True)
        return {"ok": True, "spawned": True, "pid": proc.pid,
                "note": "Chrome is launching; status will refresh shortly.",
                "cmd": cmd}
    except Exception as exc:
        return {"ok": False, "spawned": False, "pid": -1,
                "note": f"spawn failed: {exc!r}", "cmd": cmd}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quieter console
        pass

    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/" or parsed.path.startswith("/index"):
                self._send(200, APP_HTML.read_bytes(), "text/html; charset=utf-8")
            elif parsed.path.startswith("/api/state"):
                q = parse_qs(parsed.query)
                asset = q.get("asset", ["btc"])[0]
                mb = q.get("min_bars", [None])[0]
                mu = q.get("mult", [None])[0]
                self._send(200, compute_state(asset, mb, mu))
            elif parsed.path == "/api/tv_status":
                self._send(200, {"chrome_alive": _tv_chrome_alive(),
                                 "platform": sys.platform})
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:  # surface errors to the client for debugging
            self._send(500, {"error": repr(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path.startswith("/api/feedback"):
                self._send(200, save_feedback(body))
            elif self.path == "/api/tv_launch_chrome":
                # Fire-and-forget: chromedriver keeps captured pipes open for
                # minutes, so we detach. Frontend polls /api/tv_status to
                # learn when Chrome's debug port is actually up.
                self._send(200, _spawn_tv_script_detached(["login"]))
            elif self.path == "/api/tv_place_setups":
                # Place N setups (default 12) on the already-running TV chart.
                # Requires _tv_chrome_alive() == True (we don't recheck here --
                # the script's own error surfaces clearly enough).
                n = int(body.get("n", 12))
                self._send(200, _run_tv_script([str(n)], timeout=240))
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": repr(exc)})


def main() -> None:
    port = 8800
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"DB1 review dashboard on {url}  (Ctrl-C to stop)")
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.shutdown()


if __name__ == "__main__":
    main()
