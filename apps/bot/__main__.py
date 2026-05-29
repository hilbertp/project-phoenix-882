"""CLI entrypoint: `python -m apps.bot <command>`.

M1 commands:
  detect    Run the bar-close detector loop over the configured universe.
            Read-only — backfills history, subscribes to live candles, and
            logs/persists every new swing setup. No orders are placed.
  status    Dump the most recent setups + FSM states from the state store.
  init-db   Create the SQLite schema (idempotent; useful for tooling).

Run `python -m apps.bot --help` for full usage.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from apps.bot import __version__
from apps.bot.config import BotConfig, hl_agent_private_key, load_config
from apps.bot.exchange.hyperliquid import HyperliquidPublicClient
from apps.bot.logging_setup import configure_logging, get_logger
from apps.bot.marketdata import MarketDataFeed, hl_to_worker_candle
from apps.bot.simulation.paper_executor import simulate_setup
from apps.bot.state import StateStore
from apps.bot.strategy.detector_loop import DetectorLoop
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.swing_detector import clean_legs


def _make_client(cfg: BotConfig) -> HyperliquidPublicClient:
    return HyperliquidPublicClient(
        rest_url=cfg.hyperliquid.rest_url,
        ws_url=cfg.hyperliquid.ws_url,
    )


def cmd_init_db(cfg: BotConfig, args: argparse.Namespace) -> int:
    store = StateStore(cfg.state_db_path)
    store.close()
    print(f"State DB ready at {cfg.state_db_path}")
    return 0


def cmd_status(cfg: BotConfig, args: argparse.Namespace) -> int:
    store = StateStore(cfg.state_db_path)
    setups = store.list_setups(asset=args.asset, limit=args.limit)
    if not setups:
        print("No setups recorded yet.")
        store.close()
        return 0
    print(f"{'asset':<6} {'dir':<5} {'parent_ts':<20} {'term_ts':<20} "
          f"{'parent':>10} {'term':>10} {'state':<10}")
    for rec in setups:
        state = store.get_state(rec.setup_key)
        state_label = state.state if state else "-"
        print(f"{rec.asset:<6} {rec.direction:<5} {rec.parent_ts:<20} "
              f"{rec.term_ts:<20} {rec.parent_price:>10.2f} "
              f"{rec.term_price:>10.2f} {state_label:<10}")
    store.close()
    return 0


def cmd_detect(cfg: BotConfig, args: argparse.Namespace) -> int:
    log = get_logger("apps.bot.detect")
    assets = tuple(args.asset) if args.asset else cfg.universe
    log.info("starting detector loop",
             extra={"assets": list(assets), "mode": cfg.mode,
                    "interval": cfg.detector.interval})
    store = StateStore(cfg.state_db_path)
    client = _make_client(cfg)
    feed = MarketDataFeed(
        client,
        assets=assets,
        interval=cfg.detector.interval,
        buffer_size=args.buffer_size,
    )
    loop = DetectorLoop(store, cfg.detector)
    feed.subscribe(loop.on_bar_close)

    log.info("backfilling history",
             extra={"buffer_size": args.buffer_size})
    feed.backfill()

    # Run the detector once across the backfilled buffer so any pre-existing
    # finalized legs land in the state store without waiting for a fresh bar.
    for asset in assets:
        buf = feed.buffer(asset)
        if not buf:
            continue
        from apps.bot.marketdata import BarCloseEvent
        synthetic = BarCloseEvent(
            asset=asset,
            interval=cfg.detector.interval,
            closed_open_ms=0,
            candles=buf,
        )
        loop.on_bar_close(synthetic)

    if args.once:
        log.info("--once set, exiting after initial pass")
        store.close()
        return 0

    feed.start_live()
    stop_evt = threading.Event()

    def _sigterm(signum, frame):
        log.info("signal received; shutting down",
                 extra={"signal": signum})
        stop_evt.set()

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        while not stop_evt.is_set():
            time.sleep(1.0)
    finally:
        feed.stop()
        store.close()
    return 0


def cmd_live(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Run the bot against real Hyperliquid with real money.

    Safety gates (all required):
      * cfg.mode == "live"
      * PHOENIX_HL_AGENT_PRIVATE_KEY env set (Rabby-approved agent, not master)
      * PHOENIX_HL_ACCOUNT_ADDRESS env set (master / Rabby wallet address)
      * --yes-real-money flag
      * Reconciler returns non-AMBIGUOUS
      * Agent key is currently approved on HL for the master account
    """
    log = get_logger("apps.bot.live")
    missing: list[str] = []
    if cfg.mode != "live":
        missing.append('config.mode must be "live"')
    if hl_agent_private_key() is None:
        missing.append("env PHOENIX_HL_AGENT_PRIVATE_KEY not set")
    if cfg.hyperliquid.account_address is None:
        missing.append("env PHOENIX_HL_ACCOUNT_ADDRESS not set")
    if not args.yes_real_money:
        missing.append("--yes-real-money flag not passed")
    if missing:
        print("REFUSING to start live trading. Missing requirements:")
        for m in missing:
            print(f"  * {m}")
        return 2

    # Late imports — the SDK is only required when actually trading live.
    from apps.bot.exchange.signed_client import SignedHyperliquidClient
    from apps.bot.observability.error_counter import ErrorCounter
    from apps.bot.observability.metrics import MetricsServer, register_all
    from apps.bot.risk.engine import RiskEngine
    from apps.bot.risk.funding_watcher import FundingWatcher
    from apps.bot.risk.kill_switch import KillSwitch
    from apps.bot.strategy.fsm import Setup
    from apps.bot.strategy.order_manager import OrderManager
    from apps.bot.strategy.reconciler import format_summary, reconcile

    # Register the §8.2 metric catalogue BEFORE constructing components
    # that emit. Idempotent — safe to call once per process.
    register_all()
    metrics_server: MetricsServer | None = None
    if (cfg.observability.metrics_enabled
            and cfg.observability.metrics_port > 0):
        metrics_server = MetricsServer(
            host=cfg.observability.metrics_host,
            port=cfg.observability.metrics_port,
        )
        metrics_server.start()

    # PRD §7.3: > 10 consecutive WS/REST errors in 60s fires the kill switch.
    # We defer constructing the kill switch until we have a signed client,
    # then use a forward-declared closure to wire the trip handler.
    _pending_kill_switch: list = []  # 1-element list as a closure cell

    def _on_error_trip(kind: str, count: int) -> None:
        if _pending_kill_switch:
            _pending_kill_switch[0].fire(f"error_rate:{kind}")

    error_counter = ErrorCounter(
        threshold=10, window_s=60.0, on_trip=_on_error_trip,
    )

    signed = SignedHyperliquidClient(
        agent_private_key=hl_agent_private_key(),
        master_account_address=cfg.hyperliquid.account_address,
        rest_url=cfg.hyperliquid.rest_url,
        error_counter=error_counter,
    )

    # Verify Rabby actually approved this agent for the master account. HL
    # rejects every signed action otherwise; better to refuse here with a
    # clear message than to ship a trade-rejecting bot.
    if not signed.agent_is_approved():
        log.error(
            "agent key is NOT approved on HL for this master account; "
            "re-approve via Rabby on app.hyperliquid.xyz and try again",
            extra={"master_address": cfg.hyperliquid.account_address,
                   "agent_address": signed.agent_address},
        )
        return 6

    store = StateStore(cfg.state_db_path)

    kill_switch = KillSwitch(client=signed, store=store)
    # Make the error-trip closure aware of the kill switch now that we
    # have one.
    _pending_kill_switch.append(kill_switch)
    if kill_switch.is_halted():
        reason = kill_switch.halt_reason()
        if args.rearm_on_start:
            log.warning(
                "halt flag was set; --rearm-on-start clears it",
                extra={"previous_reason": reason},
            )
            kill_switch.re_arm()
        else:
            log.error(
                "kill switch is engaged; refusing to start. Run "
                "`python -m apps.bot re-arm` (or pass --rearm-on-start) "
                "after investigating.",
                extra={"halt_reason": reason},
            )
            store.close()
            return 7

    log.info("running startup reconciliation")
    result = reconcile(signed, store)
    print(format_summary(result))
    if not result.ok:
        log.error("reconciliation ambiguous; refusing to start",
                  extra={"issues": result.issues})
        store.close()
        return 3
    # PRD F-09 (orphan stop). RESUMABLE with in-flight setups means the
    # exchange and DB agree, but the OrderManager has no in-memory FSMs to
    # drive those setups -- software BE-drag won't run, so a TP1_HIT/TP2_HIT
    # setup would lose its close-based break-even protection. Halt unless the
    # operator explicitly accepts the orphan-position risk. Automated FSM
    # rehydration is M4 work.
    if result.in_flight_setups and not args.accept_orphan_positions:
        log.error(
            "RESUMABLE state has in-flight setups but FSM rehydration is "
            "not implemented. Pass --accept-orphan-positions to proceed "
            "with the understanding that software BE-drag will NOT run "
            "for these setups.",
            extra={"in_flight_count": len(result.in_flight_setups)},
        )
        store.close()
        return 5

    # Equity for sizing: HL user_state -> marginSummary.accountValue.
    user_state = signed._info.user_state(signed.account_address) or {}
    equity = float(
        ((user_state.get("marginSummary") or {}).get("accountValue")) or 0
    )
    if equity <= 0:
        log.error("no equity available for sizing",
                  extra={"user_state": user_state})
        store.close()
        return 4
    log.info("equity snapshot", extra={"equity": equity})

    # Per-asset qty precision (HL szDecimals) + leverage caps. Without
    # these, every live order is at risk of rejection (over-precise qty
    # or notional > equity*maxLeverage). One retry on transient REST
    # failures; if both attempts fail, refuse to start (defaults are
    # WRONG — better to halt than ship doomed orders).
    qty_precision: dict[str, int] = {}
    max_leverage: dict[str, int] = {}
    meta_ok = False
    for attempt in (1, 2):
        try:
            qty_precision = signed.fetch_size_decimals()
            max_leverage = signed.fetch_max_leverage()
            meta_ok = True
            break
        except Exception:
            log.exception(
                "venue meta fetch failed",
                extra={"attempt": attempt},
            )
            time.sleep(2.0)
    if not meta_ok:
        log.error(
            "venue meta unavailable after retries; refusing to start "
            "(would ship orders with wrong precision/leverage)",
        )
        store.close()
        return 9
    log.info("loaded venue meta",
             extra={"assets_with_precision": len(qty_precision),
                    "assets_with_leverage": len(max_leverage)})

    risk_engine = RiskEngine(store=store, risk_cfg=cfg.risk)
    funding_watcher = FundingWatcher(
        client=signed, risk_engine=risk_engine, store=store, risk_cfg=cfg.risk,
        error_counter=error_counter,
    )
    # Seed the funding-skip set BEFORE the loop opens, so we don't arm into
    # an already-adverse asset on the first bar close, then keep polling
    # hourly in a background thread.
    funding_watcher.poll_once()
    funding_watcher.start()

    order_manager = OrderManager(
        client=signed, store=store,
        strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, equity=equity,
        qty_precision=qty_precision, max_leverage=max_leverage,
        risk_engine=risk_engine,
    )

    assets = tuple(args.asset) if args.asset else cfg.universe
    public = HyperliquidPublicClient(
        rest_url=cfg.hyperliquid.rest_url, ws_url=cfg.hyperliquid.ws_url,
        error_counter=error_counter,
    )
    feed = MarketDataFeed(
        public, assets=assets, interval=cfg.detector.interval,
        buffer_size=args.buffer_size,
    )
    detector = DetectorLoop(
        store, cfg.detector, on_new_setup=order_manager.arm_setup,
    )
    feed.subscribe(detector.on_bar_close)
    feed.subscribe(order_manager.on_bar_close)

    log.info("backfilling history",
             extra={"buffer_size": args.buffer_size, "assets": list(assets)})
    feed.backfill()

    # Pickup stranded "detected" setups: rows in the state store that the
    # detector persisted but the OrderManager never armed (e.g. crashed
    # between the detector's upsert and the arm_setup hook). Without this,
    # the detector's INSERT OR IGNORE on the next bar would skip them
    # forever.
    detected_setups = []
    for setup_row in store.list_setups(limit=10_000):
        st = store.get_state(setup_row.setup_key)
        if st and st.state == "detected":
            detected_setups.append(setup_row)
    if detected_setups:
        log.info("picking up stranded detected setups",
                 extra={"count": len(detected_setups)})
        for setup_row in detected_setups:
            buf = feed.buffer(setup_row.asset)
            history = tuple(c for c in buf if c.source_timestamp > setup_row.term_ts)
            order_manager.arm_setup(
                Setup(
                    asset=setup_row.asset,
                    direction=setup_row.direction,
                    parent_ts=setup_row.parent_ts,
                    parent_price=setup_row.parent_price,
                    term_ts=setup_row.term_ts,
                    term_price=setup_row.term_price,
                ),
                history,
            )

    feed.start_live()

    stop_evt = threading.Event()

    def _sigterm(signum, frame):
        log.info("signal received; shutting down",
                 extra={"signal": signum})
        stop_evt.set()

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        while not stop_evt.is_set():
            time.sleep(1.0)
    finally:
        funding_watcher.stop()
        feed.stop()
        if metrics_server is not None:
            metrics_server.stop()
        store.close()
    return 0


