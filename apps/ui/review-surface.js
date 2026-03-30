(function () {
  const state = {
    currentPosition: 1,
    totalStructures: 0,
    currentPayload: null,
    viewing: "current",
    adjustmentMode: false,
    pendingAction: null,
    adjustmentNote: "",
  };

  const elements = {
    marketSymbol: document.getElementById("market-symbol"),
    progressLabel: document.getElementById("progress-label"),
    toggleState: document.getElementById("toggle-state"),
    showCurrentButton: document.getElementById("show-current-button"),
    showPreviousButton: document.getElementById("show-previous-button"),
    reloadButton: document.getElementById("reload-button"),
    positionSummary: document.getElementById("position-summary"),
    statusBanner: document.getElementById("status-banner"),
    marketContextTitle: document.getElementById("market-context-title"),
    marketContextSymbol: document.getElementById("market-context-symbol"),
    marketContextInstrument: document.getElementById("market-context-instrument"),
    marketContextTimeframe: document.getElementById("market-context-timeframe"),
    structureId: document.getElementById("structure-id"),
    directionChip: document.getElementById("direction-chip"),
    viewingLabel: document.getElementById("viewing-label"),
    progressPosition: document.getElementById("progress-position"),
    previousAvailability: document.getElementById("previous-availability"),
    parentAnchorKind: document.getElementById("parent-anchor-kind"),
    parentAnchorPrice: document.getElementById("parent-anchor-price"),
    parentAnchorTimestamp: document.getElementById("parent-anchor-timestamp"),
    terminalExtremeKind: document.getElementById("terminal-extreme-kind"),
    terminalExtremePrice: document.getElementById("terminal-extreme-price"),
    terminalExtremeTimestamp: document.getElementById("terminal-extreme-timestamp"),
    anchorRangeLow: document.getElementById("anchor-range-low"),
    anchorRangeHigh: document.getElementById("anchor-range-high"),
    lifecycleState: document.getElementById("lifecycle-state"),
    pendingAction: document.getElementById("pending-action"),
    goodEnoughButton: document.getElementById("good-enough-button"),
    adjustedAcceptButton: document.getElementById("adjusted-accept-button"),
    flatoutWrongButton: document.getElementById("flatout-wrong-button"),
    adjustmentPanel: document.getElementById("adjustment-panel"),
    adjustmentNoteInput: document.getElementById("adjustment-note-input"),
    cancelAdjustmentButton: document.getElementById("cancel-adjustment-button"),
    finaliseAdjustmentButton: document.getElementById("finalise-adjustment-button"),
    debugPayload: document.getElementById("debug-payload"),
  };

  const API_BASE_URL = window.DB1_REVIEW_API_BASE_URL || "http://127.0.0.1:8000";

  wireEvents();
  loadPosition(1);

  function wireEvents() {
    elements.showCurrentButton.addEventListener("click", function () {
      state.viewing = "current";
      render();
    });

    elements.showPreviousButton.addEventListener("click", function () {
      if (!hasPrevious()) {
        return;
      }
      state.viewing = "previous";
      render();
    });

    elements.reloadButton.addEventListener("click", function () {
      loadPosition(state.currentPosition);
    });

    elements.goodEnoughButton.addEventListener("click", function () {
      finaliseAction("good_enough");
    });

    elements.flatoutWrongButton.addEventListener("click", function () {
      finaliseAction("flatout_wrong");
    });

    elements.adjustedAcceptButton.addEventListener("click", function () {
      state.adjustmentMode = true;
      state.pendingAction = "adjusted_accept";
      setStatus("Adjustment mode active. Review the current structure and finalise when ready.");
      render();
    });

    elements.cancelAdjustmentButton.addEventListener("click", function () {
      state.adjustmentMode = false;
      state.pendingAction = null;
      state.adjustmentNote = "";
      elements.adjustmentNoteInput.value = "";
      setStatus("Adjustment mode cancelled. Current structure remains active.");
      render();
    });

    elements.finaliseAdjustmentButton.addEventListener("click", function () {
      state.adjustmentNote = elements.adjustmentNoteInput.value;
      finaliseAction("adjusted_accept");
    });
  }

  async function loadPosition(position) {
    setStatus("Loading review structure...");
    try {
      const response = await fetch(
        API_BASE_URL + "/db1/review/structures?position=" + String(position)
      );
      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Request failed." };
        });
        throw new Error(errorPayload.error || "Request failed.");
      }
      state.currentPayload = await response.json();
      state.currentPosition = state.currentPayload.progress.current_position;
      state.totalStructures = state.currentPayload.progress.total_structures;
      state.viewing = "current";
      state.adjustmentMode = false;
      state.pendingAction = null;
      elements.adjustmentNoteInput.value = "";
      state.adjustmentNote = "";
      setStatus("Loaded " + state.currentPayload.progress.label + ".");
      render();
    } catch (error) {
      setStatus(String(error.message || error), "error");
    }
  }

  function finaliseAction(action) {
    state.pendingAction = action;
    const nextPosition = state.currentPosition + 1;
    if (nextPosition > state.totalStructures) {
      state.adjustmentMode = false;
      setStatus("Review complete. Final action: " + action + ".", "warning");
      render();
      return;
    }

    setStatus("Finalised " + action + ". Loading next structure...");
    loadPosition(nextPosition);
  }

  function render() {
    if (!state.currentPayload) {
      return;
    }

    const structure = getVisibleStructure();
    const market = state.currentPayload.market_contract;
    const progress = state.currentPayload.progress;

    elements.marketSymbol.textContent = market.tradingview_symbol;
    elements.progressLabel.textContent = progress.label;
    elements.positionSummary.textContent =
      "current: " + progress.current_position + " / " + progress.total_structures;
    elements.marketContextTitle.textContent = market.human_label;
    elements.marketContextSymbol.textContent = market.tradingview_symbol;
    elements.marketContextInstrument.textContent = market.instrument_label;
    elements.marketContextTimeframe.textContent = market.timeframe;

    elements.structureId.textContent = structure.structure_id;
    elements.directionChip.textContent = structure.direction;
    elements.viewingLabel.textContent = state.viewing;
    elements.progressPosition.textContent =
      progress.current_position + " / " + progress.total_structures;
    elements.previousAvailability.textContent = hasPrevious() ? "yes" : "no";

    elements.parentAnchorKind.textContent = structure.parent_anchor_kind;
    elements.parentAnchorPrice.textContent = formatPrice(structure.parent_anchor_price);
    elements.parentAnchorTimestamp.textContent = formatTimestamp(
      structure.parent_anchor_timestamp_utc
    );

    elements.terminalExtremeKind.textContent = structure.terminal_extreme_kind;
    elements.terminalExtremePrice.textContent = formatPrice(
      structure.terminal_extreme_price
    );
    elements.terminalExtremeTimestamp.textContent = formatTimestamp(
      structure.terminal_extreme_timestamp_utc
    );

    elements.anchorRangeLow.textContent = formatPrice(structure.anchor_range_low);
    elements.anchorRangeHigh.textContent = formatPrice(structure.anchor_range_high);
    elements.lifecycleState.textContent = structure.invalidation_reason
      ? "invalidated"
      : "active";
    elements.toggleState.textContent =
      state.viewing === "current"
        ? "Viewing current structure"
        : "Viewing previous structure";
    elements.pendingAction.textContent = state.pendingAction
      ? "Pending action: " + state.pendingAction
      : "No action selected";

    elements.showCurrentButton.classList.toggle(
      "is-active",
      state.viewing === "current"
    );
    elements.showPreviousButton.classList.toggle(
      "is-active",
      state.viewing === "previous"
    );
    elements.showPreviousButton.disabled = !hasPrevious();

    elements.adjustmentPanel.classList.toggle("is-hidden", !state.adjustmentMode);
    elements.debugPayload.textContent = JSON.stringify(
      {
        progress: state.currentPayload.progress,
        current_structure: state.currentPayload.current_structure,
        previous_structure: state.currentPayload.previous_structure,
        adjustment_note: state.adjustmentNote,
      },
      null,
      2
    );
  }

  function getVisibleStructure() {
    if (state.viewing === "previous" && hasPrevious()) {
      return state.currentPayload.previous_structure;
    }
    return state.currentPayload.current_structure;
  }

  function hasPrevious() {
    return Boolean(
      state.currentPayload && state.currentPayload.previous_structure
    );
  }

  function formatPrice(value) {
    return Number(value).toFixed(2);
  }

  function formatTimestamp(value) {
    return String(value).replace("T", " ").replace("+00:00", " UTC");
  }

  function setStatus(message, tone) {
    elements.statusBanner.textContent = message;
    elements.statusBanner.classList.remove("is-warning", "is-error");
    if (tone === "warning") {
      elements.statusBanner.classList.add("is-warning");
    }
    if (tone === "error") {
      elements.statusBanner.classList.add("is-error");
    }
  }
})();