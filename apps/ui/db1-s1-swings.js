(function () {
  const API_BASE_URL = window.DB1_REVIEW_API_BASE_URL || "http://127.0.0.1:8080";
  const DEFAULT_VISIBLE_CANDLES = 24 * 7;
  const MIN_VISIBLE_CANDLES = 24 * 3;
  const MAX_VISIBLE_CANDLES = 24 * 10;
  const PAN_STEP_CANDLES = 24;
  const ZOOM_STEP_CANDLES = 24;
  const body = document.body;
  const state = {
    payload: null,
    visibleStartIndex: 0,
    visibleCount: DEFAULT_VISIBLE_CANDLES,
    selectedSwingIndex: null,
  };
  const elements = {
    marketCopy: document.getElementById("s1-market-copy"),
    detectorCopy: document.getElementById("s1-detector-copy"),
    candleCount: document.getElementById("s1-candle-count"),
    swingHighCount: document.getElementById("s1-swing-high-count"),
    swingLowCount: document.getElementById("s1-swing-low-count"),
    window: document.getElementById("s1-window"),
    viewportCopy: document.getElementById("s1-viewport-copy"),
    chart: document.getElementById("s1-chart"),
    swingRows: document.getElementById("s1-swing-rows"),
    panLeft: document.getElementById("s1-pan-left"),
    panRight: document.getElementById("s1-pan-right"),
    zoomIn: document.getElementById("s1-zoom-in"),
    zoomOut: document.getElementById("s1-zoom-out"),
  };

  wireEvents();
  boot();

  function wireEvents() {
    elements.panLeft.addEventListener("click", function () {
      shiftViewport(-PAN_STEP_CANDLES);
    });
    elements.panRight.addEventListener("click", function () {
      shiftViewport(PAN_STEP_CANDLES);
    });
    elements.zoomIn.addEventListener("click", function () {
      resizeViewport(-ZOOM_STEP_CANDLES);
    });
    elements.zoomOut.addEventListener("click", function () {
      resizeViewport(ZOOM_STEP_CANDLES);
    });
    elements.swingRows.addEventListener("click", function (event) {
      const target = event.target;
      const targetRow = target && target.closest ? target.closest("tr[data-swing-index]") : null;
      if (!targetRow) {
        return;
      }
      centerOnSwing(Number(targetRow.getAttribute("data-swing-index")));
    });
  }

  async function boot() {
    try {
      const payload = await fetchPayload();
      state.payload = payload;
      state.visibleCount = Math.min(
        MAX_VISIBLE_CANDLES,
        Math.max(MIN_VISIBLE_CANDLES, Math.min(DEFAULT_VISIBLE_CANDLES, payload.candles.length))
      );
      state.visibleStartIndex = Math.max(0, payload.candles.length - state.visibleCount);
      renderSummary(payload);
      renderInspectionSurface();
      body.dataset.db1S1State = "ready";
    } catch (error) {
      body.dataset.db1S1State = "error";
      elements.marketCopy.textContent = String(error.message || error);
    }
  }

  async function fetchPayload() {
    const response = await fetch(API_BASE_URL + "/db1/s1/swings");
    const payload = await response.json().catch(function () {
      return { error: "DB1.S1 swing payload was not valid JSON." };
    });
    if (!response.ok) {
      throw new Error(payload.error || "DB1.S1 swing request failed.");
    }
    return payload;
  }

  function renderSummary(payload) {
    const market = payload.market_contract;
    const detector = payload.detector;
    const summary = payload.summary;

    elements.marketCopy.textContent =
      market.human_label
      + " · "
      + market.timeframe
      + " · "
      + market.review_window;
    elements.detectorCopy.textContent = detector.description;
    elements.candleCount.textContent = String(summary.candle_count);
    elements.swingHighCount.textContent = String(summary.swing_high_count);
    elements.swingLowCount.textContent = String(summary.swing_low_count);
    elements.window.textContent =
      formatTimestamp(summary.source_start_timestamp)
      + " → "
      + formatTimestamp(summary.source_end_timestamp);
  }

  function renderInspectionSurface() {
    if (!state.payload) {
      return;
    }
    renderChart(state.payload.candles, state.payload.swing_highs, state.payload.swing_lows);
    renderSwingTable(state.payload.swing_highs, state.payload.swing_lows);
    renderViewportCopy();
    renderControlState();
  }

  function renderChart(candles, swingHighs, swingLows) {
    const chartHeight = 560;
    const padding = { top: 24, right: 24, bottom: 48, left: 76 };
    const plotHeight = chartHeight - padding.top - padding.bottom;
    const candleWidth = 10;
    const spacing = 4;
    const visibleCandles = candles.slice(
      state.visibleStartIndex,
      state.visibleStartIndex + state.visibleCount
    );
    const visibleEndIndex = state.visibleStartIndex + visibleCandles.length - 1;
    const plotWidth = visibleCandles.length * (candleWidth + spacing);
    const chartWidth = padding.left + padding.right + plotWidth;
    const priceMin = Math.min.apply(null, visibleCandles.map(function (candle) { return candle.low; }));
    const priceMax = Math.max.apply(null, visibleCandles.map(function (candle) { return candle.high; }));
    const priceRange = Math.max(priceMax - priceMin, 1);
    const gridLevels = 6;
    const fragments = [];

    fragments.push(
      '<rect x="0" y="0" width="' + chartWidth + '" height="' + chartHeight + '" fill="#fffdf9"></rect>'
    );

    for (let level = 0; level <= gridLevels; level += 1) {
      const ratio = level / gridLevels;
      const y = padding.top + ratio * plotHeight;
      const price = priceMax - ratio * priceRange;
      fragments.push(
        '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (chartWidth - padding.right) + '" y2="' + y + '" stroke="rgba(24,32,42,0.10)" stroke-width="1"></line>'
      );
      fragments.push(
        '<text x="' + (padding.left - 12) + '" y="' + (y + 4) + '" text-anchor="end" font-size="12" fill="#5c6670">' + formatPrice(price) + '</text>'
      );
    }

    visibleCandles.forEach(function (candle, visibleIndex) {
      const x = padding.left + visibleIndex * (candleWidth + spacing);
      const centerX = x + candleWidth / 2;
      const openY = mapPrice(candle.open, priceMin, priceRange, plotHeight, padding.top);
      const closeY = mapPrice(candle.close, priceMin, priceRange, plotHeight, padding.top);
      const highY = mapPrice(candle.high, priceMin, priceRange, plotHeight, padding.top);
      const lowY = mapPrice(candle.low, priceMin, priceRange, plotHeight, padding.top);
      const bodyY = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5);
      const bodyColor = candle.close >= candle.open ? '#1c8c74' : '#d65252';
      fragments.push(
        '<line x1="' + centerX + '" y1="' + highY + '" x2="' + centerX + '" y2="' + lowY + '" stroke="' + bodyColor + '" stroke-width="1.25"></line>'
      );
      fragments.push(
        '<rect x="' + x + '" y="' + bodyY + '" width="' + candleWidth + '" height="' + bodyHeight + '" fill="' + bodyColor + '" rx="1"></rect>'
      );

      if (visibleIndex % 24 === 0) {
        fragments.push(
          '<text x="' + centerX + '" y="' + (chartHeight - 14) + '" text-anchor="middle" font-size="11" fill="#5c6670">' + formatShortTimestamp(candle.source_timestamp) + '</text>'
        );
      }
    });

    swingHighs.forEach(function (swing) {
      if (swing.index < state.visibleStartIndex || swing.index > visibleEndIndex) {
        return;
      }
      const visibleIndex = swing.index - state.visibleStartIndex;
      const centerX = padding.left + visibleIndex * (candleWidth + spacing) + candleWidth / 2;
      const y = mapPrice(swing.price, priceMin, priceRange, plotHeight, padding.top) - 10;
      fragments.push(
        '<polygon points="' + centerX + ',' + (y - 8) + ' ' + (centerX - 7) + ',' + y + ' ' + (centerX + 7) + ',' + y + '" fill="#c14b3d"></polygon>'
      );
      if (swing.index === state.selectedSwingIndex) {
        fragments.push(
          '<circle cx="' + centerX + '" cy="' + (y - 2) + '" r="12" fill="none" stroke="#c14b3d" stroke-width="2"></circle>'
        );
      }
    });

    swingLows.forEach(function (swing) {
      if (swing.index < state.visibleStartIndex || swing.index > visibleEndIndex) {
        return;
      }
      const visibleIndex = swing.index - state.visibleStartIndex;
      const centerX = padding.left + visibleIndex * (candleWidth + spacing) + candleWidth / 2;
      const y = mapPrice(swing.price, priceMin, priceRange, plotHeight, padding.top) + 10;
      fragments.push(
        '<polygon points="' + centerX + ',' + (y + 8) + ' ' + (centerX - 7) + ',' + y + ' ' + (centerX + 7) + ',' + y + '" fill="#287a72"></polygon>'
      );
      if (swing.index === state.selectedSwingIndex) {
        fragments.push(
          '<circle cx="' + centerX + '" cy="' + (y + 2) + '" r="12" fill="none" stroke="#287a72" stroke-width="2"></circle>'
        );
      }
    });

    elements.chart.setAttribute("viewBox", "0 0 " + chartWidth + " " + chartHeight);
    elements.chart.setAttribute("width", String(chartWidth));
    elements.chart.setAttribute("height", String(chartHeight));
    elements.chart.innerHTML = fragments.join("");
  }

  function renderSwingTable(swingHighs, swingLows) {
    const swings = swingHighs.concat(swingLows).sort(function (left, right) {
      return left.index - right.index;
    });

    elements.swingRows.innerHTML = swings.map(function (swing) {
      const selectedClass = swing.index === state.selectedSwingIndex ? ' is-selected' : '';
      return '<tr class="' + selectedClass.trim() + '" data-kind="' + swing.kind + '" data-swing-index="' + swing.index + '">' +
        '<td>' + swing.index + '</td>' +
        '<td>' + swing.kind + '</td>' +
        '<td>' + formatTimestamp(swing.source_timestamp) + '</td>' +
        '<td>' + formatPrice(swing.price) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderViewportCopy() {
    if (!state.payload) {
      return;
    }
    const visibleCandles = state.payload.candles.slice(
      state.visibleStartIndex,
      state.visibleStartIndex + state.visibleCount
    );
    if (visibleCandles.length === 0) {
      elements.viewportCopy.textContent = 'No visible candles.';
      return;
    }
    elements.viewportCopy.textContent =
      'Showing '
      + visibleCandles.length
      + ' candles · '
      + formatTimestamp(visibleCandles[0].source_timestamp)
      + ' → '
      + formatTimestamp(visibleCandles[visibleCandles.length - 1].source_timestamp);
  }

  function renderControlState() {
    if (!state.payload) {
      return;
    }
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    elements.panLeft.disabled = state.visibleStartIndex <= 0;
    elements.panRight.disabled = state.visibleStartIndex >= maxStart;
    elements.zoomIn.disabled = state.visibleCount <= MIN_VISIBLE_CANDLES;
    elements.zoomOut.disabled = state.visibleCount >= Math.min(MAX_VISIBLE_CANDLES, state.payload.candles.length);
  }

  function shiftViewport(delta) {
    if (!state.payload) {
      return;
    }
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(state.visibleStartIndex + delta, 0, maxStart);
    renderInspectionSurface();
  }

  function resizeViewport(delta) {
    if (!state.payload) {
      return;
    }
    const currentCenter = state.visibleStartIndex + Math.floor(state.visibleCount / 2);
    state.visibleCount = clamp(
      state.visibleCount + delta,
      MIN_VISIBLE_CANDLES,
      Math.min(MAX_VISIBLE_CANDLES, state.payload.candles.length)
    );
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(currentCenter - Math.floor(state.visibleCount / 2), 0, maxStart);
    renderInspectionSurface();
  }

  function centerOnSwing(swingIndex) {
    if (!state.payload || !Number.isFinite(swingIndex)) {
      return;
    }
    state.selectedSwingIndex = swingIndex;
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(swingIndex - Math.floor(state.visibleCount / 2), 0, maxStart);
    renderInspectionSurface();
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function mapPrice(price, priceMin, priceRange, plotHeight, topPadding) {
    const ratio = (price - priceMin) / priceRange;
    return topPadding + plotHeight - ratio * plotHeight;
  }

  function formatTimestamp(value) {
    return String(value || '').replace('T', ' ');
  }

  function formatShortTimestamp(value) {
    return formatTimestamp(value).slice(5, 16);
  }

  function formatPrice(value) {
    return Number(value).toFixed(1);
  }
})();