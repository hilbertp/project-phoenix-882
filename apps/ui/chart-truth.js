(function () {
  const API_BASE_URL = window.DB1_REVIEW_API_BASE_URL || "http://127.0.0.1:8000";
  const body = document.body;
  const elements = {
    structureId: document.getElementById("chart-truth-structure-id"),
    direction: document.getElementById("chart-truth-direction"),
    anchor1: document.getElementById("chart-truth-anchor-1"),
    anchor2: document.getElementById("chart-truth-anchor-2"),
  };

  boot();

  async function boot() {
    setState("loading");

    try {
      const payload = await loadFirstStructure();
      const structure = payload.current_structure;
      renderStructure(structure);
      await syncStructure(payload.market_contract, structure);
      setState("synced", "", true);
    } catch (error) {
      setState("error", String(error.message || error), false);
    }
  }

  async function loadFirstStructure() {
    const response = await fetch(API_BASE_URL + "/db1/review/structures?position=1");
    const payload = await response.json().catch(function () {
      return { error: "DB1 structure payload was not valid JSON." };
    });

    if (!response.ok) {
      throw new Error(payload.error || "DB1 structure request failed.");
    }

    if (!payload.current_structure || !payload.market_contract) {
      throw new Error("DB1 structure payload was incomplete.");
    }

    return payload;
  }

  async function syncStructure(marketContract, structure) {
    setState("syncing");
    const response = await fetch(API_BASE_URL + "/db1/review/tradingview/sync", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        market_contract: {
          tradingview_symbol: marketContract.tradingview_symbol,
          timeframe: marketContract.timeframe,
        },
        review_structure: {
          structure_id: structure.structure_id,
          direction: structure.direction,
          parent_anchor_source_timestamp: structure.parent_anchor_source_timestamp,
          parent_anchor_price: structure.parent_anchor_price,
          parent_anchor_kind: structure.parent_anchor_kind,
          terminal_extreme_source_timestamp: structure.terminal_extreme_source_timestamp,
          terminal_extreme_price: structure.terminal_extreme_price,
          terminal_extreme_kind: structure.terminal_extreme_kind,
        },
      }),
    });

    const payload = await response.json().catch(function () {
      return { error: "TradingView sync response was not valid JSON." };
    });

    if (!response.ok) {
      throw new Error(payload.error || "TradingView sync failed.");
    }

    verifyRenderTruth(structure, payload.render_verification);
    window.__db1ChartTruthLastSync = payload;
  }

  function renderStructure(structure) {
    elements.structureId.textContent = structure.structure_id;
    elements.direction.textContent = String(structure.direction || "").toUpperCase();
    elements.anchor1.textContent = formatAnchor(
      structure.parent_anchor_source_timestamp,
      structure.parent_anchor_price
    );
    elements.anchor2.textContent = formatAnchor(
      structure.terminal_extreme_source_timestamp,
      structure.terminal_extreme_price
    );
    document.title = structure.structure_id + " Chart Truth";
  }

  function verifyRenderTruth(structure, renderVerification) {
    if (!renderVerification || renderVerification.verified !== true) {
      throw new Error("TradingView sync did not verify the rendered DB1 fib.");
    }

    const expected = [
      [
        renderVerification.direction,
        structure.direction,
        "direction",
      ],
      [
        renderVerification.parent_anchor_source_timestamp,
        structure.parent_anchor_source_timestamp,
        "anchor 1 timestamp",
      ],
      [
        renderVerification.parent_anchor_price,
        structure.parent_anchor_price,
        "anchor 1 price",
      ],
      [
        renderVerification.terminal_extreme_source_timestamp,
        structure.terminal_extreme_source_timestamp,
        "anchor 2 timestamp",
      ],
      [
        renderVerification.terminal_extreme_price,
        structure.terminal_extreme_price,
        "anchor 2 price",
      ],
    ];

    expected.forEach(function (entry) {
      if (entry[0] !== entry[1]) {
        throw new Error("TradingView sync did not verify the exact DB1 " + entry[2] + ".");
      }
    });
  }

  function formatAnchor(timestamp, price) {
    return formatTimestamp(timestamp) + " @ " + formatPrice(price);
  }

  function formatTimestamp(timestamp) {
    if (typeof timestamp !== "string") {
      return "-";
    }

    return timestamp.replace("T", " ");
  }

  function formatPrice(price) {
    if (typeof price !== "number") {
      return "-";
    }

    return price.toFixed(2);
  }

  function setState(state, errorMessage, verified) {
    body.dataset.chartTruthState = state;
    body.dataset.chartTruthVerified = verified ? "true" : "false";
    body.dataset.chartTruthError = errorMessage || "";
  }
})();