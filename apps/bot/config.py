"""Bot configuration: TOML file + env-only secrets.

Loading order:
  1. Built-in defaults (this module).
  2. TOML overrides from --config (or PHOENIX_BOT_CONFIG env var).
  3. Secrets from env: PHOENIX_HL_AGENT_PRIVATE_KEY, PHOENIX_HL_ACCOUNT_ADDRESS.

The defaults intentionally mirror docs/db1_live_bot_prd.md so the bot runs in
detect-only paper mode out of the box without any config file.

Hyperliquid agent trust model (the only supported pattern):
  * Master wallet lives in the user's Rabby wallet. It holds funds and is
    the only key that can withdraw. The bot NEVER sees this key.
  * Agent wallet is a separate keypair the user generates (via the HL web
    UI at app.hyperliquid.xyz, signed once in Rabby). The agent can sign
    trades but cannot withdraw.
  * The bot's `PHOENIX_HL_AGENT_PRIVATE_KEY` is the AGENT key.
  * `PHOENIX_HL_ACCOUNT_ADDRESS` is the MASTER address (the Rabby wallet
    that holds funds). HL associates positions / balance with the master.

See docs/db1_live_bot_acs/rabby_agent.md for the full contract.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import tomllib

DEFAULT_UNIVERSE = ("BTC", "ETH", "BNB", "ADA", "XRP", "SOL", "HYPE")


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    min_bars: int = 6
    mult: float = 2.0
    interval: str = "1h"  # Hyperliquid candle interval string


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    entry_coeff: float = 0.941
    init_sl_coeff: float = 1.05
    tp1_coeff: float = 0.882
    tp2_coeff: float = 0.5
    tp3_coeff: float = 0.0
    tp1_size: float = 0.25
    tp2_size: float = 0.60
    tp3_size: float = 0.15


@dataclass(frozen=True, slots=True)
class RiskConfig:
    account_risk_pct: float = 1.0
    max_concurrent_positions: int = 4
    max_trades_per_asset_per_day: int = 6
    daily_loss_r_limit: float = -3.0
    weekly_loss_r_limit: float = -8.0
    consecutive_loss_limit: int = 5
    slippage_alert_pct: float = 0.3
    adverse_funding_apy_skip: float = 100.0
    # Hyperliquid's minimum order notional in USDC. Orders below this are
    # silently rejected by HL; we pre-flight in the OrderManager and refuse
    # to arm rather than ship a no-op order to the exchange.
    min_notional_usd: float = 10.0


@dataclass(frozen=True, slots=True)
class HyperliquidConfig:
    testnet: bool = False
    rest_url: str = "https://api.hyperliquid.xyz"
    ws_url: str = "wss://api.hyperliquid.xyz/ws"
    # Master (Rabby-controlled) wallet address. The bot trades AS this
    # account via an approved agent key; the master key itself never
    # touches the bot. Set via env PHOENIX_HL_ACCOUNT_ADDRESS.
    account_address: str | None = None
    # Agent private key is held only inside the signed client; never stored
    # on this config object so a stray pickle / log of `config` cannot leak
    # it. Read on demand via config.hl_agent_private_key().


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    # PRD §8.2 metrics. The /metrics endpoint binds 127.0.0.1 by default so
    # scraping requires a reverse proxy / SSH tunnel (no random listeners
    # facing the world). port=0 disables the server entirely.
    metrics_enabled: bool = True
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9100


@dataclass(frozen=True, slots=True)
class BotConfig:
    # "shadow" mode (real orders at minimum HL notional) is on the M4 roadmap
    # but not yet implemented anywhere. Validator only accepts the modes
    # the bot actually honors today.
    mode: str = "paper"  # paper | live
    state_db_path: Path = Path("data/bot/state.db")
    log_dir: Path = Path("data/bot/logs")
    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    hyperliquid: HyperliquidConfig = field(default_factory=HyperliquidConfig)
    observability: ObservabilityConfig = field(
        default_factory=ObservabilityConfig,
    )


_HL_TESTNET_REST = "https://api.hyperliquid-testnet.xyz"
_HL_TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws"


def _apply_section(cfg: Any, overrides: dict) -> Any:
    """Replace only the fields present in `overrides`; reject unknown keys."""
    if not overrides:
        return cfg
    known = {f for f in cfg.__dataclass_fields__}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(
            f"Unknown config keys for {type(cfg).__name__}: {sorted(unknown)}"
        )
    return replace(cfg, **overrides)


def load_config(path: str | os.PathLike | None = None) -> BotConfig:
    """Load BotConfig from TOML at `path` (or PHOENIX_BOT_CONFIG env), env-merged."""
    cfg = BotConfig()

    resolved_path: Path | None = None
    if path is not None:
        resolved_path = Path(path)
    else:
        env_path = os.environ.get("PHOENIX_BOT_CONFIG")
        if env_path:
            resolved_path = Path(env_path)

    if resolved_path is not None:
        if not resolved_path.exists():
            raise FileNotFoundError(f"Bot config not found: {resolved_path}")
        with resolved_path.open("rb") as fh:
            data = tomllib.load(fh)
        bot_section = data.get("bot", {})
        cfg = replace(
            cfg,
            mode=bot_section.get("mode", cfg.mode),
            state_db_path=Path(bot_section.get("state_db_path", cfg.state_db_path)),
            log_dir=Path(bot_section.get("log_dir", cfg.log_dir)),
            universe=tuple(data.get("universe", {}).get("assets", cfg.universe)),
            detector=_apply_section(cfg.detector, data.get("detector", {})),
            strategy=_apply_section(cfg.strategy, data.get("strategy", {})),
            risk=_apply_section(cfg.risk, data.get("risk", {})),
            hyperliquid=_apply_section(cfg.hyperliquid, data.get("hyperliquid", {})),
            observability=_apply_section(
                cfg.observability, data.get("observability", {}),
            ),
        )

    # Testnet defaults: only swap URLs if the user didn't already override.
    if cfg.hyperliquid.testnet:
        hl = cfg.hyperliquid
        if hl.rest_url == BotConfig().hyperliquid.rest_url:
            hl = replace(hl, rest_url=_HL_TESTNET_REST)
        if hl.ws_url == BotConfig().hyperliquid.ws_url:
            hl = replace(hl, ws_url=_HL_TESTNET_WS)
        cfg = replace(cfg, hyperliquid=hl)

    # Env-only secrets / addresses
    addr = os.environ.get("PHOENIX_HL_ACCOUNT_ADDRESS")
    if addr:
        cfg = replace(cfg, hyperliquid=replace(cfg.hyperliquid, account_address=addr))

    _validate(cfg)
    return cfg


def _validate(cfg: BotConfig) -> None:
    if cfg.mode not in ("paper", "live"):
        raise ValueError(
            f"Unknown mode {cfg.mode!r}; expected paper|live. (shadow mode "
            f"is on the roadmap but not yet implemented.)"
        )
    if cfg.detector.min_bars < 1:
        raise ValueError("detector.min_bars must be >= 1.")
    if cfg.detector.mult <= 0:
        raise ValueError("detector.mult must be > 0.")
    if not cfg.universe:
        raise ValueError("universe.assets must not be empty.")
    s = cfg.strategy
    if not (0 < s.entry_coeff < s.init_sl_coeff):
        raise ValueError("strategy: require 0 < entry_coeff < init_sl_coeff.")
    if abs((s.tp1_size + s.tp2_size + s.tp3_size) - 1.0) > 1e-9:
        raise ValueError("strategy: tp1_size + tp2_size + tp3_size must equal 1.0.")
    if cfg.risk.account_risk_pct <= 0 or cfg.risk.account_risk_pct > 100:
        raise ValueError("risk.account_risk_pct must be in (0, 100].")


_DEPRECATION_WARNED = False


def hl_agent_private_key() -> str | None:
    """Fetch the HL AGENT signing key from env on demand.

    Read order:
      1. PHOENIX_HL_AGENT_PRIVATE_KEY (canonical name).
      2. PHOENIX_HL_PRIVATE_KEY (deprecated; emits a warning ONCE per process
         if used).

    The agent key signs trades; it cannot withdraw. The master key (the
    Rabby-controlled wallet) must NEVER be set here. See the module docstring.
    """
    global _DEPRECATION_WARNED
    val = os.environ.get("PHOENIX_HL_AGENT_PRIVATE_KEY")
    if val:
        return val
    legacy = os.environ.get("PHOENIX_HL_PRIVATE_KEY")
    if legacy:
        if not _DEPRECATION_WARNED:
            import logging
            logging.getLogger(__name__).warning(
                "PHOENIX_HL_PRIVATE_KEY is deprecated; use "
                "PHOENIX_HL_AGENT_PRIVATE_KEY (this is your HL AGENT key, "
                "not your master wallet's key)."
            )
            _DEPRECATION_WARNED = True
        return legacy
    return None


# Legacy alias kept until callers migrate. NEW code should use
# hl_agent_private_key().
hl_private_key = hl_agent_private_key
