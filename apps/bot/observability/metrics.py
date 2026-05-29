"""Prometheus-style metrics registry — no external dependency.

Why hand-rolled: the bot already runs threads + a state DB; adding the
`prometheus_client` dependency just for emission is overkill, and the
text-format spec is short. This module gives the same shape — counters,
gauges, histograms with labels — and emits the standard text exposition
format that any Prometheus scraper will consume.

Thread-safe via a single registry lock around sample mutations. The
HTTP server is a stdlib `BaseHTTPRequestHandler` on a daemon thread.

PRD §8.2 metric catalogue (the registry is populated by `register_all()`
at bot startup, then individual call sites do `metric.inc()` /
`.observe()` / `.set()`):

  bot_open_positions{asset}            gauge
  bot_armed_entries{asset}             gauge
  bot_trades_total{asset,outcome}      counter
  bot_realized_r{asset}                counter (float-valued)
  bot_ws_latency_ms                    histogram
  bot_rest_latency_ms                  histogram
  bot_errors_total{kind}               counter
  bot_funding_apy{asset}               gauge
  bot_risk_denials_total{reason}       counter
"""
from __future__ import annotations

import bisect
import http.server
import socketserver
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from apps.bot.logging_setup import get_logger

log = get_logger(__name__)


# --- type primitives ---------------------------------------------------

LabelDict = dict[str, str]


def _labels_to_key(labels: LabelDict) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


def _format_labels(labels: LabelDict) -> str:
    if not labels:
        return ""
    parts = ",".join(
        f'{k}="{v}"' for k, v in sorted(labels.items())
    )
    return "{" + parts + "}"


@dataclass
class _BaseMetric:
    name: str
    help_text: str
    label_names: tuple[str, ...] = ()
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _check_labels(self, labels: LabelDict) -> None:
        if set(labels.keys()) != set(self.label_names):
            raise ValueError(
                f"metric {self.name} expects labels "
                f"{sorted(self.label_names)}; got {sorted(labels.keys())}"
            )

    # Subclasses implement render_lines.
    def render_lines(self) -> list[str]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class Counter(_BaseMetric):
    """Monotonically-increasing value per label set."""
    _values: dict = field(default_factory=lambda: defaultdict(float))

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self._check_labels(labels)
        with self._lock:
            self._values[_labels_to_key(labels)] += amount

    def render_lines(self) -> list[str]:
        out = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            items = list(self._values.items())
        for key, val in items:
            labels = dict(key)
            out.append(f"{self.name}{_format_labels(labels)} {val}")
        return out


@dataclass
class Gauge(_BaseMetric):
    """Last-set value per label set."""
    _values: dict = field(default_factory=dict)

    def set(self, value: float, **labels: str) -> None:
        self._check_labels(labels)
        with self._lock:
            self._values[_labels_to_key(labels)] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self._check_labels(labels)
        with self._lock:
            self._values[_labels_to_key(labels)] = (
                self._values.get(_labels_to_key(labels), 0.0) + amount
            )

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def render_lines(self) -> list[str]:
        out = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            items = list(self._values.items())
        for key, val in items:
            labels = dict(key)
            out.append(f"{self.name}{_format_labels(labels)} {val}")
        return out


# Default histogram buckets in ms — appropriate for both REST and WS latency.
DEFAULT_LATENCY_BUCKETS_MS = (
    1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000,
)


@dataclass
class Histogram(_BaseMetric):
    """Cumulative buckets + sum + count per label set."""
    buckets_ms: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS_MS
    _buckets: dict = field(default_factory=lambda: defaultdict(
        lambda: [0] * (len(DEFAULT_LATENCY_BUCKETS_MS) + 1)
    ))
    _sums: dict = field(default_factory=lambda: defaultdict(float))
    _counts: dict = field(default_factory=lambda: defaultdict(int))

    def observe(self, value_ms: float, **labels: str) -> None:
        self._check_labels(labels)
        key = _labels_to_key(labels)
        idx = bisect.bisect_left(self.buckets_ms, value_ms)
        with self._lock:
            # Cumulative buckets: increment THIS bucket and every higher one.
            bucket_array = self._buckets[key]
            if len(bucket_array) != len(self.buckets_ms) + 1:
                bucket_array.extend(
                    [0] * (len(self.buckets_ms) + 1 - len(bucket_array))
                )
            for i in range(idx, len(self.buckets_ms) + 1):
                bucket_array[i] += 1
            self._sums[key] += value_ms
            self._counts[key] += 1

    def render_lines(self) -> list[str]:
        out = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            keys = list(self._buckets.keys())
        for key in keys:
            labels = dict(key)
            with self._lock:
                buckets = list(self._buckets[key])
                sum_val = self._sums[key]
                cnt = self._counts[key]
            label_parts = _format_labels({**labels})
            label_parts_no_braces = label_parts.strip("{}")
            sep = "," if label_parts_no_braces else ""
            for upper, count in zip(self.buckets_ms, buckets[:-1]):
                out.append(
                    f'{self.name}_bucket{{le="{upper}"{sep}'
                    f"{label_parts_no_braces}}} {count}"
                )
            out.append(
                f'{self.name}_bucket{{le="+Inf"{sep}'
                f"{label_parts_no_braces}}} {buckets[-1]}"
            )
            out.append(f"{self.name}_sum{label_parts} {sum_val}")
            out.append(f"{self.name}_count{label_parts} {cnt}")
        return out


