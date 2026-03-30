(function () {
  const state = {
    currentPosition: 1,
    totalStructures: 0,
    currentPayload: null,
    summaryPayload: null,
    viewing: "current",
    adjustmentMode: false,
    pendingAction: null,
    adjustmentNote: "",
    previousComparisonUsed: false,
    lastSubmission: null,
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
    summaryReadinessHint: document.getElementById("summary-readiness-hint"),
    summaryTotalReviewed: document.getElementById("summary-total-reviewed"),
    summaryGoodEnough: document.getElementById("summary-good-enough"),
    summaryAdjustedAccept: document.getElementById("summary-adjusted-accept"),
    summaryFlatoutWrong: document.getElementById("summary-flatout-wrong"),
    summaryPositiveShare: document.getElementById("summary-positive-share"),
    wrongCaseSummaryBlock: document.getElementById("wrong-case-summary-block"),
    wrongCaseReasonList: document.getElementById("wrong-case-reason-list"),
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
    reviewNoteInput: document.getElementById("review-note-input"),
    goodEnoughButton: document.getElementById("good-enough-button"),
    adjustedAcceptButton: document.getElementById("adjusted-accept-button"),
    flatoutWrongButton: document.getElementById("flatout-wrong-button"),
    adjustmentPanel: document.getElementById("adjustment-panel"),
    adjustmentNoteInput: document.getElementById("adjustment-note-input"),
    adjustedParentAnchorTimestamp: document.getElementById(
      "adjusted-parent-anchor-timestamp"
    ),
    adjustedParentAnchorPrice: document.getElementById("adjusted-parent-anchor-price"),
    adjustedTerminalExtremeTimestamp: document.getElementById(
      "adjusted-terminal-extreme-timestamp"
    ),
    adjustedTerminalExtremePrice: document.getElementById(
      "adjusted-terminal-extreme-price"
    ),
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
      state.previousComparisonUsed = true;
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
      state.previousComparisonUsed = false;
      state.lastSubmission = null;
      elements.reviewNoteInput.value = "";
      elements.adjustmentNoteInput.value = "";
      state.adjustmentNote = "";
      populateAdjustmentFields(state.currentPayload.current_structure);
      await loadSummary();
      setStatus("Loaded " + state.currentPayload.progress.label + ".");
      render();
    } catch (error) {
      setStatus(String(error.message || error), "error");
    }
  }

  async function loadSummary() {
    try {
      const response = await fetch(API_BASE_URL + "/db1/review/summary");
      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Summary request failed." };
        });
        throw new Error(errorPayload.error || "Summary request failed.");
      }
      state.summaryPayload = await response.json();
    } catch (error) {
      state.summaryPayload = null;
      throw error;
    }
  }

  async function finaliseAction(action) {
    state.pendingAction = action;
    const submissionPayload = buildSubmissionPayload(action);
    try {
      const response = await fetch(API_BASE_URL + "/db1/review/submissions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(submissionPayload),
      });

      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Review submission failed." };
        });
        throw new Error(errorPayload.error || "Review submission failed.");
      }

      state.lastSubmission = await response.json();
      await loadSummary();
    } catch (error) {
      state.pendingAction = null;
      setStatus(String(error.message || error), "error");
      render();
      return;
    }

    const nextPosition = state.currentPosition + 1;
    if (nextPosition > state.totalStructures) {
      state.adjustmentMode = false;
      setStatus(
        "Review complete. Final action: " + action + ". Submission recorded.",
        "warning"
      );
      render();
      return;
    }

    setStatus("Finalised " + action + ". Submission recorded. Loading next structure...");
    await loadPosition(nextPosition);
  }

  function render() {
    if (!state.currentPayload) {
      return;
    }

    const structure = getVisibleStructure();
    const market = state.currentPayload.market_contract;
    const progress = state.currentPayload.progress;
    const summary = state.summaryPayload ? state.summaryPayload.summary : null;

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
      structure.parent_anchor_source_timestamp
    );

    elements.terminalExtremeKind.textContent = structure.terminal_extreme_kind;
    elements.terminalExtremePrice.textContent = formatPrice(
      structure.terminal_extreme_price
    );
    elements.terminalExtremeTimestamp.textContent = formatTimestamp(
      structure.terminal_extreme_source_timestamp
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
    renderSummary(summary);
    elements.debugPayload.textContent = JSON.stringify(
      {
        progress: state.currentPayload.progress,
        current_structure: state.currentPayload.current_structure,
        previous_structure: state.currentPayload.previous_structure,
        summary: state.summaryPayload ? state.summaryPayload.summary : null,
        previous_structure_comparison_used: state.previousComparisonUsed,
        adjustment_note: state.adjustmentNote,
        last_submission: state.lastSubmission,
      },
      null,
      2
    );
  }

  function buildSubmissionPayload(action) {
    const currentStructure = state.currentPayload.current_structure;
    return {
      structure_id: currentStructure.structure_id,
      proposed_anchor_pair: {
        parent_anchor_source_timestamp:
          currentStructure.parent_anchor_source_timestamp,
        parent_anchor_price: Number(currentStructure.parent_anchor_price),
        terminal_extreme_source_timestamp:
          currentStructure.terminal_extreme_source_timestamp,
        terminal_extreme_price: Number(currentStructure.terminal_extreme_price),
      },
      review_outcome: action,
      adjusted_anchor_pair:
        action === "adjusted_accept"
          ? {
              parent_anchor_source_timestamp:
                elements.adjustedParentAnchorTimestamp.value,
              parent_anchor_price: Number(elements.adjustedParentAnchorPrice.value),
              terminal_extreme_source_timestamp:
                elements.adjustedTerminalExtremeTimestamp.value,
              terminal_extreme_price: Number(elements.adjustedTerminalExtremePrice.value),
            }
          : null,
      note: elements.reviewNoteInput.value || null,
      previous_structure_comparison_used: state.previousComparisonUsed,
    };
  }

  function renderSummary(summary) {
    if (!summary) {
      elements.summaryTotalReviewed.textContent = "-";
      elements.summaryGoodEnough.textContent = "-";
      elements.summaryAdjustedAccept.textContent = "-";
      elements.summaryFlatoutWrong.textContent = "-";
      elements.summaryPositiveShare.textContent = "-";
      elements.summaryReadinessHint.textContent = "summary unavailable";
      elements.summaryReadinessHint.classList.remove("is-continue", "is-kill");
      elements.wrongCaseSummaryBlock.classList.add("is-hidden");
      elements.wrongCaseReasonList.innerHTML = "";
      return;
    }

    elements.summaryTotalReviewed.textContent = String(
      summary.total_reviewed_structures
    );
    elements.summaryGoodEnough.textContent = String(summary.good_enough_count);
    elements.summaryAdjustedAccept.textContent = String(
      summary.adjusted_accept_count
    );
    elements.summaryFlatoutWrong.textContent = String(summary.flatout_wrong_count);
    elements.summaryPositiveShare.textContent = formatShare(
      summary.combined_positive_share
    );
    elements.summaryReadinessHint.textContent = summary.readiness_hint;
    elements.summaryReadinessHint.classList.toggle(
      "is-continue",
      summary.readiness_hint === "continue"
    );
    elements.summaryReadinessHint.classList.toggle(
      "is-kill",
      summary.readiness_hint === "kill and switch"
    );

    const reasonCounts = state.summaryPayload.wrong_case_reason_counts || [];
    elements.wrongCaseSummaryBlock.classList.toggle(
      "is-hidden",
      reasonCounts.length === 0
    );
    elements.wrongCaseReasonList.innerHTML = reasonCounts
      .map(function (reasonCount) {
        return "<li>" + reasonCount.reason + " (" + reasonCount.count + ")</li>";
      })
      .join("");
  }

  function populateAdjustmentFields(structure) {
    elements.adjustedParentAnchorTimestamp.value =
      structure.parent_anchor_source_timestamp;
    elements.adjustedParentAnchorPrice.value = Number(
      structure.parent_anchor_price
    ).toFixed(2);
    elements.adjustedTerminalExtremeTimestamp.value =
      structure.terminal_extreme_source_timestamp;
    elements.adjustedTerminalExtremePrice.value = Number(
      structure.terminal_extreme_price
    ).toFixed(2);
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
    return String(value).replace("T", " ");
  }

  function formatShare(value) {
    return (Number(value) * 100).toFixed(1) + "%";
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