def cmd_kill(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Operator-fired kill switch: cancel everything, market-flat, halt.

    Same credential gates as `live` because we are signing exchange actions.
    """
    missing: list[str] = []
    if hl_agent_private_key() is None:
        missing.append("env PHOENIX_HL_AGENT_PRIVATE_KEY not set")
    if cfg.hyperliquid.account_address is None:
        missing.append("env PHOENIX_HL_ACCOUNT_ADDRESS not set")
    if not args.yes_real_money:
        missing.append("--yes-real-money flag not passed")
    if missing:
        print("REFUSING to fire kill switch. Missing requirements:")
        for m in missing:
            print(f"  * {m}")
        return 2

    from apps.bot.exchange.signed_client import SignedHyperliquidClient
    from apps.bot.risk.kill_switch import KillSwitch

    signed = SignedHyperliquidClient(
        agent_private_key=hl_agent_private_key(),
        master_account_address=cfg.hyperliquid.account_address,
        rest_url=cfg.hyperliquid.rest_url,
    )
    store = StateStore(cfg.state_db_path)
    kill = KillSwitch(client=signed, store=store)
    summary = kill.fire(args.reason)
    print(f"halted_at:           {summary.halted_at}")
    print(f"reason:              {summary.reason}")
    print(f"cancelled orders:    {len(summary.cancelled_orders)}")
    print(f"cancel failures:     {len(summary.cancel_failures)}")
    print(f"closed positions:    {len(summary.closed_positions)}")
    print(f"close failures:      {len(summary.close_failures)}")
    print(f"clean flatten:       {summary.ok()}")
    store.close()
    return 0 if summary.ok() else 8


def cmd_rearm(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Clear the halt flag. No signed-credential gate — local DB op only."""
    store = StateStore(cfg.state_db_path)
    if store.get_flag("halt") is None:
        print("not halted; nothing to do")
        store.close()
        return 0
    prev = store.get_flag("halt")
    store.clear_flag("halt")
    print(f"cleared halt flag (was: {prev!r})")
    store.close()
    return 0


def cmd_dashboard(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Serve the read-only bot dashboard at http://host:port."""
    from apps.bot.dashboard import serve

    log = get_logger("apps.bot.dashboard")
    store = StateStore(cfg.state_db_path)
    server = serve(
        store=store, cfg=cfg,
        host=args.host, port=args.port, open_browser=args.open,
        log_dir=cfg.log_dir,
    )
    print(f"dashboard: http://{args.host}:{args.port}")
    print("Ctrl-C to stop")
    stop_evt = threading.Event()

    def _sigterm(signum, frame):
        log.info("signal received; shutting down dashboard",
                 extra={"signal": signum})
        stop_evt.set()

    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        while not stop_evt.is_set():
            time.sleep(1.0)
    finally:
        server.shutdown()
        server.server_close()
        store.close()
    return 0


def cmd_risk_status(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Print a snapshot of the risk engine's live counters."""
    from apps.bot.risk.engine import RiskEngine

    store = StateStore(cfg.state_db_path)
    engine = RiskEngine(store=store, risk_cfg=cfg.risk)
    snap = engine.status_snapshot()
    print("== Risk status ==")
    for k, v in snap.items():
        print(f"  {k:<28} {v}")
    store.close()
    return 0


def cmd_simulate(cfg: BotConfig, args: argparse.Namespace) -> int:
    """Pull historical candles from HL, run the detector, replay through the FSM."""
    log = get_logger("apps.bot.simulate")
    asset = args.asset
    log.info("starting simulation",
             extra={"asset": asset, "bars": args.buffer_size})

    client = _make_client(cfg)
    import time as _time
    interval_ms = 3_600_000  # 1h
    now_ms = int(_time.time() * 1000)
    current_bar_open = (now_ms // interval_ms) * interval_ms
    end_ms = current_bar_open - 1
    start_ms = end_ms - args.buffer_size * interval_ms
    raw = client.candle_snapshot(asset, cfg.detector.interval, start_ms, end_ms)
    candles = [hl_to_worker_candle(c) for c in raw]
    log.info("fetched candles", extra={"asset": asset, "bars": len(candles)})

    atr = calculate_atr14(candles)
    legs = clean_legs(
        candles, atr, None,
        min_bars=cfg.detector.min_bars, mult=cfg.detector.mult,
    )
    log.info("legs detected", extra={"asset": asset, "legs": len(legs)})

    idx = {c.source_timestamp: i for i, c in enumerate(candles)}
    counts: dict[str, int] = {}
    total_r = 0.0
    triggered = 0
    wins = 0
    for leg in legs:
        leg = {**leg, "asset": asset}
        out = simulate_setup(leg, candles, idx, cfg.strategy)
        st = out["status"]
        counts[st] = counts.get(st, 0) + 1
        if st in ("wipeout", "tp1_then_scratch", "tp2_then_scratch", "tp3_full"):
            triggered += 1
            total_r += out["r"]
            # Win = anything that reached TP1 or beyond. Only wipeout is a loss
            # in the triggered cohort (per the DB1 review-label semantics).
            if st in ("tp1_then_scratch", "tp2_then_scratch", "tp3_full"):
                wins += 1

    print(f"\n=== Simulation summary: {asset} ({len(candles)} bars) ===")
    print(f"  legs detected:       {len(legs)}")
    print(f"  triggered (filled):  {triggered}")
    if triggered:
        win_rate = wins / triggered * 100
        avg_r = total_r / triggered
        print(f"  total R:             {total_r:+.2f}")
        print(f"  avg R per trade:     {avg_r:+.3f}")
        print(f"  win rate (TP1+):     {wins}/{triggered} = {win_rate:.1f}%")
    print("  by outcome:")
    for status in ("tp3_full", "tp2_then_scratch", "tp1_then_scratch",
                   "wipeout", "no_trigger", "no_entry", "degenerate", "open"):
        n = counts.get(status, 0)
        if n:
            print(f"    {status:<20} {n:>4}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apps.bot",
        description="DB1-Sniper live trading bot (M1: detect-only).",
    )
    parser.add_argument(
        "--config",
        help="Path to a TOML config file. Falls back to PHOENIX_BOT_CONFIG env.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        help="Console + file log level (default INFO).",
    )
    parser.add_argument("--version", action="version", version=__version__)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="Create the state DB schema.")
    p_init.set_defaults(func=cmd_init_db)

    p_status = sub.add_parser("status", help="Print recent setups + FSM states.")
    p_status.add_argument("--asset", help="Filter by asset symbol.")
    p_status.add_argument("--limit", type=int, default=20)
    p_status.set_defaults(func=cmd_status)

    p_detect = sub.add_parser(
        "detect",
        help="Backfill, subscribe to live candles, persist new setups.",
    )
    p_detect.add_argument(
        "--asset", action="append",
        help="Restrict to one or more assets (repeatable). Defaults to universe.",
    )
    p_detect.add_argument(
        "--buffer-size", type=int, default=2000,
        help="Candles to retain per asset (default 2000 ~= 83 days of 1H).",
    )
    p_detect.add_argument(
        "--once", action="store_true",
        help="Run the detector over backfilled data once and exit.",
    )
    p_detect.set_defaults(func=cmd_detect)

    p_sim = sub.add_parser(
        "simulate",
        help="Fetch history, detect setups, replay through the FSM (paper).",
    )
    p_sim.add_argument("--asset", default="BTC",
                       help="Asset symbol to simulate (default BTC).")
    p_sim.add_argument(
        "--buffer-size", type=int, default=5000,
        help="Bars of history to fetch (default 5000 ~= 7 months at 1H).",
    )
    p_sim.set_defaults(func=cmd_simulate)

    p_kill = sub.add_parser(
        "kill",
        help=("Fire the kill switch: cancel every open order, market-flat"
              " every position, halt. Same credential gates as `live`."),
    )
    p_kill.add_argument(
        "--yes-real-money", action="store_true",
        help="Required acknowledgement (this signs real exchange actions).",
    )
    p_kill.add_argument(
        "--reason", required=True,
        help="Free-text reason for audit (e.g. 'manual_operator')",
    )
    p_kill.set_defaults(func=cmd_kill)

    p_rearm = sub.add_parser(
        "re-arm",
        help="Clear the halt flag so the bot will accept new entries again.",
    )
    p_rearm.set_defaults(func=cmd_rearm)

    p_rstatus = sub.add_parser(
        "risk-status",
        help="Print risk engine counters: positions, R, paused assets, halt.",
    )
    p_rstatus.set_defaults(func=cmd_risk_status)

    p_dash = sub.add_parser(
        "dashboard",
        help="Serve a read-only HTML dashboard over state.db.",
    )
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--port", type=int, default=9101)
    p_dash.add_argument("--open", action="store_true",
                        help="Open the dashboard URL in a browser on start.")
    p_dash.set_defaults(func=cmd_dashboard)

    p_live = sub.add_parser(
        "live",
        help=("Run the bot against Hyperliquid with REAL MONEY."
              " Multiple gates required."),
    )
    p_live.add_argument(
        "--yes-real-money", action="store_true",
        help=("Required explicit acknowledgement. Without this flag,"
              " live mode refuses to start."),
    )
    p_live.add_argument(
        "--accept-orphan-positions", action="store_true",
        help=("Allow startup with in-flight setups present on the exchange"
              " that the in-memory FSM cannot manage (BE-drag will NOT run"
              " for them). Use only when manually supervising the exit."),
    )
    p_live.add_argument(
        "--rearm-on-start", action="store_true",
        help=("Clear an existing halt flag at startup. Without this, "
              "`live` refuses to start if the kill switch was previously "
              "engaged."),
    )
    p_live.add_argument(
        "--asset", action="append",
        help="Restrict to one or more assets (repeatable). Defaults to universe.",
    )
    p_live.add_argument(
        "--buffer-size", type=int, default=2000,
        help="Candles to retain per asset (default 2000 ~= 83 days of 1H).",
    )
    p_live.set_defaults(func=cmd_live)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    configure_logging(cfg.log_dir, level=args.log_level)
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
