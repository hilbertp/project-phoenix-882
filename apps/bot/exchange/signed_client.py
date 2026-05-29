"""Signed Hyperliquid client — the surface the OrderManager needs.

Wraps hyperliquid.exchange.Exchange and hyperliquid.info.Info into a narrow,
strategy-shaped API:

  place_limit_post_only(...)   -- entry orders sit as makers
  place_reduce_only_limit(...) -- TP1/TP2/TP3 partials, never increase position
  place_stop_market(...)       -- initial 1.05 SL (exchange-side trigger)
  cancel(...)                  -- by cloid; idempotent: cancelling an unknown
                                  cloid is treated as success
  market_close(...)            -- BE-stop fallback and operator kill switch
  open_orders()                -- reconciler input
  positions()                  -- reconciler input
  fills_since(start_ms)        -- fill reconciliation

The SDK takes a `eth_account.LocalAccount` for signing. We construct it from
the env-only private key on first use and never log or persist the key. The
account_address may be different from the wallet address when an agent wallet
is in use; we forward both to the SDK.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils.types import Cloid

from apps.bot.logging_setup import get_logger
from apps.bot.observability import metrics as _m

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlacedOrder:
    """Normalized response from a successful order placement."""

    cloid: str
    exchange_order_id: int | None  # HL "oid"; None if resting status not yet known
    status: str                    # "resting" | "filled" | "rejected"
    raw: dict


@dataclass(frozen=True, slots=True)
class Position:
    coin: str
    size: float   # signed: positive long, negative short
    entry_px: float
    unrealized_pnl: float
    raw: dict


@dataclass(frozen=True, slots=True)
class OpenOrder:
    coin: str
    cloid: str | None
    oid: int
    side: str         # "B" (buy) | "A" (sell)
    qty: float
    price: float
    reduce_only: bool
    raw: dict


@dataclass(frozen=True, slots=True)
class Fill:
    coin: str
    cloid: str | None
    oid: int
    qty: float
    price: float
    fee: float
    time_ms: int
    side: str
    raw: dict


class SignedHyperliquidClient:
    """Thin signed wrapper around the HL SDK using an agent key.

    Trust model: the agent private key signs every trade; the master account
    address (the user's Rabby-controlled wallet) is the account positions
    settle against. The bot NEVER sees the master key — that lives in Rabby
    and is only used once to approve this agent.

    NEVER write or log the agent private key. The Account is constructed
    once on init and held only on the Exchange instance (the SDK requires it).
    """

    def __init__(
        self,
        *,
        agent_private_key: str,
        master_account_address: str,
        rest_url: str,
        error_counter=None,
    ):
        if not agent_private_key or not master_account_address:
            raise ValueError(
                "agent_private_key and master_account_address are both "
                "required; set PHOENIX_HL_AGENT_PRIVATE_KEY and "
                "PHOENIX_HL_ACCOUNT_ADDRESS."
            )
        wallet = Account.from_key(agent_private_key)
        # Cache the agent's derived address so we can verify HL approval
        # without re-deriving from the key (or storing the key).
        self.agent_address: str = wallet.address
        self.master_address: str = master_account_address
        # Back-compat alias for callers that haven't migrated yet.
        self.account_address: str = master_account_address
        self.error_counter = error_counter
        self._info = Info(base_url=rest_url, skip_ws=True)
        self._exchange = Exchange(
            wallet=wallet, base_url=rest_url,
            account_address=master_account_address,
        )

    # --- agent approval check -------------------------------------------

    def agent_is_approved(self) -> bool:
        """True iff the agent's address is currently listed for the master.

        HL exposes the approved-agent set via Info.extra_agents(master).
        If the agent has been revoked (or never approved), every signed
        action returns "ApprovedAgent missing" — better to fail fast at
        startup.
        """
        try:
            agents = self._info_call(
                self._info.extra_agents, self.master_address,
            ) or []
        except Exception:
            log.exception("extra_agents query failed",
                          extra={"master": self.master_address})
            return False
        target = self.agent_address.lower()
        for entry in agents:
            addr = (entry.get("address") if isinstance(entry, dict)
                    else entry)
            if addr and str(addr).lower() == target:
                return True
        return False

    # --- order placement -------------------------------------------------

    def place_limit_post_only(
        self, coin: str, is_buy: bool, qty: float, price: float, cloid: str,
    ) -> PlacedOrder:
        """Maker-only limit. HL rejects with 'PostOnly' if the price would cross."""
        return self._submit_order(
            coin=coin, is_buy=is_buy, qty=qty, price=price,
            order_type={"limit": {"tif": "Alo"}},
            reduce_only=False, cloid=cloid,
        )

    def place_reduce_only_limit(
        self, coin: str, is_buy: bool, qty: float, price: float, cloid: str,
    ) -> PlacedOrder:
        """TP partial. reduce_only guards against accidentally growing the position."""
        return self._submit_order(
            coin=coin, is_buy=is_buy, qty=qty, price=price,
            order_type={"limit": {"tif": "Gtc"}},
            reduce_only=True, cloid=cloid,
        )

    def place_stop_market(
        self, coin: str, is_buy: bool, qty: float, trigger_px: float, cloid: str,
        *, slippage_tolerance: float = 0.05,
    ) -> PlacedOrder:
        """Exchange-side stop-market that flips to market on trigger price.

        Used for the initial 1.05 SL. After TP1 the bot cancels this and holds
        the BE stop in software (PRD §6.1: close-based, not wick-based).

        IMPORTANT — `limit_px` semantics on HL: this is the WORST acceptable
        price for the eventual market fill, not the trigger. Setting
        limit_px == trigger_px is a footgun: when a sell-stop triggers, the
        market is below the trigger by definition, so a limit at the trigger
        won't cross the book and the order won't fill. We aim the limit a
        configurable `slippage_tolerance` (default 5%) in the direction the
        market will be moving on trigger.
        """
        if is_buy:
            # Stop fires when price rises to trigger; market is ABOVE trigger
            # by the time we cross, so we accept a higher limit.
            limit_px = trigger_px * (1.0 + slippage_tolerance)
        else:
            # Sell-stop: market is BELOW trigger; accept a lower limit.
            limit_px = trigger_px * (1.0 - slippage_tolerance)
        order_type = {
            "trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": "sl"},
        }
        return self._submit_order(
            coin=coin, is_buy=is_buy, qty=qty, price=limit_px,
            order_type=order_type, reduce_only=True, cloid=cloid,
        )

    def market_close(
        self, coin: str, qty: float, cloid: str, slippage: float = 0.05,
    ) -> PlacedOrder:
        """Cross the book to flatten. Used for software BE stop + kill switch."""
        with _m.TimeRest():
            try:
                raw = self._exchange.market_close(
                    coin=coin, sz=qty, slippage=slippage,
                    cloid=Cloid.from_str(cloid),
                )
            except Exception:
                if self.error_counter is not None:
                    self.error_counter.record("rest")
                raise
        return _parse_order_response(raw, cloid)

    def cancel(self, coin: str, cloid: str) -> dict:
        """Cancel by cloid. Returns the raw exchange response."""
        with _m.TimeRest():
            try:
                return self._exchange.cancel_by_cloid(
                    coin, Cloid.from_str(cloid),
                )
            except Exception:
                if self.error_counter is not None:
                    self.error_counter.record("rest")
                raise

    def _submit_order(
        self, *, coin: str, is_buy: bool, qty: float, price: float,
        order_type: dict, reduce_only: bool, cloid: str,
    ) -> PlacedOrder:
        with _m.TimeRest():
            try:
                raw = self._exchange.order(
                    name=coin, is_buy=is_buy, sz=qty, limit_px=price,
                    order_type=order_type, reduce_only=reduce_only,
                    cloid=Cloid.from_str(cloid),
                )
            except Exception:
                if self.error_counter is not None:
                    self.error_counter.record("rest")
                raise
        return _parse_order_response(raw, cloid)

    # --- read endpoints --------------------------------------------------

    def _info_call(self, method, *args, **kwargs):
        """Wrap an Info.* call with REST latency + error counting.

        All read endpoints route through here so the kill-switch error
        budget (§7.3) and the latency histograms (§8.2) are consistent
        across every signed-side REST call.
        """
        with _m.TimeRest():
            try:
                return method(*args, **kwargs)
            except Exception:
                if self.error_counter is not None:
                    self.error_counter.record("rest")
                raise

    def open_orders(self) -> list[OpenOrder]:
        raw = self._info_call(self._info.open_orders, self.account_address)
        return [_open_order_from_payload(o) for o in raw or []]

    def positions(self) -> list[Position]:
        raw = self._info_call(
            self._info.user_state, self.account_address,
        ) or {}
        out: list[Position] = []
        for p in (raw.get("assetPositions") or []):
            pos = p.get("position") or {}
            sz = float(pos.get("szi") or 0)
            if sz == 0:
                continue
            out.append(Position(
                coin=pos.get("coin", ""),
                size=sz,
                entry_px=float(pos.get("entryPx") or 0),
                unrealized_pnl=float(pos.get("unrealizedPnl") or 0),
                raw=pos,
            ))
        return out

    def fetch_size_decimals(self) -> dict[str, int]:
        """Return coin -> szDecimals from HL's perp meta.

        HL rejects orders whose qty has more decimal places than szDecimals
        (e.g. BTC szDecimals=5 -> qty must round to 0.00001 BTC). The
        OrderManager uses this map to round position sizes at arming.
        """
        raw = self._info_call(self._info.meta) or {}
        out: dict[str, int] = {}
        for u in raw.get("universe") or []:
            name = u.get("name")
            sz = u.get("szDecimals")
            if name and sz is not None:
                out[str(name)] = int(sz)
        return out

    def fetch_funding_rates_apy(self) -> dict[str, float]:
        """Return coin -> CURRENT annualized funding rate (%, positive or
        negative).

        Hyperliquid quotes `funding` per hour as a fraction (e.g. 0.0000125
        = 0.00125%/hr). Annualized = funding * 24 * 365 * 100.

        Used by the funding-skip watcher (PRD §7.2). The bot pauses entries
        on assets whose adverse funding exceeds the configured APY threshold
        (default 100%).
        """
        ctx = self._info_call(self._info.meta_and_asset_ctxs) or []
        out: dict[str, float] = {}
        # HL returns [meta_dict, [asset_ctx_list]]. The order of asset_ctx
        # mirrors meta.universe.
        if not isinstance(ctx, list) or len(ctx) < 2:
            return out
        meta_part, asset_ctxs = ctx[0], ctx[1]
        universe = (meta_part or {}).get("universe") or []
        for u, c in zip(universe, asset_ctxs):
            name = u.get("name")
            funding_hourly = c.get("funding") if isinstance(c, dict) else None
            if name and funding_hourly is not None:
                try:
                    f = float(funding_hourly)
                except (TypeError, ValueError):
                    continue
                out[str(name)] = f * 24.0 * 365.0 * 100.0
        return out

    def fetch_max_leverage(self) -> dict[str, int]:
        """Return coin -> maxLeverage from HL's perp meta.

        HL enforces per-asset leverage caps (BTC=40, ATOM=5, etc.). The
        OrderManager refuses to arm any position whose notional would
        exceed `equity * maxLeverage[asset]`, satisfying PRD §7.1's
        requirement that the strategy's 1.05 stop sit inside the
        exchange-imposed liquidation price.
        """
        raw = self._info_call(self._info.meta) or {}
        out: dict[str, int] = {}
        for u in raw.get("universe") or []:
            name = u.get("name")
            lev = u.get("maxLeverage")
            if name and lev is not None:
                out[str(name)] = int(lev)
        return out

    def fills_since(self, start_ms: int) -> list[Fill]:
        raw = self._info_call(
            self._info.user_fills_by_time, self.account_address,
        ) or []
        out: list[Fill] = []
        for f in raw:
            t = int(f.get("time") or 0)
            if t < start_ms:
                continue
            out.append(Fill(
                coin=f.get("coin", ""),
                cloid=f.get("cloid"),
                oid=int(f.get("oid") or 0),
                qty=float(f.get("sz") or 0),
                price=float(f.get("px") or 0),
                fee=float(f.get("fee") or 0),
                time_ms=t,
                side=f.get("side", ""),
                raw=f,
            ))
        return out


def _parse_order_response(raw: Any, cloid: str) -> PlacedOrder:
    """HL returns {'status': 'ok'/'err', 'response': {'data': {'statuses': [...]}}}."""
    if not isinstance(raw, dict) or raw.get("status") != "ok":
        return PlacedOrder(cloid=cloid, exchange_order_id=None,
                           status="rejected", raw=raw if isinstance(raw, dict) else {})
    statuses = (raw.get("response") or {}).get("data", {}).get("statuses") or []
    if not statuses:
        return PlacedOrder(cloid=cloid, exchange_order_id=None,
                           status="rejected", raw=raw)
    first = statuses[0]
    if "resting" in first:
        return PlacedOrder(cloid=cloid, exchange_order_id=first["resting"].get("oid"),
                           status="resting", raw=raw)
    if "filled" in first:
        return PlacedOrder(cloid=cloid, exchange_order_id=first["filled"].get("oid"),
                           status="filled", raw=raw)
    if "error" in first:
        return PlacedOrder(cloid=cloid, exchange_order_id=None,
                           status="rejected", raw=raw)
    return PlacedOrder(cloid=cloid, exchange_order_id=None,
                       status="unknown", raw=raw)


def _open_order_from_payload(o: dict) -> OpenOrder:
    return OpenOrder(
        coin=o.get("coin", ""),
        cloid=o.get("cloid"),
        oid=int(o.get("oid") or 0),
        side=o.get("side", ""),
        qty=float(o.get("sz") or 0),
        price=float(o.get("limitPx") or 0),
        reduce_only=bool(o.get("reduceOnly", False)),
        raw=o,
    )