# --- registry ----------------------------------------------------------

class _Registry:
    def __init__(self):
        self._metrics: dict[str, _BaseMetric] = {}
        self._lock = threading.Lock()

    def register(self, metric: _BaseMetric) -> None:
        with self._lock:
            if metric.name in self._metrics:
                raise ValueError(
                    f"metric {metric.name!r} already registered"
                )
            self._metrics[metric.name] = metric

    def get(self, name: str) -> _BaseMetric | None:
        with self._lock:
            return self._metrics.get(name)

    def all(self) -> list[_BaseMetric]:
        with self._lock:
            return list(self._metrics.values())

    def render(self) -> str:
        lines: list[str] = []
        for m in self.all():
            lines.extend(m.render_lines())
        return "\n".join(lines) + "\n"


# Process-wide singleton. The bot creates one of these at startup.
_GLOBAL_REGISTRY: _Registry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> _Registry:
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = _Registry()
        return _GLOBAL_REGISTRY


def reset_for_tests() -> None:
    """Wipe the singleton — only call from test fixtures."""
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        _GLOBAL_REGISTRY = None


# --- canonical metric set (PRD §8.2) -----------------------------------

# Sentinel singletons exposed for instrumentation call sites. The bot
# calls register_all() once at startup to populate the registry; after
# that any module can do `from apps.bot.observability.metrics import M`
# and call M.inc()/.set()/.observe().
M_OPEN_POSITIONS: Gauge | None = None
M_ARMED_ENTRIES: Gauge | None = None
M_TRADES_TOTAL: Counter | None = None
M_REALIZED_R: Counter | None = None
M_WS_LATENCY: Histogram | None = None
M_REST_LATENCY: Histogram | None = None
M_ERRORS: Counter | None = None
M_FUNDING_APY: Gauge | None = None
M_RISK_DENIALS: Counter | None = None


def register_all() -> None:
    """Register the PRD §8.2 metric catalogue. Idempotent."""
    global M_OPEN_POSITIONS, M_ARMED_ENTRIES, M_TRADES_TOTAL, M_REALIZED_R
    global M_WS_LATENCY, M_REST_LATENCY, M_ERRORS, M_FUNDING_APY
    global M_RISK_DENIALS
    reg = get_registry()
    if reg.get("bot_open_positions") is not None:
        return  # already registered

    M_OPEN_POSITIONS = Gauge(
        name="bot_open_positions",
        help_text="In-flight positions per asset",
        label_names=("asset",),
    )
    M_ARMED_ENTRIES = Gauge(
        name="bot_armed_entries",
        help_text="Setups in ARMED state per asset",
        label_names=("asset",),
    )
    M_TRADES_TOTAL = Counter(
        name="bot_trades_total",
        help_text="Total trades by outcome per asset",
        label_names=("asset", "outcome"),
    )
    M_REALIZED_R = Counter(
        name="bot_realized_r",
        help_text=(
            "Realized R per asset (counter; grows non-monotonically"
            " when wins/losses cancel)"
        ),
        label_names=("asset",),
    )
    M_WS_LATENCY = Histogram(
        name="bot_ws_latency_ms",
        help_text="WS message latency (ms) from exchange to receipt",
    )
    M_REST_LATENCY = Histogram(
        name="bot_rest_latency_ms",
        help_text="REST call round-trip (ms)",
    )
    M_ERRORS = Counter(
        name="bot_errors_total",
        help_text="Total error events per kind",
        label_names=("kind",),
    )
    M_FUNDING_APY = Gauge(
        name="bot_funding_apy",
        help_text="Last-observed annualized funding rate (%) per asset",
        label_names=("asset",),
    )
    M_RISK_DENIALS = Counter(
        name="bot_risk_denials_total",
        help_text="Risk-engine denial count per reason",
        label_names=("reason",),
    )

    for m in (
        M_OPEN_POSITIONS, M_ARMED_ENTRIES, M_TRADES_TOTAL, M_REALIZED_R,
        M_WS_LATENCY, M_REST_LATENCY, M_ERRORS, M_FUNDING_APY,
        M_RISK_DENIALS,
    ):
        reg.register(m)


# --- HTTP exposition ---------------------------------------------------

class _MetricsHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = get_registry().render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802
        # Silence the default stderr access log; we have our own.
        return


class _ThreadedHTTPServer(socketserver.ThreadingMixIn,
                           http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MetricsServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9100):
        self.host = host
        self.port = port
        self._server: _ThreadedHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = _ThreadedHTTPServer(
            (self.host, self.port), _MetricsHandler,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="metrics-http", daemon=True,
        )
        self._thread.start()
        log.info("metrics server started",
                 extra={"host": self.host, "port": self.port})

    def stop(self, timeout_s: float = 2.0) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._server = None
        self._thread = None


# --- timing helpers ---------------------------------------------------

class TimeRest:
    """Context-manager that records REST latency to M_REST_LATENCY."""

    def __enter__(self) -> "TimeRest":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        elapsed_ms = (time.monotonic() - self._t0) * 1000.0
        if M_REST_LATENCY is not None:
            M_REST_LATENCY.observe(elapsed_ms)
