(function () {
  const API_BASE_URL = window.DB1_REVIEW_API_BASE_URL || "http://127.0.0.1:8000";
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
    selectedCandidateId: null,
  };
  const elements = {
    marketCopy: document.getElementById("s2-market-copy"),
    ruleCopy: document.getElementById("s2-rule-copy"),
    rawPivotCount: document.getElementById("s2-raw-pivot-count"),
    altPivotCount: document.getElementById("s2-alt-pivot-count"),
    candidateCount: document.getElementById("s2-candidate-count"),
    displayedCount: document.getElementById("s2-displayed-count"),
    viewportCopy: document.getElementById("s2-viewport-copy"),
    chart: document.getElementById("s2-chart"),
    candidateRows: document.getElementById("s2-candidate-rows"),
    panLeft: document.getElementById("s2-pan-left"),
    panRight: document.getElementById("s2-pan-right"),
    zoomIn: document.getElementById("s2-zoom-in"),
    zoomOut: document.getElementById("s2-zoom-out"),
  };

  wireEvents();
  boot();

  function wireEvents() {
    elements.panLeft.addEventListener("click", function () { shiftViewport(-PAN_STEP_CANDLES); });
    elements.panRight.addEventListener("click", function () { shiftViewport(PAN_STEP_CANDLES); });
    elements.zoomIn.addEventListener("click", function () { resizeViewport(-ZOOM_STEP_CANDLES); });
    elements.zoomOut.addEventListener("click", function () { resizeViewport(ZOOM_STEP_CANDLES); });
    elements.candidateRows.addEventListener("click", function (event) {
      const target = event.target;
      const row = target && target.closest ? target.closest("tr[data-candidate-id]") : null;
      if (!row) {
        return;
      }
      centerOnCandidate(String(row.getAttribute("data-candidate-id") || ""));
    });
  }

  async function boot() {
    try {
      const payload = await fetchPayload();
      state.payload = payload;
      const selectedCandidate = payload.candidate_legs[0] || null;
      state.selectedCandidateId = selectedCandidate ? selectedCandidate.candidate_id : null;
      state.visibleCount = Math.min(MAX_VISIBLE_CANDLES, Math.max(MIN_VISIBLE_CANDLES, Math.min(DEFAULT_VISIBLE_CANDLES, payload.candles.length)));
      if (selectedCandidate) {
        const centerIndex = Math.round((selectedCandidate.start_pivot.index + selectedCandidate.end_pivot.index) / 2);
        state.visibleStartIndex = clamp(centerIndex - Math.floor(state.visibleCount / 2), 0, Math.max(0, payload.candles.length - state.visibleCount));
      }
      renderSummary(payload);
      renderInspectionSurface();
      body.dataset.db1S2State = "ready";
    } catch (error) {
      body.dataset.db1S2State = "error";
      elements.marketCopy.textContent = String(error.message || error);
    }
  }

  async function fetchPayload() {
    const response = await fetch(API_BASE_URL + "/db1/s2/candidate-legs");
    const payload = await response.json().catch(function () {
      return { error: "DB1.S2 candidate payload was not valid JSON." };
    });
    if (!response.ok) {
      throw new Error(payload.error || "DB1.S2 candidate request failed.");
    }
    return payload;
  }

  function renderSummary(payload) {
    elements.marketCopy.textContent = payload.market_contract.human_label + " · " + payload.market_contract.timeframe + " · " + payload.market_contract.review_window;
    elements.ruleCopy.textContent = payload.detector.candidate_leg_rule.description;
    elements.rawPivotCount.textContent = String(payload.summary.raw_pivot_count);
    elements.altPivotCount.textContent = String(payload.summary.alternating_pivot_count);
    elements.candidateCount.textContent = String(payload.summary.candidate_leg_count);
    elements.displayedCount.textContent = String(payload.summary.displayed_candidate_count);
  }

  function renderInspectionSurface() {
    if (!state.payload) {
      return;
    }
    renderChart();
    renderCandidateTable();
    renderViewportCopy();
    renderControlState();
  }

  function renderChart() {
    const candles = state.payload.candles;
    const rawPivots = state.payload.raw_pivots;
    const selectedCandidate = findSelectedCandidate();
    const chartHeight = 560;
    const padding = { top: 24, right: 24, bottom: 48, left: 76 };
    const plotHeight = chartHeight - padding.top - padding.bottom;
    const candleWidth = 10;
    const spacing = 4;
    const visibleCandles = candles.slice(state.visibleStartIndex, state.visibleStartIndex + state.visibleCount);
    const visibleEndIndex = state.visibleStartIndex + visibleCandles.length - 1;
    const plotWidth = visibleCandles.length * (candleWidth + spacing);
    const chartWidth = padding.left + padding.right + plotWidth;
    const priceMin = Math.min.apply(null, visibleCandles.map(function (candle) { return candle.low; }));
    const priceMax = Math.max.apply(null, visibleCandles.map(function (candle) { return candle.high; }));
    const priceRange = Math.max(priceMax - priceMin, 1);
    const fragments = [];
    fragments.push('<rect x="0" y="0" width="' + chartWidth + '" height="' + chartHeight + '" fill="#fffdf9"></rect>');
    for (let level = 0; level <= 6; level += 1) {
      const ratio = level / 6;
      const y = padding.top + ratio * plotHeight;
      const price = priceMax - ratio * priceRange;
      fragments.push('<line x1="' + padding.left + '" y1="' + y + '" x2="' + (chartWidth - padding.right) + '" y2="' + y + '" stroke="rgba(24,32,42,0.10)" stroke-width="1"></line>');
      fragments.push('<text x="' + (padding.left - 12) + '" y="' + (y + 4) + '" text-anchor="end" font-size="12" fill="#5c6670">' + formatPrice(price) + '</text>');
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
      fragments.push('<line x1="' + centerX + '" y1="' + highY + '" x2="' + centerX + '" y2="' + lowY + '" stroke="' + bodyColor + '" stroke-width="1.25"></line>');
      fragments.push('<rect x="' + x + '" y="' + bodyY + '" width="' + candleWidth + '" height="' + bodyHeight + '" fill="' + bodyColor + '" rx="1"></rect>');
      if (visibleIndex % 24 === 0) {
        fragments.push('<text x="' + centerX + '" y="' + (chartHeight - 14) + '" text-anchor="middle" font-size="11" fill="#5c6670">' + formatShortTimestamp(candle.source_timestamp) + '</text>');
      }
    });
    rawPivots.forEach(function (pivot) {
      if (pivot.index < state.visibleStartIndex || pivot.index > visibleEndIndex) {
        return;
      }
      const visibleIndex = pivot.index - state.visibleStartIndex;
      const centerX = padding.left + visibleIndex * (candleWidth + spacing) + candleWidth / 2;
      const markerColor = pivot.kind === 'high' ? '#c14b3d' : '#287a72';
      const y = mapPrice(pivot.price, priceMin, priceRange, plotHeight, padding.top) + (pivot.kind === 'high' ? -10 : 10);
      if (pivot.kind === 'high') {
        fragments.push('<polygon points="' + centerX + ',' + (y - 8) + ' ' + (centerX - 6) + ',' + y + ' ' + (centerX + 6) + ',' + y + '" fill="' + markerColor + '" opacity="0.7"></polygon>');
      } else {
        fragments.push('<polygon points="' + centerX + ',' + (y + 8) + ' ' + (centerX - 6) + ',' + y + ' ' + (centerX + 6) + ',' + y + '" fill="' + markerColor + '" opacity="0.7"></polygon>');
      }
    });
    if (selectedCandidate) {
      const startX = padding.left + (selectedCandidate.start_pivot.index - state.visibleStartIndex) * (candleWidth + spacing) + candleWidth / 2;
      const endX = padding.left + (selectedCandidate.end_pivot.index - state.visibleStartIndex) * (candleWidth + spacing) + candleWidth / 2;
      const startY = mapPrice(selectedCandidate.start_pivot.price, priceMin, priceRange, plotHeight, padding.top);
      const endY = mapPrice(selectedCandidate.end_pivot.price, priceMin, priceRange, plotHeight, padding.top);
      if (selectedCandidate.start_pivot.index >= state.visibleStartIndex && selectedCandidate.end_pivot.index <= visibleEndIndex) {
        fragments.push('<line x1="' + startX + '" y1="' + startY + '" x2="' + endX + '" y2="' + endY + '" stroke="#7b5a40" stroke-width="3"></line>');
        fragments.push('<circle cx="' + startX + '" cy="' + startY + '" r="6" fill="#fffdf9" stroke="#7b5a40" stroke-width="2"></circle>');
        fragments.push('<circle cx="' + endX + '" cy="' + endY + '" r="6" fill="#fffdf9" stroke="#7b5a40" stroke-width="2"></circle>');
      }
    }
    elements.chart.setAttribute('viewBox', '0 0 ' + chartWidth + ' ' + chartHeight);
    elements.chart.setAttribute('width', String(chartWidth));
    elements.chart.setAttribute('height', String(chartHeight));
    elements.chart.innerHTML = fragments.join('');
  }

  function renderCandidateTable() {
    elements.candidateRows.innerHTML = state.payload.candidate_legs.map(function (candidate) {
      const selectedClass = candidate.candidate_id === state.selectedCandidateId ? ' is-selected' : '';
      return '<tr class="' + selectedClass.trim() + '" data-candidate-id="' + candidate.candidate_id + '">' +
        '<td>' + candidate.rank + '</td>' +
        '<td>' + candidate.direction.toUpperCase() + '</td>' +
        '<td>' + formatTimestamp(candidate.start_pivot.source_timestamp) + ' @ ' + formatPrice(candidate.start_pivot.price) + '</td>' +
        '<td>' + formatTimestamp(candidate.end_pivot.source_timestamp) + ' @ ' + formatPrice(candidate.end_pivot.price) + '</td>' +
        '<td>' + formatPercent(candidate.metrics.size_score) + '</td>' +
        '<td>' + formatPercent(candidate.metrics.cleanliness_score) + '</td>' +
        '<td>' + formatPercent(candidate.metrics.prominence_score) + '</td>' +
        '<td>' + formatPercent(candidate.metrics.dominance_score) + '</td>' +
        '<td>' + formatPercent(candidate.score) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderViewportCopy() {
    const visibleCandles = state.payload.candles.slice(state.visibleStartIndex, state.visibleStartIndex + state.visibleCount);
    if (visibleCandles.length === 0) {
      elements.viewportCopy.textContent = 'No visible candles.';
      return;
    }
    const candidate = findSelectedCandidate();
    const candidateCopy = candidate ? (' · selected candidate #' + candidate.rank + ' (' + candidate.direction + ')') : '';
    elements.viewportCopy.textContent = 'Showing ' + visibleCandles.length + ' candles · ' + formatTimestamp(visibleCandles[0].source_timestamp) + ' → ' + formatTimestamp(visibleCandles[visibleCandles.length - 1].source_timestamp) + candidateCopy;
  }

  function renderControlState() {
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    elements.panLeft.disabled = state.visibleStartIndex <= 0;
    elements.panRight.disabled = state.visibleStartIndex >= maxStart;
    elements.zoomIn.disabled = state.visibleCount <= MIN_VISIBLE_CANDLES;
    elements.zoomOut.disabled = state.visibleCount >= Math.min(MAX_VISIBLE_CANDLES, state.payload.candles.length);
  }

  function shiftViewport(delta) {
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(state.visibleStartIndex + delta, 0, maxStart);
    renderInspectionSurface();
  }

  function resizeViewport(delta) {
    const currentCenter = state.visibleStartIndex + Math.floor(state.visibleCount / 2);
    state.visibleCount = clamp(state.visibleCount + delta, MIN_VISIBLE_CANDLES, Math.min(MAX_VISIBLE_CANDLES, state.payload.candles.length));
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(currentCenter - Math.floor(state.visibleCount / 2), 0, maxStart);
    renderInspectionSurface();
  }

  function centerOnCandidate(candidateId) {
    state.selectedCandidateId = candidateId;
    const candidate = findSelectedCandidate();
    if (!candidate) {
      return;
    }
    const centerIndex = Math.round((candidate.start_pivot.index + candidate.end_pivot.index) / 2);
    const maxStart = Math.max(0, state.payload.candles.length - state.visibleCount);
    state.visibleStartIndex = clamp(centerIndex - Math.floor(state.visibleCount / 2), 0, maxStart);
    renderInspectionSurface();
  }

  function findSelectedCandidate() {
    return state.payload.candidate_legs.find(function (candidate) {
      return candidate.candidate_id === state.selectedCandidateId;
    }) || null;
  }

  function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }
  function mapPrice(price, priceMin, priceRange, plotHeight, topPadding) { return topPadding + plotHeight - ((price - priceMin) / priceRange) * plotHeight; }
  function formatTimestamp(value) { return String(value || '').replace('T', ' '); }
  function formatShortTimestamp(value) { return formatTimestamp(value).slice(5, 16); }
  function formatPrice(value) { return Number(value).toFixed(1); }
  function formatPercent(value) { return (Number(value) * 100).toFixed(1) + '%'; }
})();